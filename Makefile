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
        deploy run destroy bootstrap-uc enable-githooks commit-protected clean

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
LINT_PATHS := src tests notebooks scripts examples

lint: install  ## Ruff lint over src/, tests/, notebooks/, scripts/ and examples/
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
	$(UV) run python -m datalab.framework.loader $(CONFIG_DIRS)

schema: install  ## Regenerate schemas/layer_config.schema.json from the Pydantic models
	$(UV) run python scripts/export_config_schema.py

# ---- bundle (Declarative Automation Bundle) ---------------------------------
validate:  ## databricks bundle validate -t $(TARGET)
	databricks bundle validate -t $(TARGET)

deploy: validate  ## Deploy the bundle to $(TARGET)
	databricks bundle deploy -t $(TARGET)

run:  ## Trigger a refresh of the sales_etl pipeline on $(TARGET)
	databricks bundle run sales_etl -t $(TARGET)

destroy:  ## Tear down everything the bundle deployed to $(TARGET) (asks first)
	databricks bundle destroy -t $(TARGET)

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
