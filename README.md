# datalab

Medallion (bronze → silver → gold) lakehouse framework built on **Lakeflow
Spark Declarative Pipelines** (`pyspark.pipelines`) and shipped as a
**Declarative Automation Bundle** with GitHub OIDC CI/CD.

> AI coding agents and humans: the document of record is **[AGENTS.md](AGENTS.md)**.
> Read it before editing.

## What's here

| Surface | Where | What |
|---|---|---|
| Pipeline code | `src/sales_etl/transformations/` | SDP datasets: `@dp.table`, `@dp.materialized_view`, expectations, AUTO CDC |
| Edge jobs | `src/jobs/` + `notebooks/` | python-file lane (headless exports) + notebook lane (human-gated triage) |
| Shared library | `src/datalab/` | Pure, unit-tested transforms + config/quality/params helpers |
| Deploy | `databricks.yml` + `resources/` | Bundle variables, targets `dev`/`stage`/`prod`, pipeline + jobs |
| Tests | `tests/` | Unit tests on a local SparkSession — no workspace needed |
| CI/CD | `.github/` | ruff + pytest + `bundle validate` on PRs; OIDC deploys on merge/tags |
| Agent harness | `.cursor/`, `.claude/`, `.githooks/` | Rules, skills, PR-template + protected-file guards |
| Docs | `docs/` | [ARCHITECTURE](docs/ARCHITECTURE.md) · [CICD](docs/CICD.md) · [MIGRATION](docs/MIGRATION.md) |

## Quick start

```bash
# prereqs: uv, Java 17+ (local Spark), Databricks CLI >= v0.294.0
make install            # uv sync → .venv from uv.lock
make enable-githooks    # protected-files pre-commit guard
make lint test          # ruff + pytest (local Spark)

databricks auth login --host https://adb-XXXX.azuredatabricks.net
make validate           # bundle validate -t dev
make deploy             # deploy to dev (resources prefixed [dev <you>])
make run                # trigger a refresh of the sales_etl pipeline

databricks bundle run sales_export -t dev             # weekly gold CSV export (python-file lane)
databricks bundle run sales_quarantine_report -t dev  # on-demand quarantine triage (notebook lane)
```

`make help` lists everything.

## The sales_etl pipeline

```
landing volume (JSON)
   │  Auto Loader
   ▼
bronze.customers_raw            @dp.table — raw + lineage (_ingest_ts, _source_file)
   ▼
customers_cleaned               @dp.temporary_view — pure transform (datalab.transforms.sales)
   ▼
customers_validated             @dp.temporary_view — expectations:
   │                              drop  → QUARANTINE_RULES (e.g. customer_id IS NOT NULL)
   │                              warn  → WARN_RULES (e.g. email format)
   ├──────────────▶ silver.customers_quarantine   rows violating QUARANTINE_RULES
   ▼
silver.customers                dp.create_streaming_table + dp.create_auto_cdc_flow
   │                              (upsert by customer_id, ordered by _ingest_ts, SCD1)
   ▼
gold.customers_by_city          @dp.materialized_view — aggregates
```

Catalog, layer schemas, and the landing path are bundle **variables**
(`databricks.yml`) surfaced to code through the pipeline `configuration`
mapping — nothing is hardcoded.

## Authoring rules (the short version)

- Route every new target with the 3-question router (AGENTS.md): managed
  medallion Delta table → **SDP** (mandatory); headless side-effectful edge
  work → **python-file** task; human-must-decide → **notebook** task.
- `from pyspark import pipelines as dp` — never `import dlt` (legacy DLT).
- Dataset functions return DataFrames; the engine owns all writes. Jobs and
  notebooks own their writes but never write SDP-owned tables.
- Upserts via AUTO CDC, data quality via expectations.
- Business logic lives in `src/datalab/transforms/` as pure functions with
  unit tests; pipeline files, job entry points, and notebooks are thin wiring.

Full conventions: [AGENTS.md](AGENTS.md) and the `author-sdp-pipeline` skill
(`.cursor/skills/` / `.claude/skills/`).

## Dependencies (uv)

`pyproject.toml` is the single source of truth; `uv.lock` is committed and CI
installs with `uv sync --frozen`.

```bash
# add/change a dependency
$EDITOR pyproject.toml
make lock      # refresh uv.lock
make install   # sync .venv
```

## Pull requests

One format for every PR: `.github/pull_request_template.md` (marker
`datalab-pr-template`). From the CLI:

```bash
cp .github/pull_request_template.md /tmp/pr-body.md   # fill it in
gh pr create --title "..." --body-file /tmp/pr-body.md
```

Agent hooks block `gh pr create` calls that bypass the template, and
`pr-template-check.yml` re-checks every PR body in CI.
