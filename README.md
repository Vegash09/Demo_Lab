# datalab

A reusable, config-driven medallion (bronze → silver → gold) lakehouse
framework on **Lakeflow Spark Declarative Pipelines** (`pyspark.pipelines`),
shipped as a **Declarative Automation Bundle** with GitHub OIDC CI/CD.

One target table = **one YAML artifact** (columns + types, dqx quality rules,
CDC/backfills/fan-in, target kind). The framework validates it and generates
all the SDP wiring; quality failures land in auto-created quarantine tables
with evidence. You never write `dp.*` boilerplate, `MERGE` logic, or
checkpoint management.

> AI coding agents and humans: the document of record is **[AGENTS.md](AGENTS.md)**.
> Read it before editing.

## Start here

| You are… | Read |
|---|---|
| Building a pipeline on the framework | **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** — empty folder → deployed pipeline, no framework-team help needed |
| Looking up an artifact field / SDP capability | **[docs/FRAMEWORK.md](docs/FRAMEWORK.md)** — the complete reference + capability matrix |
| Wanting a finished example to copy | **[examples/sales/](examples/sales/README.md)** — complete worked domain, mirrors an adopter repo |
| Understanding the system / governance | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Setting up or debugging deploys | [docs/CICD.md](docs/CICD.md) |
| Migrating from the legacy DLT-era repo | [docs/MIGRATION.md](docs/MIGRATION.md) |

## What's where

| Surface | Where | What |
|---|---|---|
| **Framework** | `src/datalab/` | The ONLY package under `src/` — reusable, zero domain code: Pydantic models, LDP generator, dqx engine, devtools, param helpers. Lifts into any project untouched. |
| **Reference domains** | `examples/` | Complete worked adoptions (currently `sales/`): config artifacts, domain package, edge jobs, notebook, bundle resources, tests, ABAC SQL. Deployed by this repo's bundle; copy one to start your own domain. |
| Dataset configs | `examples/sales/config/sales/` (adopters: `config/<domain>/`) | ONE artifact per target table, per layer |
| Deploy | `databricks.yml` + `examples/*/resources/` | Bundle variables, targets `dev`/`stage`/`prod`, pipeline + jobs |
| Framework tests | `tests/` | Example-free unit tests on a local SparkSession |
| Verify notebook | `notebooks/framework/verify_dataset.py` | Run one dataset through the real framework path — no deploy |
| CI/CD | `.github/` | ruff + pytest + config validation + `bundle validate` on PRs; OIDC deploys on merge/tags |
| Agent harness | `.claude/`, `.cursor/`, `.githooks/` | Skills, PR-template + protected-file guards |

## Quick start

```bash
# prereqs: uv, Java 17+ (local Spark), Databricks CLI >= v0.294.0
make install            # uv sync → .venv from uv.lock
make enable-githooks    # protected-files pre-commit guard
make validate-configs   # validate every domain's YAML artifacts (pydantic + dqx)
make lint test          # ruff + pytest (framework suite + example suites)

databricks auth login --host https://dbc-425be768-f138.cloud.databricks.com
make validate           # bundle validate -t dev
make deploy             # deploy to dev (resources prefixed [dev <you>])
make run                # refresh the sales_etl example pipeline

databricks bundle run sales_export -t dev             # python-file lane example
databricks bundle run sales_quarantine_report -t dev  # notebook lane example
```

`make help` lists everything.

## How a table is born (the whole workflow)

```yaml
# examples/sales/config/sales/silver/customers.yml  (one artifact == one table)
source:  {kind: table, name: customers_raw, layer: bronze, as_stream: true}
columns:
  - name: customer_id
    type: string
    quality: [{criticality: error, check: {function: is_not_null}}]
  - {name: email, type: string}
transform: [{function: sales.normalize_email}]
target:
  kind: streaming_table
  cdc: {keys: [customer_id], sequence_by: _ingest_ts, scd_type: 1}
```

```bash
make validate-configs   # static validation (same loader as CI and the pipeline)
make test               # behavior via run_dataset — valid rows, quarantine, casts
make deploy run         # dev refresh verifies the engine-owned parts (CDC merge)
```

The framework generates: input/checked/valid views → AUTO CDC into
`silver.customers` → rejected rows into `silver.customers_quarantine` with
dqx `_errors` evidence. The full surface (Auto Loader, Kafka in/out, fan-in
`sources:`, `backfill:` once-flows, snapshot CDC, MV refresh policies) is in
[docs/FRAMEWORK.md](docs/FRAMEWORK.md) — including what SDP offers that this
repo deliberately does NOT use, and why.

## Authoring rules (the short version)

- Route every new target with the 3-question router (AGENTS.md): managed
  medallion Delta table → **SDP via YAML artifact** (mandatory, backfills
  included); headless side-effectful edge work → **python-file** task;
  human-must-decide → **notebook** task (no trigger).
- Business logic lives in your domain package (`src/<domain>_etl/transforms/`)
  as pure `@transform`-registered functions with unit tests — never in the
  framework, never as `dp.*` wiring.
- Upserts via `target.cdc` (AUTO CDC), full-snapshot SCD via
  `target.cdc_from_snapshot`, quality via dqx rules (error → quarantine,
  warn → flagged). Never `import dlt`, never hand-written `MERGE`.
- Nothing hardcoded: locations are conf keys resolved per environment by
  bundle variables.

## Dependencies (uv)

`pyproject.toml` is the single source of truth; `uv.lock` is committed and CI
installs with `uv sync --frozen`.

```bash
$EDITOR pyproject.toml && make lock && make install
```

## Branching, PRs, releases

Branch from `main` (`feature/…`, `fix/…`, `debug/…`); one PR per branch using
the unified template (marker `datalab-pr-template` — hook + CI enforce it);
head branches are **deleted automatically on merge**. Merge to `main`
deploys dev; `vX.Y.Z-rcN` tags deploy stage; `vX.Y.Z` tags deploy prod.

```bash
cp .github/pull_request_template.md /tmp/pr-body.md   # fill it in
gh pr create --title "..." --body-file /tmp/pr-body.md
```
