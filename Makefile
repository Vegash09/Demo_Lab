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
.PHONY: help install lock lint fmt test validate-configs schema validate \
        deploy run destroy bootstrap-uc enable-githooks commit-protected clean \
        sync-skills check-skills spec-local dry-run-local run-local validate-connect design

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
LINT_PATHS := src tests scripts examples

lint: install  ## Ruff lint over src/, tests/, scripts/ and examples/
	$(UV) run ruff check $(LINT_PATHS)

fmt: install  ## Ruff auto-format + fix imports
	$(UV) run ruff format $(LINT_PATHS)
	$(UV) run ruff check --fix $(LINT_PATHS)

test: install  ## Run the unit test suite (local Spark, no workspace needed)
	$(UV) run pytest

# Domain config roots: a root-level config/ (adopter layout) and every
# examples/<domain>/config/ — $(wildcard) drops whichever doesn't exist.
CONFIG_DIRS := $(wildcard config) $(wildcard examples/*/config)

validate-configs: install  ## Validate every domain's <layer>/<table>.yml artifacts (pydantic + dqx checks)
	$(UV) run python -m datalab.framework $(CONFIG_DIRS)

schema: install  ## Regenerate schemas/{domain,table}_config.schema.json from the Pydantic models
	$(UV) run python scripts/export_config_schema.py

# ---- agent skills (one canonical source: .claude/skills) --------------------
sync-skills:  ## Regenerate .cursor/skills + .agents/skills from canonical .claude/skills
	$(UV) run python scripts/sync_skills.py --write

check-skills:  ## Fail if any harness skill mirror drifted from .claude/skills (CI + pre-commit)
	$(UV) run python scripts/sync_skills.py --check

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

# ---- local OSS run (spark-pipelines, no Databricks) -------------------------
# The `local` profile (datalab.framework.local) downgrades the medallion to a
# batch materialized-view graph the OSS `spark-pipelines` CLI can run on sample
# data. Fidelity caveat: CDC is approximated (SCD1 dedup), Auto Loader/sinks are
# skipped — engine-owned semantics are still verified by `make deploy run`.
LOCAL_DOMAIN_CONFIG ?= examples/customer_sales/config/customer_sales
LOCAL_TRANSFORMS    ?= examples/customer_sales/src/customer_sales_etl/transformations
LOCAL_LANDING       ?= $(CURDIR)/examples/customer_sales/sample_data/landing/sales/customers
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
# namespace), so it NEVER enters .venv/uv.lock. This overlay installs it +
# this project (whose [project].dependencies have no pyspark) into a throwaway
# env. Pin DBCONNECT to your workspace's DBR/serverless version. Auth via the
# Databricks SDK env (DATABRICKS_HOST + token/profile, DATABRICKS_CLUSTER_ID or
# serverless). See docs/FRAMEWORK.md "Validate via Databricks Connect".
DBCONNECT      ?= databricks-connect
CONNECT_CONFIG ?= examples/customer_sales/config/customer_sales
LAYER          ?= silver
TABLE          ?= customers

validate-connect:  ## Validate one dataset on a LIVE cluster via isolated Databricks Connect
	$(UV) run --no-project --with-editable . --with "$(DBCONNECT)" \
		python scripts/validate_connect.py \
		--config-dir $(CONNECT_CONFIG) --layer $(LAYER) --table $(TABLE) $(CONNECT_ARGS)

# One-time per target, BEFORE the first deploy. Out-of-band of the bundle so
# `bundle destroy` never touches catalogs/schemas/volumes/grants. Dry run by
# default; pass WAREHOUSE_ID=<sql-warehouse-id> to execute. `--with` keeps
# databricks-sdk out of uv.lock (the dev venv stays pyspark-only).
bootstrap-uc:  ## Print (or apply, with WAREHOUSE_ID=...) UC bootstrap SQL for $(TARGET)
	@if [ -n "$(WAREHOUSE_ID)" ]; then \
		$(UV) run --with databricks-sdk python scripts/bootstrap_uc.py --target $(TARGET) --apply --warehouse-id $(WAREHOUSE_ID); \
	else \
		$(UV) run python scripts/bootstrap_uc.py --target $(TARGET); \
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

# ---- cleanup ----------------------------------------------------------------
clean:  ## Remove .venv and caches
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
