# datalab

Medallion (bronze → silver → gold) lakehouse framework built on **Lakeflow
Spark Declarative Pipelines** (`pyspark.pipelines`) and shipped as a
**Declarative Automation Bundle** with GitHub OIDC CI/CD.

> AI coding agents and humans: the document of record is **[AGENTS.md](AGENTS.md)**.
> Read it before editing.

## What's here

| Surface | Where | What |
|---|---|---|
| Dataset configs | `config/<domain>/` | Per-layer YAML: sources, transforms, dqx quality rules, targets ([guide](docs/FRAMEWORK.md)) |
| Framework | `src/datalab/` | REUSABLE, zero domain code: Pydantic models + LDP adapters + dqx engine + param helpers |
| Domain code | `src/<domain>_etl/` | Pure `@transform` functions, custom dqx checks, 3-line pipeline entrypoint |
| Edge jobs | `src/jobs/` + `notebooks/` | python-file lane (headless exports) + notebook lane (human-gated triage) |
| Deploy | `databricks.yml` + `resources/` | Bundle variables, targets `dev`/`stage`/`prod`, pipeline + jobs |
| Tests | `tests/` | Unit tests on a local SparkSession — no workspace needed |
| CI/CD | `.github/` | ruff + pytest + `bundle validate` on PRs; OIDC deploys on merge/tags |
| Agent harness | `.cursor/`, `.claude/`, `.githooks/` | Rules, skills, PR-template + protected-file guards |
| Docs | `docs/` | [FRAMEWORK](docs/FRAMEWORK.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [CICD](docs/CICD.md) · [MIGRATION](docs/MIGRATION.md) |

## Quick start

```bash
# prereqs: uv, Java 17+ (local Spark), Databricks CLI >= v0.294.0
make install            # uv sync → .venv from uv.lock
make enable-githooks    # protected-files pre-commit guard
make lint test          # ruff + pytest (local Spark)

databricks auth login --host https://dbc-425be768-f138.cloud.databricks.com
make validate           # bundle validate -t dev
make deploy             # deploy to dev (resources prefixed [dev <you>])
make run                # trigger a refresh of the sales_etl pipeline

databricks bundle run sales_export -t dev             # weekly gold CSV export (python-file lane)
databricks bundle run sales_quarantine_report -t dev  # on-demand quarantine triage (notebook lane)
```

`make help` lists everything.

## The sales_etl pipeline

Generated entirely from `config/sales/*.yml` by the framework:

```
landing volume (JSON)
   │  Auto Loader (source: cloud_files + lineage)
   ▼
bronze.customers_raw            streaming table — raw + _ingest_ts/_source_file
   ▼
customers__input                framework view — pure fn sales.clean_customers
   ▼
customers__checked              framework view — dqx checks (_errors/_warnings)
   │                              error → dropped   (valid_customer_id)
   │                              warn  → flagged   (valid_email)
   ├──────────────▶ silver.customers_quarantine   dropped rows + dqx evidence
   ▼  customers__valid
silver.customers                streaming table + AUTO CDC flow
   │                              (upsert by customer_id, ordered by _ingest_ts, SCD1)
   ▼
gold.customers_by_city          materialized view — aggregates
```

Catalog, layer schemas, and the landing path are bundle **variables**
(`databricks.yml`) surfaced to code through the pipeline `configuration`
mapping — nothing is hardcoded.

## Authoring rules (the short version)

- Route every new target with the 3-question router (AGENTS.md): managed
  medallion Delta table → **SDP via YAML config** (mandatory); headless
  side-effectful edge work → **python-file** task; human-must-decide →
  **notebook** task.
- Add a table = add a dataset entry in `config/<domain>/<layer>.yml` —
  source, transform registry names, dqx checks, target kind. No `dp` wiring
  by hand; never `import dlt`.
- Upserts via AUTO CDC (`target.cdc`), data quality via databrickslabs/dqx
  (`quality.checks`, error → quarantine, warn → flagged).
- Business logic lives in `src/<domain>_etl/transforms/` as pure
  `@transform`-registered functions with unit tests.
- Verify without deploying: `make validate-configs`, then
  `notebooks/framework/verify_dataset.py` (`run_dataset` — same code path as
  pytest).

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
