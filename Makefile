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
.PHONY: help install lock lint fmt test validate-configs validate \
        deploy run destroy publish-wheel bootstrap-uc enable-githooks \
        commit-protected clean sync-skills check-skills publish-genie-skills \
        spec-local dry-run-local run-local validate-connect design \
        new-adopter configure-adopter

help:  ## Show available targets
	@printf "\ndatalab · make targets (TARGET=$(TARGET))\n\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\nFirst-time setup:  \033[33mmake install enable-githooks\033[0m\n\n"

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

# Editor schemas (schemas/*.json) are VENDORED here for config validation; they
# are generated FROM the datalab models in the datalab-framework repo (its
# `scripts/export_config_schema.py`). Refresh them when bumping the datalab
# version: regenerate there and copy the JSON over.

# ---- agent skills (one canonical source: .agents/skills) --------------------
# Authored ONCE under .agents/skills (read natively by Cursor + Codex); the
# .claude/skills copy is GENERATED for Claude Code (symlinks are unreliable
# there). Genie Code is reached separately via `publish-genie-skills`.
sync-skills:  ## Regenerate the .claude/skills copy from canonical .agents/skills
	$(UV) run python scripts/sync_skills.py --write

check-skills:  ## Fail if the .claude/skills copy drifted from .agents/skills (CI + pre-commit)
	$(UV) run python scripts/sync_skills.py --check

# Publish the canonical .agents/skills into Databricks Genie Code, whose skills
# live in the Workspace .assistant/skills/ (NOT the repo). Dry-run by default;
# APPLY=1 pushes via `databricks workspace import-dir`. Override the target with
# GENIE_SKILLS_PATH=<ws path> (default /Users/<you>/.assistant/skills) and the
# CLI profile with PROFILE=<name>. See AGENTS.md.
publish-genie-skills:  ## Publish .agents/skills to Genie's Workspace .assistant/skills (dry-run; APPLY=1 to push)
	$(UV) run python scripts/publish_genie_skills.py \
		$(if $(APPLY),--apply,) \
		$(if $(GENIE_SKILLS_PATH),--workspace-dir $(GENIE_SKILLS_PATH),) \
		$(if $(PROFILE),--profile $(PROFILE),)

# ---- design assets (architecture diagrams -> images) ------------------------
# Re-export design/*.drawio to design/images/*.png with the draw.io Desktop CLI
# (set DRAWIO=/path if it isn't on PATH or at the default macOS location). The
# CLI isn't available in CI, so this is a developer/agent step: run it after
# editing a .drawio source and commit the regenerated PNGs. The README, docs/
# and design/OVERVIEW.md embed these images. See the maintain-design-diagram skill.
design:  ## Re-export design/*.drawio diagrams to design/images/*.png (needs draw.io Desktop)
	python3 scripts/export_design.py

# ---- bundle (Declarative Automation Bundle) ---------------------------------
validate:  ## databricks bundle validate -t $(TARGET)
	databricks bundle validate -t $(TARGET)

deploy: validate  ## Deploy the bundle to $(TARGET)
	databricks bundle deploy -t $(TARGET)

run:  ## Trigger a refresh of the customer_sales_etl pipeline on $(TARGET)
	databricks bundle run customer_sales_etl -t $(TARGET)

destroy:  ## Tear down everything the bundle deployed to $(TARGET) (asks first)
	databricks bundle destroy -t $(TARGET)

# The datalab FRAMEWORK wheel is built HERE from the pinned git dependency
# (pyproject.toml [tool.uv.sources].datalab) and uploaded into the `artifacts.wheels`
# UC Volume inside EACH project's own catalog (one upload per project catalog). CI
# runs this in the deploy-dab action BEFORE `bundle deploy` (the version each domain
# references via var.datalab_wheel / var.sales_datalab_wheel must be on its volume
# first). Bump the git tag + var.datalab_version in lockstep when upgrading.
publish-wheel: install  ## Build the framework wheel from the pinned git dep + publish it into each project catalog's artifacts.wheels Volume for $(TARGET) (APPLY=1)
	$(UV) run --with databricks-sdk --with pip python scripts/publish_wheel.py \
		--target $(TARGET) --build \
		$(if $(APPLY),--apply,) \
		$(if $(PROFILE),--profile $(PROFILE),)

# ---- local OSS run (spark-pipelines, no Databricks) -------------------------
# The `local` profile (datalab.framework.local) downgrades the medallion to a
# batch materialized-view graph the OSS `spark-pipelines` CLI can run on sample
# data. Fidelity caveat: CDC is approximated (SCD1 dedup), Auto Loader/sinks are
# skipped — engine-owned semantics are still verified by `make deploy run`.
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

# One-time per target, BEFORE the first deploy. Out-of-band of the bundle so
# `bundle destroy` never touches catalogs/schemas/volumes/grants. Dry run by
# default; pass WAREHOUSE_ID=<sql-warehouse-id> to execute. PROFILE=<cli-profile>
# selects the workspace (the SDK otherwise uses the DEFAULT profile — set it to
# the SAME workspace the bundle target deploys to). SKIP_CATALOGS=1 omits the
# CREATE CATALOG statements when the domain catalogs already exist (e.g. created
# via the UI on a Default-Storage metastore) — it still ensures schemas/volumes/
# grants. `--with` keeps databricks-sdk out of uv.lock (dev venv stays pyspark-only).
bootstrap-uc:  ## Print/apply UC bootstrap SQL for $(TARGET) (WAREHOUSE_ID=… to apply; PROFILE=… picks the workspace; SKIP_CATALOGS=1 if catalogs exist)
	@if [ -n "$(WAREHOUSE_ID)" ]; then \
		$(UV) run --with databricks-sdk python scripts/bootstrap_uc.py --target $(TARGET) --apply --warehouse-id $(WAREHOUSE_ID) $(if $(PROFILE),--profile $(PROFILE),) $(if $(SKIP_CATALOGS),--skip-catalogs,); \
	else \
		$(UV) run python scripts/bootstrap_uc.py --target $(TARGET) $(if $(SKIP_CATALOGS),--skip-catalogs,); \
	fi

# ---- git --------------------------------------------------------------------
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

# ---- adopter scaffold -------------------------------------------------------
# Two ways to turn this reference repo into a customer's single-domain adopter.
# Both run the SAME deterministic engine (scripts/scaffold_adopter.py), so the
# adopter always matches the template structure (config/<catalog>/<schema>/, root
# src/resources) and the workspace-specific surfaces are all repointed — host,
# RBAC groups, deploy SP, AND the MCP grounding config (.mcp.json /
# .cursor/mcp.json: SQL warehouse id + CLI profile, which the old flow ignored).
# CATALOG must be the BASE catalog name — no _dev/_stage/_prod suffix (the bundle
# appends those per target; the engine rejects a suffixed name). docs/ADOPTING.md.

# configure-adopter: convert THIS clone (made from the GitHub template) in place,
# PROMPTING for + confirming every workspace value. This is the path the
# bootstrap-adopter-repo skill drives. Prefill any value to skip its prompt
# (e.g. CATALOG=acme). --no-project: the script is stdlib-only, so it runs before
# `make install` and without touching the (still reference) project env.
configure-adopter:  ## Configure THIS template clone in place into an adopter (interactive; prefill CATALOG=, HOST=, WAREHOUSE_ID=, MCP_PROFILE=, *_GROUP=, DEPLOY_SP=)
	$(UV) run --no-project python scripts/scaffold_adopter.py --in-place --interactive \
		$(if $(CATALOG),--catalog $(CATALOG),) \
		$(if $(HOST),--host $(HOST),) \
		$(if $(WAREHOUSE_ID),--warehouse-id $(WAREHOUSE_ID),) \
		$(if $(MCP_PROFILE),--mcp-profile $(MCP_PROFILE),) \
		$(if $(DEPLOY_SP),--deploy-sp $(DEPLOY_SP),) \
		$(if $(READER_GROUP),--reader-group $(READER_GROUP),) \
		$(if $(ENGINEER_GROUP),--engineer-group $(ENGINEER_GROUP),) \
		$(if $(ADMIN_GROUP),--admin-group $(ADMIN_GROUP),) \
		$(if $(FRAMEWORK_TAG),--framework-tag $(FRAMEWORK_TAG),)

# new-adopter: generate a fresh sibling repo from THIS repo (copies only
# git-TRACKED files — no secrets/state). Required: CATALOG=<name> OUT=<dir>.
# Optional: HOST=, WAREHOUSE_ID=, MCP_PROFILE=, DEPLOY_SP=, READER_GROUP=,
# ENGINEER_GROUP=, ADMIN_GROUP=, FRAMEWORK_TAG=, FORCE=1.
new-adopter:  ## Generate a new adopter repo in a sibling dir (CATALOG=<name> OUT=<dir>; optional HOST=, WAREHOUSE_ID=, MCP_PROFILE=, DEPLOY_SP=, *_GROUP=, FORCE=1)
	@if [ -z "$(CATALOG)" ] || [ -z "$(OUT)" ]; then \
		echo "ERROR: pass CATALOG and OUT:  make new-adopter CATALOG=acme OUT=../acme-datalab"; \
		exit 1; \
	fi
	$(UV) run python scripts/scaffold_adopter.py --catalog $(CATALOG) --out $(OUT) \
		$(if $(HOST),--host $(HOST),) \
		$(if $(WAREHOUSE_ID),--warehouse-id $(WAREHOUSE_ID),) \
		$(if $(MCP_PROFILE),--mcp-profile $(MCP_PROFILE),) \
		$(if $(DEPLOY_SP),--deploy-sp $(DEPLOY_SP),) \
		$(if $(READER_GROUP),--reader-group $(READER_GROUP),) \
		$(if $(ENGINEER_GROUP),--engineer-group $(ENGINEER_GROUP),) \
		$(if $(ADMIN_GROUP),--admin-group $(ADMIN_GROUP),) \
		$(if $(FRAMEWORK_TAG),--framework-tag $(FRAMEWORK_TAG),) \
		$(if $(FORCE),--force,)

# ---- cleanup ----------------------------------------------------------------
clean:  ## Remove .venv and caches
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
