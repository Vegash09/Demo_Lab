# Migration: legacy DLT-era framework → config-driven Lakeflow SDP

This repo has been through two restructures; this page maps old → current so
history stays navigable.

1. **Legacy** (pre-SDP): an imperative "minimal toolkit" (`src/datalab_etl/`:
   `process_batch`/`process_streaming`, JSON config files, widget-driven
   notebooks, a DQX wrapper, poetry packaging) plus one `import dlt` example.
2. **Intermediate** (hand-written SDP): `pyspark.pipelines` source files with
   `dp.expect_*` expectations and rules dicts in code — replaced in turn by
   the config-driven framework.
3. **Current (flowspec)**: one YAML artifact per target table under
   `config/<domain>/` (this repo's example: `examples/sales/config/sales/`),
   validated by Pydantic, generated into LDP datasets by
   `datalab.framework.generate`, quality by databrickslabs/dqx with
   auto-quarantine. `src/` contains only the framework; complete reference
   domains live under `examples/`. See `docs/FRAMEWORK.md`.

## Concept map (legacy → current)

| Legacy (removed) | Current replacement |
|---|---|
| `import dlt` notebooks | NOTHING hand-written: one YAML artifact per table, generated via `pyspark.pipelines` (the 3-line `transformations/pipeline.py` is the only pipeline code) |
| `process_batch(source, transform, target)` | `target.kind: materialized_view` artifact (+ a registered `@transform` for the logic) |
| `process_streaming(...)` + `foreachBatch` + checkpoints | `target.kind: streaming_table` artifact — the engine manages state/checkpoints; flow names are the checkpoint identity |
| `write_dataset(mode="upsert")` Delta MERGE | `target.cdc:` (AUTO CDC: keys, sequence_by, SCD1/2, deletes/truncates) — never MERGE |
| Full-snapshot dimension reloads | `target.cdc_from_snapshot:` (SDP diffs successive snapshots, SCD1/2) |
| `SimpleDQ` / DQX checks JSON (`criticality: error/warn`) | dqx rules verbatim in the artifact (`columns[].quality` + `quality.checks`); `criticality` kept its meaning |
| DQX quarantine writer | Auto-created `<table>_quarantine` streaming table/MV with `_errors` evidence structs — error rules never silently drop rows |
| `config/**/*.json` (source/target/quality per pipeline) | `config/<domain>/domain.yml` + `<layer>/<table>.yml` artifacts (Pydantic-validated, editor-validated via JSON schemas) |
| Notebook widgets (`get_widget_value`, `load_config`) | `datalab.config.pipeline_conf(spark, "datalab.<key>")` (SDP) / `datalab.params.*` (job lanes) |
| `notebooks/**` + notebook test mirror | Pure functions in the DOMAIN package (`src/<domain>_etl/transforms/`) + pytest; integration = dev refresh (`make run`) |
| `pipelines/*.job.yml` (notebook_task + job cluster yaml) | `resources/*.pipeline.yml` (serverless SDP) + `resources/*.job.yml` (pipeline_task) per domain |
| `permissions/<env>/permission_variables.yml` | `pipeline_permissions` / `job_permissions` complex variables in `databricks.yml` |
| poetry (`poetry.lock`, wheel artifact build) | uv (`uv.lock`, `uv sync --frozen`); pipeline env installs the repo `--editable` — no wheel step |
| `dbconnect` CI integration tests | CI = unit tests (local Spark) + `validate-configs` + `bundle validate`; integration via dev deploys |
| Azure SP secret-based CI auth | GitHub OIDC federation (`docs/CICD.md`) |

## Intermediate → current (if you adopted the hand-written SDP phase)

| Hand-written SDP (intermediate) | Current replacement |
|---|---|
| `@dp.table` / `@dp.materialized_view` source files per table | ONE `<layer>/<table>.yml` artifact; `make validate-configs` replaces "does it import" |
| `@dp.expect_all_or_drop(QUARANTINE_RULES)` / `@dp.expect_all(WARN_RULES)` | dqx rules in the artifact: `criticality: error` (drop + quarantine) / `warn` (flag); `dp.expect_*` is retired in this repo |
| `datalab.quality.violation_predicate` quarantine filter | dqx `get_invalid` + evidence structs (the deprecated `datalab.quality` shims are removed; git history has them) |
| Hand-wired `dp.create_auto_cdc_flow` calls | `target.cdc:` in the artifact |
| `@dp.append_flow(once=True)` backfills by hand | `backfill:` entries in the artifact |
| Rules dicts in `src/datalab/transforms/` | Domain transforms moved to `src/<domain>_etl/transforms/`; the framework owns no domain code |

## Renames to remember

- **DLT → Lakeflow Spark Declarative Pipelines (SDP)**: the `dlt` module is
  deprecated; `pyspark.pipelines` is the API (OSS in Apache Spark 4.1+).
  `@dlt.view` → `@dp.temporary_view`; `dlt.apply_changes` →
  `dp.create_auto_cdc_flow`; `dlt.apply_changes_from_snapshot` →
  `dp.create_auto_cdc_from_snapshot_flow`; `dlt.create_target_table` /
  `create_streaming_live_table` → `dp.create_streaming_table`.
- **Databricks Asset Bundles → Declarative Automation Bundles** (CLI
  v0.295.0): naming only, `databricks bundle` commands unchanged.
- **Repo layout (June 2026)**: `src/sales_etl`, `src/jobs`, `notebooks/sales`,
  `config/sales`, the `resources/sales_*.yml` files and `sql/abac/` moved
  into the self-contained `examples/sales/` tree; `src/` now holds only the
  framework. Adopter repos keep the root-level layout (`examples/README.md`
  maps one to the other).

## Carry-overs

The sales customer flow kept its semantics across all three eras:

- bronze→silver column selection + `to_date(signup_date)` → the artifact's
  `columns:` mapping (ANSI-safe `try_cast`) + the pure
  `sales.normalize_email` transform.
- DQX `is_not_null(customer_id)` (error) and the email regex (warn) → the
  same dqx functions, now per-column `quality:` rules in
  `examples/sales/config/sales/silver/customers.yml`.
- MERGE on `customer_id` → AUTO CDC keyed on `customer_id`, sequenced by the
  `_ingest_ts` lineage column (`target.cdc`).
- Quarantine table `…customer_quarantine` → `silver.customers_quarantine`
  (auto-created, with dqx evidence).

If you need the old code, it lives in git history prior to these
restructures.
