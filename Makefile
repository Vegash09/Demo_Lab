# =============================================================================
# datalab · developer Makefile
#
# Run `make help` to see what's available.
# `uv` is the package + venv manager: `uv sync` (re)creates .venv from
# uv.lock; `uv run <cmd>` runs <cmd> inside it without activating.
# =============================================================================

SHELL  := /bin/bash
UV     ?= uv
TARGET ?= dev

.DEFAULT_GOAL := help
# Optional sections declare their OWN .PHONY targets next to their rules and are
# fenced `# adopter-if:<feature> start/end`: the adopter scaffold
# (scripts/scaffold_adopter.py) drops a section whose feature the new repo did
# not choose, declaration included. In this repo every section is live.
.PHONY: help install lock lint fmt test validate-configs validate \
        deploy run destroy publish-wheel bootstrap-uc clean \
        check-lockstep check-framework-current bump-framework check-domains \
        check-sync-lists check-changelog release-changelog

help:  ## Show available targets
	@printf "\ndatalab · make targets (TARGET=$(TARGET))\n\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\nFirst-time setup:  \033[33mmake install$(if $(wildcard .githooks), enable-githooks,)\033[0m\n\n"

# ---- python env (uv-managed) ------------------------------------------------
install:  ## Create/refresh .venv from uv.lock (`uv sync`)
	$(UV) sync

lock:  ## Re-resolve dependencies and refresh uv.lock (run after editing pyproject.toml)
	$(UV) lock

# ---- quality gates (same commands CI runs) ----------------------------------
LINT_PATHS := scripts projects

lint: install  ## Ruff lint over scripts/ and projects/
	$(UV) run ruff check $(LINT_PATHS)

fmt: install  ## Ruff auto-format + fix imports
	$(UV) run ruff format $(LINT_PATHS)
	$(UV) run ruff check --fix $(LINT_PATHS)

test: install  ## Run the unit test suite (local Spark, no workspace needed)
	$(UV) run pytest

# Domain config roots: a root-level config/ (adopter layout) and every
# projects/<domain>/config/ — $(wildcard) drops whichever doesn't exist.
CONFIG_DIRS := $(wildcard config) $(wildcard projects/*/config)

validate-configs: install  ## Validate every domain's <layer>/<table>.yml artifacts (pydantic + dqx checks)
	$(UV) run python -m datalab.framework $(CONFIG_DIRS)

# adopter-if:schemas start
# ---- vendored editor schemas (generated from the PINNED framework) ----------
# schemas/*.json power editor validation via the yaml-language-server header in
# every config file. They are GENERATED from the datalab Pydantic models of the
# pinned framework version installed in .venv — never hand-edited, never
# hand-copied from the framework repo (that's how they went stale pre-0.6.0).
.PHONY: sync-schemas check-schemas
sync-schemas: install  ## Regenerate schemas/*.json from the pinned datalab framework
	$(UV) run python scripts/sync_schemas.py --write

check-schemas: install  ## Fail if schemas/*.json drifted from the pinned framework (CI + pre-commit)
	$(UV) run python scripts/sync_schemas.py --check
# adopter-if:schemas end

# ---- framework version lockstep ---------------------------------------------
# The framework version lives in TWO functional places: the `datalab` git tag in
# pyproject.toml [tool.uv.sources] and variables/medallion.yml `datalab_version`
# (the Volume wheel filename), with uv.lock resolving the tag. check-lockstep
# asserts all three agree (CI runs it); bump-framework is the one-shot that
# performs a full, drift-free upgrade.
check-lockstep:  ## Fail if the datalab git tag, var.datalab_version, uv.lock and framework-doc links disagree
	$(UV) run --no-project python scripts/check_lockstep.py

# ---- changelog releases -------------------------------------------------------
# The deploy IS the release: after every successful CI deploy of main, the
# ci-cd.yml `release` job cuts CHANGELOG.md's [Unreleased] into `## [X.Y.Z] — date`
# and moves pyproject [project].version + uv.lock with it (docs/CICD.md "Changelog
# releases"). Nobody cuts by hand — release-changelog previews the cut the next
# deploy will make; APPLY=1 writes it (recovery only, e.g. the bot's push failed).
check-changelog:  ## Fail if CHANGELOG.md is malformed or the repo version drifted from its newest release (CI + pre-commit)
	$(UV) run --no-project python scripts/release_changelog.py check

release-changelog:  ## Preview the changelog release the next deploy cuts (APPLY=1 writes it — recovery only)
	$(UV) run --no-project python scripts/release_changelog.py cut $(if $(APPLY),--apply,)

# Adopting every framework release is MANDATORY in the template (docs/CICD.md
# "Framework bumps"): check-framework-current fails while a newer published
# vX.Y.Z exists; check-framework-surface fails while the authoring skill misses
# a target/source kind of the pinned framework (the corresponding change a
# feature release needs). DATALAB_FRAMEWORK_MANDATE=enforce|warn — enforce by
# default in the template, warn in generated adopters; warn = break-glass.
check-framework-current:  ## Fail if a newer datalab-framework release exists than the pinned tag (CI)
	$(UV) run --no-project python scripts/check_framework_current.py

# adopter-if:schemas&any-agent start
# Reads the vendored schemas/ and the .agents authoring skill, so it ships only
# with both.
.PHONY: check-framework-surface
check-framework-surface:  ## Fail if the authoring skill misses a kind the pinned framework offers (CI + pre-commit)
	$(UV) run --no-project python scripts/check_framework_surface.py
# adopter-if:schemas&any-agent end

# ---- domain registry ---------------------------------------------------------
# scripts/domains.py is the ONE place listing this repo's domains; the per-target
# catalogs/groups are resolved from variables/ + targets/ + rbac.yml (nothing to
# keep in sync by hand). check-domains resolves every target as a smoke check.
check-domains: install  ## Resolve the domain registry against variables/, targets/ and rbac.yml (CI)
	$(UV) run python scripts/domains.py

check-sync-lists: install  ## Fail if databricks.yml sync.exclude and .databricksignore diverged (CI)
	$(UV) run python scripts/check_sync_lists.py

# adopter-if:template start
# The bootstrap-adopter-repo skill's references/templates.md is the documented
# MANUAL FALLBACK for converting a repo by hand. It only earns that role while
# it matches the engine byte for byte — it had silently drifted into shipping an
# uncommentable environment_version and an empty-layer-dir instruction that the
# config validator rejects. This diffs every mirrored code block.
.PHONY: check-templates-doc check-adopter-docs
check-templates-doc:  ## Fail if the adopter templates doc drifted from scripts/scaffold_adopter.py (CI + pre-commit)
	$(UV) run --no-project python scripts/check_templates_doc.py

# Checks a GENERATED adopter (ADOPTER=<dir>; the scaffold smoke test runs it on
# every profile it builds): fails if a surface the adopter reads still names the
# template's workspace, deploy SP or SQL warehouse, or points at a file, doc or
# make target that repo does not have (a dropped component, template-only
# material). Without ADOPTER= it no-ops here — this repo is the template.
check-adopter-docs:  ## Fail if a generated adopter (ADOPTER=<dir>) carries template identity or dangling references (CI)
	$(UV) run --no-project python scripts/check_adopter_docs.py $(if $(ADOPTER),--root $(ADOPTER),)
# adopter-if:template end

# adopter-if:hooked-agent start
# The COMMITTED agent configs (.claude/settings.json, .cursor/hooks.json,
# .codex/hooks.json) are shared with every developer AND copied into every
# generated adopter repo, so a machine-specific path in them is dead weight in
# one place and a leak in the other. Per-developer grants belong in the
# gitignored .claude/settings.local.json, which overrides the tracked file.
.PHONY: check-agent-settings
check-agent-settings:  ## Fail if a committed agent-harness config is tied to one machine (CI + pre-commit)
	$(UV) run --no-project python scripts/check_agent_settings.py
# adopter-if:hooked-agent end

bump-framework:  ## Upgrade the framework pin end to end (VERSION=x.y.z): pyproject tag + datalab_version + uv.lock + schemas
	@if [ -z "$(VERSION)" ]; then \
		echo "ERROR: pass the new framework version:  make bump-framework VERSION=0.7.0"; \
		exit 1; \
	fi
	$(UV) run --no-project python scripts/bump_framework.py --version $(VERSION)
	$(UV) lock
	$(UV) sync
# adopter-if:schemas start
	$(UV) run python scripts/sync_schemas.py --write
# adopter-if:schemas end
	$(UV) run --no-project python scripts/check_lockstep.py
# adopter-if:schemas&any-agent start
	@$(UV) run --no-project python scripts/check_framework_surface.py || \
		echo "NOTE: document the new kinds in the authoring skill (part of this bump) — CI gates it."
# adopter-if:schemas&any-agent end
	@echo "Framework pinned to $(VERSION). Add the release's corresponding changes (framework CHANGELOG), record the bump in CHANGELOG.md, commit, then make publish-wheel APPLY=1 per target."

# adopter-if:any-agent start
# ---- agent skills (one canonical source: .agents/skills) --------------------
# Authored ONCE under .agents/skills (read natively by Cursor + Codex); the
# .claude/skills copy is GENERATED for Claude Code (symlinks are unreliable
# there). Genie Code is reached separately via `publish-genie-skills`.
# adopter-if:any-agent end
# adopter-if:agent-claude start
.PHONY: sync-skills check-skills
sync-skills:  ## Regenerate the .claude/skills copy from canonical .agents/skills
	$(UV) run python scripts/sync_skills.py --write

check-skills:  ## Fail if the .claude/skills copy drifted from .agents/skills (CI + pre-commit)
	$(UV) run python scripts/sync_skills.py --check
# adopter-if:agent-claude end

# adopter-if:agent-genie start
# Publish the canonical .agents/skills into Databricks Genie Code, whose skills
# live in the Workspace .assistant/skills/ (NOT the repo). Dry-run by default;
# APPLY=1 pushes via `databricks workspace import-dir`. Override the target with
# GENIE_SKILLS_PATH=<ws path> (default /Users/<you>/.assistant/skills) and the
# CLI profile with PROFILE=<name>. See AGENTS.md.
.PHONY: publish-genie-skills
publish-genie-skills:  ## Publish .agents/skills to Genie's Workspace .assistant/skills (dry-run; APPLY=1 to push)
	$(UV) run python scripts/publish_genie_skills.py \
		$(if $(APPLY),--apply,) \
		$(if $(GENIE_SKILLS_PATH),--workspace-dir $(GENIE_SKILLS_PATH),) \
		$(if $(PROFILE),--profile $(PROFILE),)
# adopter-if:agent-genie end

# adopter-if:design start
# ---- design package (estate -> diagrams + images + pipeline inventory) -------
# Everything in design/ except OVERVIEW.md and estate.yml is GENERATED:
#   * design/PIPELINES.md  <- the config/ artifacts (scripts/design_inventory.py)
#   * design/*.drawio      <- config/ + resources/*.yml + targets/ + workflows +
#     design/estate.yml, laid out through the vendored drawio-architecture-designer
#     kit (scripts/design_diagram.py, scripts/design_spec.py, scripts/drawio_kit/)
#   * design/images/*.png  <- the .drawio files, via the draw.io Desktop CLI (set
#     DRAWIO=/path if it isn't on PATH or at the default macOS location), else the
#     kit's HTML twin when playwright is installed, else skipped with a note.
# `check-design` (CI + pre-commit) regenerates the inventory and both diagrams in
# memory and fails on drift, a hand edit, or any layout-audit finding (text
# overflow, colour, colliding cards, an arrow through a card). Never edit the
# .drawio XML - see the maintain-design-diagram skill.
.PHONY: design check-design design-preview
design: install  ## Regenerate design/: PIPELINES.md, the .drawio diagrams from the estate, and their PNGs
	$(UV) run python scripts/design_inventory.py --write
	$(UV) run python scripts/design_diagram.py --write
	$(UV) run python scripts/export_design.py --if-available

check-design: install  ## Fail if design/PIPELINES.md or design/*.drawio is stale, hand-edited, or fails the layout audit (CI)
	$(UV) run python scripts/design_inventory.py --check
	$(UV) run python scripts/design_diagram.py --check

design-preview: install  ## Render the diagrams' HTML twin + PNGs into .design-preview/ to LOOK at before committing
	$(UV) run --with playwright python scripts/design_diagram.py --preview .design-preview
# adopter-if:design end

# ---- bundle (Declarative Automation Bundle) ---------------------------------
validate:  ## databricks bundle validate -t $(TARGET)
	databricks bundle validate -t $(TARGET)

deploy: validate  ## Deploy the bundle to $(TARGET)
	databricks bundle deploy -t $(TARGET)

# Any deployed pipeline/job resource works: PIPELINE=sales_etl refreshes the
# second reference domain (it has no scheduled job — on-demand by design).
PIPELINE ?= customer_sales_etl

run:  ## Trigger a refresh of a pipeline on $(TARGET) (PIPELINE=<resource>, default customer_sales_etl)
	databricks bundle run $(PIPELINE) -t $(TARGET)

destroy:  ## Tear down everything the bundle deployed to $(TARGET) (asks first)
	databricks bundle destroy -t $(TARGET)

# The datalab FRAMEWORK wheel is built HERE from the pinned git dependency
# (pyproject.toml [tool.uv.sources].datalab) and uploaded into the `artifacts.wheels`
# UC Volume inside EACH project's own catalog (one upload per project catalog). CI
# runs this in the deploy-dab action BEFORE `bundle deploy` (the version each domain
# references via var.datalab_wheel / var.sales_datalab_wheel must be on its volume
# first). Bump the git tag + var.datalab_version in lockstep when upgrading.
publish-wheel: install  ## Build the framework wheel from the pinned git dep + publish it into each project catalog's artifacts.wheels Volume for $(TARGET) (APPLY=1)
	$(UV) run --with databricks-sdk python scripts/publish_wheel.py \
		--target $(TARGET) --build \
		$(if $(APPLY),--apply,) \
		$(if $(PROFILE),--profile $(PROFILE),)

# adopter-if:local-dev start
# ---- local OSS run (spark-pipelines, no Databricks) -------------------------
# The `local` profile (datalab.framework.local) downgrades the medallion to a
# batch materialized-view graph the OSS `spark-pipelines` CLI can run on sample
# data. Fidelity caveat: CDC is approximated (SCD1 dedup), Auto Loader/sinks are
# skipped — engine-owned semantics are still verified by `make deploy run`.
.PHONY: spec-local dry-run-local run-local validate-connect
LOCAL_DOMAIN_CONFIG ?= projects/customer_sales/config/customer_sales
LOCAL_TRANSFORMS    ?= projects/customer_sales/src/customer_sales_etl/transformations
LOCAL_LANDING       ?= $(CURDIR)/projects/customer_sales/sample_data/landing/sales/customers
# The OSS CLI globs libraries relative to the spec dir, so the spec lives at the
# repo root (an ancestor of the transformations dir).
LOCAL_SPEC          ?= spark-pipeline.local.yml

spec-local: install  ## Generate the OSS spark-pipeline.yml for a local run
	$(UV) run python -m datalab.framework.local \
		--config-dir $(LOCAL_DOMAIN_CONFIG) \
		--transformations $(LOCAL_TRANSFORMS) \
		--out $(LOCAL_SPEC) \
		--storage $(CURDIR)/.build/local-storage \
		--conf datalab.sales_landing_path=file://$(LOCAL_LANDING)

dry-run-local: spec-local  ## Validate the pipeline graph locally (no data) — spark-pipelines dry-run
	$(UV) run spark-pipelines dry-run --spec $(LOCAL_SPEC)

run-local: spec-local  ## Materialize the medallion locally on sample data — spark-pipelines run
	$(UV) run spark-pipelines run --spec $(LOCAL_SPEC)

# ---- Databricks Connect validation (isolated, out-of-lock) ------------------
# databricks-connect conflicts with the dev `pyspark` (both own the `pyspark`
# namespace), so it NEVER enters .venv/uv.lock. This `--no-project` overlay
# installs databricks-connect + the framework (from the pinned git dep, which has
# no pyspark) + the domain package (editable, no runtime deps) into a throwaway
# env — the package-less root project can't supply them. Pin DBCONNECT to your
# workspace's DBR/serverless version. Auth via the Databricks SDK env
# (DATABRICKS_HOST + token/profile, DATABRICKS_CLUSTER_ID or serverless). See the
# framework repo's docs/FRAMEWORK.md "Run anywhere".
DBCONNECT      ?= databricks-connect
CONNECT_CONFIG ?= projects/customer_sales/config/customer_sales
CONNECT_DOMAIN ?= projects/customer_sales
LAYER          ?= silver
TABLE          ?= customers
# The framework requirement, derived from pyproject's [tool.uv.sources].datalab so
# there's no separate version pin to maintain (recursively expanded: the $(shell)
# runs only when validate-connect references it).
DATALAB_GIT_REQ = $(shell $(UV) run python -c 'import tomllib,pathlib;d=tomllib.loads(pathlib.Path("pyproject.toml").read_text())["tool"]["uv"]["sources"]["datalab"];print("datalab @ git+"+d["git"]+"@"+(d.get("tag") or d.get("rev") or d.get("branch")))')

validate-connect:  ## Validate one dataset on a LIVE cluster via isolated Databricks Connect
	$(UV) run --no-project \
		--with "$(DATALAB_GIT_REQ)" --with-editable $(CONNECT_DOMAIN) --with "$(DBCONNECT)" \
		python scripts/validate_connect.py \
		--config-dir $(CONNECT_CONFIG) --layer $(LAYER) --table $(TABLE) $(CONNECT_ARGS)
# adopter-if:local-dev end

# One-time per target, BEFORE the first deploy. Out-of-band of the bundle so
# `bundle destroy` never touches catalogs/schemas/volumes/grants. Dry run by
# default; pass WAREHOUSE_ID=<sql-warehouse-id> to execute. PROFILE=<cli-profile>
# selects the workspace (the SDK otherwise uses the DEFAULT profile — set it to
# the SAME workspace the bundle target deploys to). SKIP_CATALOGS=1 omits the
# CREATE CATALOG statements when the domain catalogs already exist (e.g. created
# via the UI on a Default-Storage metastore) — it still ensures schemas/volumes/
# grants. `--with` keeps databricks-sdk out of uv.lock (dev venv stays pyspark-only).
# MANAGED_LOCATION and SKIP_GRANTS were previously unreachable from `make` — the
# script defined the flags but the recipe never passed them, so the documented
# Default-Storage remedy could not actually be run through the Makefile.
BOOTSTRAP_FLAGS := $(if $(SKIP_CATALOGS),--skip-catalogs,) \
                   $(if $(SKIP_GRANTS),--skip-grants,) \
                   $(if $(MANAGED_LOCATION),--managed-location $(MANAGED_LOCATION),) \
                   $(if $(PROFILE),--profile $(PROFILE),)

bootstrap-uc:  ## Print/apply UC bootstrap SQL for $(TARGET) (WAREHOUSE_ID=… to apply; PROFILE=… picks the workspace; SKIP_CATALOGS=1 if catalogs exist)
	@if [ -n "$(WAREHOUSE_ID)" ]; then \
		$(UV) run --with databricks-sdk python scripts/bootstrap_uc.py --target $(TARGET) --apply --warehouse-id $(WAREHOUSE_ID) $(BOOTSTRAP_FLAGS); \
	else \
		$(UV) run python scripts/bootstrap_uc.py --target $(TARGET) $(BOOTSTRAP_FLAGS); \
	fi

# adopter-if:githooks start
# ---- git --------------------------------------------------------------------
.PHONY: enable-githooks commit-protected
enable-githooks:  ## Enable the repo's pre-commit guard for protected files
	git config core.hooksPath .githooks
	@echo "  core.hooksPath -> .githooks"

# `commit-protected` sets PROTECTED_EDIT_OK=1 so the .githooks/pre-commit guard
# lets a commit touching protected files through. Prefer this over
# `git commit --no-verify`, which skips every hook.
commit-protected:  ## Commit staged changes past the protected-files guard (make commit-protected MSG="...")
	@if [ -z "$(MSG)" ]; then \
		echo "ERROR: pass a message:  make commit-protected MSG=\"your message\""; \
		exit 1; \
	fi
	PROTECTED_EDIT_OK=1 git commit -m "$(MSG)"
# adopter-if:githooks end

# adopter-if:template start
# ---- adopter scaffold -------------------------------------------------------
# Two ways to turn this reference repo into a customer's single-domain adopter.
# Both run the SAME deterministic engine (scripts/scaffold_adopter.py), so the
# adopter always matches the template structure (config/<catalog>/<schema>/, root
# src/resources) and the workspace-specific surfaces are all repointed — host,
# RBAC groups, deploy SP, AND the MCP grounding config (.mcp.json /
# .cursor/mcp.json: SQL warehouse id + CLI profile, which the old flow ignored).
# CATALOG must be the BASE catalog name — no _dev/_stage/_prod suffix (the bundle
# appends those per target; the engine rejects a suffixed name). docs/ADOPTING.md.
#
# Every value below is optional on the command line (VAR=value) and prefills the
# matching question of the configurator's form (skipping it). AGENTS= picks the
# coding agents (claude,codex,cursor,genie | all | none) and COMPONENTS= the
# optional components (docs,design,schemas,local-dev,githooks,pr-template,
# dependabot,framework-bot,mcp | all | none | default, or +x/-x edits such as
# COMPONENTS=+design,-githooks). ANSWERS=<file> replays a previous run's
# .datalab-adopter.json. Only COMMAND-LINE values are forwarded: make also
# imports environment variables, and generic names like HOST or REPO are
# exported by some shells/CI images — one must never leak into a customer repo.
# `--flag=value` (not `--flag value`) so a value starting with `-` — e.g.
# COMPONENTS=-githooks — is not mistaken for another option.
scaffold_arg = $(if $(filter command line,$(origin $(1))),$(2)="$($(1))",)
SCAFFOLD_FLAGS = \
	$(call scaffold_arg,CATALOG,--catalog) \
	$(call scaffold_arg,CUSTOMER,--customer) \
	$(call scaffold_arg,DESCRIPTION,--description) \
	$(call scaffold_arg,REPO,--repo) \
	$(call scaffold_arg,HOST,--host) \
	$(call scaffold_arg,HOST_STAGE,--host-stage) \
	$(call scaffold_arg,HOST_PROD,--host-prod) \
	$(call scaffold_arg,CATALOG_DEV,--catalog-dev) \
	$(call scaffold_arg,CATALOG_STAGE,--catalog-stage) \
	$(call scaffold_arg,CATALOG_PROD,--catalog-prod) \
	$(call scaffold_arg,WAREHOUSE_ID,--warehouse-id) \
	$(call scaffold_arg,MCP_PROFILE,--mcp-profile) \
	$(call scaffold_arg,DEPLOY_SP,--deploy-sp) \
	$(call scaffold_arg,READER_GROUP,--reader-group) \
	$(call scaffold_arg,ENGINEER_GROUP,--engineer-group) \
	$(call scaffold_arg,ADMIN_GROUP,--admin-group) \
	$(call scaffold_arg,FRAMEWORK_TAG,--framework-tag) \
	$(call scaffold_arg,AGENTS,--agents) \
	$(call scaffold_arg,COMPONENTS,--components) \
	$(call scaffold_arg,ANSWERS,--answers)

# configure-adopter: convert THIS clone (made from the GitHub template) in place.
# Interactive by default: a short form (identity → workspace & environments →
# access → coding agents → components → framework) with a default for every
# question, then a keep/drop summary to confirm. YES=1 runs it non-interactively
# (needs CATALOG= or ANSWERS=). This is the path the bootstrap-adopter-repo skill
# drives. --no-project: the script is stdlib-only, so it runs before
# `make install` and without touching the (still reference) project env.
.PHONY: configure-adopter new-adopter
configure-adopter:  ## Configure THIS template clone in place into an adopter (interactive form; prefill CATALOG=, HOST=, AGENTS=, COMPONENTS=, ...; YES=1 non-interactive)
	$(UV) run --no-project python scripts/scaffold_adopter.py --in-place \
		$(if $(YES),--yes,--interactive) $(SCAFFOLD_FLAGS)

# new-adopter: generate a fresh sibling repo from THIS repo (copies only
# git-TRACKED files — no secrets/state). Required: OUT=<dir>. With CATALOG= or
# ANSWERS= it runs non-interactively (the CI/agent path); with neither — or with
# INTERACTIVE=1 — it walks the same form as configure-adopter. FORCE=1
# overwrites a non-empty OUT. --no-project (same as configure-adopter): the
# script is stdlib-only, so this must not sync the project env — that would
# demand read access to the private framework repo before the newcomer's first
# command can even run.
new-adopter:  ## Generate a new adopter repo in a sibling dir (OUT=<dir>; CATALOG=/ANSWERS= for non-interactive; AGENTS=, COMPONENTS=, FORCE=1)
	@if [ -z "$(OUT)" ]; then \
		echo "ERROR: pass OUT:  make new-adopter OUT=../acme-datalab [CATALOG=acme]"; \
		exit 1; \
	fi
	$(UV) run --no-project python scripts/scaffold_adopter.py --out "$(OUT)" \
		$(if $(or $(INTERACTIVE),$(if $(or $(CATALOG),$(ANSWERS)),,1)),--interactive,--yes) \
		$(SCAFFOLD_FLAGS) $(if $(FORCE),--force,)
# adopter-if:template end

# ---- cleanup ----------------------------------------------------------------
clean:  ## Remove .venv and caches
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
