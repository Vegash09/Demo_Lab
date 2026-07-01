# Adopter repo file templates

Ready-to-paste contents for a fresh single-domain adopter repo at the repo
ROOT. Replace every placeholder before writing:

- `<catalog>` — the **base** Unity Catalog catalog / domain name (e.g. `acme`).
  The domain package is `<catalog>_etl`, the pipeline is `<catalog>_etl`. BASE
  name only — **no `_dev`/`_stage`/`_prod` suffix**: the bundle appends the
  environment per target (`acme` → `acme` / `acme_stage` / `acme_prod`), so a
  suffixed name yields `config/<catalog>_prod/` and a doubled `..._prod_prod`
  catalog. (`docs/NAMING.md`.)
- `<owner>` / `<customer-repo>` — the new repo's GitHub owner / name.
- `<host>` — the customer's Databricks workspace URL.
- `<warehouse-id>` — a SQL warehouse id in the customer's workspace (UC bootstrap
  + the MCP grounding config).
- `<cli-profile>` — the `databricks auth login` profile for the read-only MCP
  grounding (default `<catalog>_dev`).
- `<deploy-sp-app-id>` — the CI/CD deploy service principal application id.
- `<reader-group>` / `<engineer-group>` / `<admin-group>` — workspace groups.
- `<framework-tag>` — the pinned `datalab` framework release tag (keep the same
  value in `pyproject.toml` and `var.datalab_version`).

These mirror `projects/customer_sales/` but with ROOT-relative paths and a
single root `pyproject.toml`. Field reference: the framework `docs/FRAMEWORK.md`.

> The `scripts/scaffold_adopter.py` engine writes all of these automatically —
> both `make configure-adopter` (convert a template clone in place) and
> `make new-adopter` (fresh sibling repo) call it. This doc is the human-readable
> reference + manual fallback; keep the two in sync when either changes.

---

## Minimal domain

### `config/<catalog>/domain.yml`

```yaml
# yaml-language-server: $schema=../../schemas/domain_config.schema.json
schema_version: 1
domain: <catalog>
imports: [] # add python modules (transforms/checks) as you create them
catalog_conf: datalab.catalog
layers:
  bronze:
    schema_conf: datalab.bronze_schema
    table_properties:
      datalab.layer: bronze
  silver:
    schema_conf: datalab.silver_schema
    table_properties:
      datalab.layer: silver
  gold:
    schema_conf: datalab.gold_schema
    table_properties:
      datalab.layer: gold
```

### `config/<catalog>/bronze/events_raw.yml`

One Auto Loader bronze table to prove the toolchain. Add silver/gold later with
the `author-ldp-artifact` skill (leave empty `config/<catalog>/silver/` and
`config/<catalog>/gold/` folders).

```yaml
# yaml-language-server: $schema=../../../schemas/table_config.schema.json
schema_version: 1
name: events_raw
comment: Raw events ingested incrementally from the landing volume (Auto Loader).
source:
  kind: cloud_files
  path_conf: datalab.landing_path
  format: json
  options:
    cloudFiles.inferColumnTypes: "true" # quote YAML-1.1 ambiguous scalars
    cloudFiles.schemaEvolutionMode: addNewColumns
  add_lineage: true # framework adds _ingest_ts + _source_file
target:
  kind: streaming_table
```

### `src/<catalog>_etl/__init__.py`

```python
"""<catalog>_etl — the <catalog> domain's adoption of the datalab framework.

Domain-owned code only: transforms/ (pure functions), checks/ (custom dqx
checks), transformations/pipeline.py (the LDP entrypoint). The reusable
framework lives in ``datalab`` and is never edited from here.
"""
```

### `src/<catalog>_etl/transformations/pipeline.py`

Copy verbatim — this 3-line entrypoint never grows; tables are added in YAML.

```python
"""<catalog>_etl pipeline entrypoint — the entire domain is config-driven.

Datasets, transforms and dqx quality rules live in the domain's config dir (the
bundle supplies the deployed path as ``datalab.config_dir``); the framework
validates them and registers every LDP dataset. Add a table by editing YAML —
see docs/GETTING_STARTED.md.
"""

from pyspark.sql import SparkSession

from datalab.config import pipeline_conf
from datalab.framework import generate

# The active session is the SDP-runtime session on Databricks and the session the
# OSS `spark-pipelines` CLI creates locally — one entrypoint, every profile.
spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
generate(spark, pipeline_conf(spark, "datalab.config_dir"))
```

### `src/<catalog>_etl/transforms/__init__.py` and `src/<catalog>_etl/checks/__init__.py`

Empty package markers (add functions later):

```python
"""Pure @transform functions for the <catalog> domain (registered via decorators)."""
```

```python
"""Custom @check_function dqx checks for the <catalog> domain."""
```

### `tests/conftest.py`

```python
"""Local SparkSession fixture for the <catalog> domain tests."""

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .appName("<catalog>-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
```

---

## Bundle resources (root-level)

### `resources/<catalog>_etl.pipeline.yml`

Paths are relative to THIS file (which now sits at `resources/`, beside `src/`
and `dist/`): `../src/...` and `../dist/...` (NOT `../../../` as in the
reference repo, where resources sit under `projects/<catalog>/resources/`).

```yaml
# Lakeflow Spark Declarative Pipeline for the <catalog> domain (bronze→silver→gold).
resources:
  pipelines:
    <catalog>_etl:
      name: <catalog>_etl
      catalog: ${var.catalog}
      schema: ${var.silver_schema}
      serverless: true
      channel: CURRENT
      root_path: "../src/<catalog>_etl"

      libraries:
        - glob:
            include: ../src/<catalog>_etl/transformations/**

      environment:
        environment_version: "4"
        dependencies:
          # datalab FRAMEWORK wheel from THIS catalog's artifacts.wheels Volume
          # (make publish-wheel; bump var.datalab_version to roll it). Serverless
          # does NOT honor an --editable install of synced workspace files.
          - ${var.datalab_wheel}
          # This domain's wheel — built by the bundle's <catalog>_etl_wheel artifact.
          - ../dist/<catalog>_etl-*.whl

      configuration:
        datalab.env: ${bundle.target}
        datalab.catalog: ${var.catalog}
        datalab.bronze_schema: ${var.bronze_schema}
        datalab.silver_schema: ${var.silver_schema}
        datalab.gold_schema: ${var.gold_schema}
        datalab.landing_path: ${var.landing_path}
        datalab.config_dir: ${workspace.file_path}/config/<catalog>

      permissions: ${var.pipeline_permissions}
```

### `resources/<catalog>_etl.job.yml`

```yaml
# Scheduled refresh of the <catalog>_etl pipeline (paused in dev).
resources:
  jobs:
    <catalog>_etl_refresh:
      name: <catalog>_etl_refresh
      trigger:
        periodic:
          interval: 1
          unit: DAYS
      tasks:
        - task_key: refresh_<catalog>_etl
          pipeline_task:
            pipeline_id: ${resources.pipelines.<catalog>_etl.id}
      queue:
        enabled: true
      permissions: ${var.job_permissions}
```

---

## Repo-level files

### `databricks.yml`

```yaml
bundle:
  name: <catalog>

# One wheel: this domain's package (uv build at the root). The framework wheel
# is delivered separately from the UC Volume (var.datalab_wheel).
artifacts:
  <catalog>_etl_wheel:
    type: whl
    build: uv build --wheel
    path: .

include:
  - variables/*.yml
  - targets/*.yml
  - rbac.yml
  - resources/*.yml

sync:
  exclude:
    - tests
    - docs
    - .github
    - .claude
    - .cursor
    - .codex
    - .agents
    - .githooks
    - Makefile
    - uv.lock
    - .markdownlint.json
```

### `pyproject.toml`

Single buildable package at the root (NO uv workspace — that is only for the
multi-domain reference repo).

```toml
# <catalog> — single-domain adopter repo for the datalab framework.
#
# The reusable FRAMEWORK lives in dediggibyte/datalab-framework and is consumed:
#   * local dev / CI         → the `datalab` git dependency (pinned to a tag);
#   * Databricks serverless  → the versioned wheel from this catalog's
#     artifacts.wheels UC Volume (var.datalab_wheel), listed in each resource.
# KEEP IN LOCKSTEP: the `datalab` git tag below and var.datalab_version.

[build-system]
requires      = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name            = "<catalog>_etl"
version         = "0.1.0"
description     = "<catalog> medallion (bronze→silver→gold) — datalab adopter domain."
requires-python = ">=3.12,<3.14"
dependencies    = []

[tool.hatch.build.targets.wheel]
packages = ["src/<catalog>_etl"]

[dependency-groups]
dev = [
    "pytest>=8.4",
    "ruff>=0.14",
    # Local Spark for tests + the OSS local-run profile. Never add
    # databricks-connect here (conflicts with pyspark; use `make validate-connect`).
    "pyspark[pipelines]>=4.1.0",
    "pandas>=2.0",
    # The framework, pinned to a release tag (source mapped to git below). Keep
    # the tag in lockstep with var.datalab_version (the serverless UC-Volume wheel).
    "datalab",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts   = "-ra --tb=short"

[tool.ruff]
line-length    = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["datalab", "<catalog>_etl"]

[tool.ruff.lint.per-file-ignores]
# `spark` is injected by the SDP runtime in the pipeline entrypoint; notebooks
# additionally get ambient dbutils/display (F821) + cell imports (E402).
"src/*/transformations/**" = ["F821"]
"notebooks/**" = ["F821", "E402"]

[tool.uv]
managed = true

[tool.uv.sources]
datalab = { git = "https://github.com/dediggibyte/datalab-framework.git", tag = "<framework-tag>" }
```

### `variables/medallion.yml`

```yaml
variables:
  catalog:
    description: Unity Catalog catalog that holds the medallion schemas.
    default: <catalog>
  bronze_schema:
    description: Schema for raw/ingested data.
    default: bronze
  silver_schema:
    description: Schema for cleaned, validated data.
    default: silver
  gold_schema:
    description: Schema for business-level aggregates.
    default: gold
  landing_path:
    description: UC volume path where raw JSON files land (Auto Loader source).
    default: /Volumes/${var.catalog}/landing/<catalog>/events/
  # --- framework wheel distribution (lockstep with the datalab git tag) -------
  datalab_version:
    description: Version of the datalab framework wheel installed from this catalog's artifacts.wheels volume.
    default: "<framework-tag-without-v>"
  datalab_wheel:
    description: UC Volume path of the framework wheel in this catalog (var.catalog).
    default: /Volumes/${var.catalog}/artifacts/wheels/datalab-${var.datalab_version}-py3-none-any.whl
```

### `targets/dev.yml`

```yaml
targets:
  dev:
    mode: development
    default: true
    workspace:
      host: <host>
    variables:
      catalog: <catalog>
```

### `targets/stage.yml`

```yaml
targets:
  stage:
    mode: production
    workspace:
      host: <host>
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: <catalog>_stage
```

### `targets/prod.yml`

```yaml
targets:
  prod:
    mode: production
    workspace:
      host: <host>
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: <catalog>_prod
```

### `rbac.yml`

Keep the reference `rbac.yml` structure verbatim (the string-var + complex-var
pivot). Only change the group-name defaults and per-target overrides:

- `reader_group.default` → `<reader-group>`
- `engineer_group.default` → `<engineer-group>`
- `admin_group.default` → `<admin-group>`
- in `targets.stage.variables` / `targets.prod.variables`, set the stage/prod
  group names (and prod read levels) for the customer.

---

## Files to EDIT in place (not full rewrites)

### `Makefile`

- `LINT_PATHS := scripts src`
- `run:` recipe → `databricks bundle run <catalog>_etl -t $(TARGET)`
- `LOCAL_DOMAIN_CONFIG ?= config/<catalog>`
- `LOCAL_TRANSFORMS ?= src/<catalog>_etl/transformations`
- `LOCAL_LANDING ?= $(CURDIR)/sample_data/landing/<catalog>/events`
- in `spec-local`, the `--conf datalab.sales_landing_path=...` → `--conf datalab.landing_path=file://$(LOCAL_LANDING)`
- `CONNECT_CONFIG ?= config/<catalog>` and `CONNECT_DOMAIN ?= .`
- `CONFIG_DIRS` already picks up the root `config/` — leave it (or simplify to `CONFIG_DIRS := config`).

### `scripts/bootstrap_uc.py`

```python
CATALOGS = {
    "dev":   [("<catalog>",        True)],
    "stage": [("<catalog>_stage",  True)],
    "prod":  [("<catalog>_prod",   True)],
}

GROUPS = {
    "dev":   {"reader": "<reader-group>", "engineer": "<engineer-group>"},
    "stage": {"reader": "<reader-group>", "engineer": "<engineer-group>"},
    "prod":  {"reader": "<reader-group>", "engineer": "<engineer-group>"},
}

DEPLOY_SP = "<deploy-sp-app-id>"
```

`scripts/publish_wheel.py` needs no edit — it reads `CATALOGS` from
`bootstrap_uc`.

### `.github/workflows/common-ci-steps.yml`

- Ruff step: `uv run ruff check scripts projects` → `uv run ruff check scripts src`.
- The config-validation loop `for d in config projects/*/config` already matches
  the root `config/` — leave it (or simplify to `config`).
- Keep the GitHub App token steps ("Mint a read-only token for datalab-framework"
  + the HTTPS `insteadOf` rewrite). The adopter repo must set the
  `DATALAB_FRAMEWORK_APP_CLIENT_ID` variable + `DATALAB_FRAMEWORK_APP_PRIVATE_KEY` secret
  (from the shared datalab-framework reader GitHub App) and have read access to the
  (private) framework repo, or `uv sync` fails in CI.

### `.databricksignore`

Align with the new `databricks.yml` `sync.exclude` — remove any `projects/*`
lines; keep the rest.

### `README.md`, `CHANGELOG.md`

Rewrite `README.md` for the customer (title, intro, the `make run <catalog>_etl`
quick start; drop the `projects/customer_sales` + `projects/sales` references).
Reset `CHANGELOG.md`. The `docs/` are reusable framework guidance — keep them,
but fix repo-specific references (workspace host, any `projects/...` paths).

### `.mcp.json` and `.cursor/mcp.json` (the MCP grounding config)

Both ship pointing at the TEMPLATE's read-only-query workspace — repoint them at
the customer's, or the adopter's agents query the wrong workspace. Swap the CLI
profile `diggi_dev_aws` → `<cli-profile>` and warehouse id `c1cdbe2406e5cf04` →
`<warehouse-id>` in BOTH files. `.mcp.json` keeps its `${VAR:-default}` env
override; `.cursor/mcp.json` holds the literals. A placeholder `<warehouse-id>`
is fine for now (the MCP is opt-in/dev-time and `.mcp.json`'s env var overrides
it) — fill it before relying on the grounding (`docs/AGENT_MCP.md`).

```jsonc
// .mcp.json — the two args that carry the workspace identity
"--profile", "${DATABRICKS_CONFIG_PROFILE:-<cli-profile>}",
"--meta",    "warehouse_id=${DATABRICKS_SQL_WAREHOUSE_ID:-<warehouse-id>}"
// .cursor/mcp.json — same two values, as literals
"--profile", "<cli-profile>",
"--meta",    "warehouse_id=<warehouse-id>"
```
