# Migration: legacy DLT-era framework → Lakeflow SDP

This repo previously shipped an imperative "minimal toolkit"
(`src/datalab_etl/`: `process_batch`/`process_streaming`, JSON config files,
widget-driven notebooks, a DQX wrapper, poetry packaging) plus one legacy DLT
example. All of it was replaced in the restructure. This page maps old → new
so history stays navigable.

## Concept map

| Legacy (removed) | Replacement |
|---|---|
| `import dlt` notebooks | `from pyspark import pipelines as dp` source files in `src/<pipeline>/transformations/` |
| `process_batch(source, transform, target)` | SDP datasets: `@dp.table` / `@dp.materialized_view` over the transform |
| `process_streaming(...)` + `foreachBatch` + checkpoints | `@dp.table` streaming reads — the engine manages state/checkpoints |
| `write_dataset(mode="upsert")` Delta MERGE | `dp.create_streaming_table` + `dp.create_auto_cdc_flow(keys, sequence_by, stored_as_scd_type)` |
| `SimpleDQ` / DQX checks JSON (`criticality: error/warn`) | Expectations: `@dp.expect_all_or_drop(QUARANTINE_RULES)` (error) / `@dp.expect_all(WARN_RULES)` (warn) in `src/datalab/transforms/` |
| DQX quarantine writer | `customers_quarantine` table filtering with `datalab.quality.violation_predicate` |
| `config/**/*.json` (source/target/quality per pipeline) | Bundle variables (`databricks.yml`) + pipeline `configuration:` mapping + rules dicts in code |
| Notebook widgets (`get_widget_value`, `load_config`) | `datalab.config.pipeline_conf(spark, "datalab.<key>")` |
| `notebooks/**` + notebook unit/integration test mirror | Pure functions in `src/datalab/transforms/` + `tests/unit/`; integration = dev refresh (`make run`) |
| `pipelines/*.job.yml` (notebook_task + job cluster yaml) | `resources/*.pipeline.yml` (serverless SDP) + `resources/*.job.yml` (pipeline_task) |
| `permissions/<env>/permission_variables.yml` | `pipeline_permissions` / `job_permissions` complex variables in `databricks.yml` |
| poetry (`poetry.lock`, wheel artifact build) | uv (`uv.lock`, `uv sync --frozen`); pipeline env installs the repo `--editable` — no wheel step |
| `dbconnect` CI integration tests | CI = unit tests (local Spark) + `bundle validate`; integration via dev deploys |
| Azure SP secret-based CI auth | GitHub OIDC federation (`docs/CICD.md`) |

## Renames to remember

- **DLT → Lakeflow Spark Declarative Pipelines (SDP)**: `dlt` module is
  deprecated; `pyspark.pipelines` is the API (OSS in Apache Spark 4.1+).
  `@dlt.view` → `@dp.temporary_view`; `dlt.apply_changes` →
  `dp.create_auto_cdc_flow`; `dlt.create_streaming_table` keeps its name.
- **Databricks Asset Bundles → Declarative Automation Bundles** (CLI
  v0.295.0): naming only, `databricks bundle` commands unchanged.

## Carry-overs

The sales customer flow kept its semantics:

- bronze→silver column selection + `to_date(signup_date)` →
  `datalab.transforms.sales.clean_customers` (now also casts age, normalizes
  email).
- DQX `is_not_null(customer_id)` (error) → `QUARANTINE_RULES`;
  email regex (warn) → `WARN_RULES`.
- MERGE on `customer_id` → AUTO CDC keyed on `customer_id`, sequenced by the
  new `_ingest_ts` lineage column.
- Quarantine table `…customer_quarantine` → `silver.customers_quarantine`.

If you need the old code, it lives in git history prior to this restructure.
