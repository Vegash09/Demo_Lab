---
name: author-sdp-pipeline
description: Author or modify Lakeflow Spark Declarative Pipelines (pyspark.pipelines) in this repo — add tables, materialized views, expectations, quarantine tables, AUTO CDC upserts, or a whole new domain pipeline. Use when the user asks to add/change pipeline code, bronze/silver/gold tables, data quality rules, CDC/upsert logic, or mentions SDP, DLT migration, dp.table, or transformations.
---

# Author an SDP pipeline (pyspark.pipelines)

Pipelines are Python files under `src/<pipeline>/transformations/`, interpreted
by the Lakeflow SDP engine. The bundle resource (`resources/<pipeline>.pipeline.yml`)
points `root_path` at `src/<pipeline>` and globs the transformations folder.

## Hard rules

1. `from pyspark import pipelines as dp` — **never** `import dlt` (deprecated).
2. Dataset functions return a DataFrame. No `.write`, `.saveAsTable`,
   `.start()`, `.collect()`, or other actions inside definitions.
3. Business logic = pure functions in `src/datalab/transforms/<domain>.py`
   with unit tests in `tests/unit/`. Transformation files stay thin wiring.
4. No hardcoded catalogs/schemas/paths. Read parameters with
   `datalab.config.pipeline_conf(spark, "datalab.<key>")` and declare them in
   the pipeline resource `configuration:` mapping.
5. `spark` exists at module scope in pipeline files (runtime-injected); tag
   usages with `# noqa: F821`.

## API cheat sheet

| Need | Use |
|---|---|
| Streaming table (incremental) | `@dp.table(name=..., comment=...)` over `spark.readStream` |
| Batch table / aggregate | `@dp.materialized_view(name=..., comment=...)` over `spark.read` |
| Pipeline-scoped intermediate | `@dp.temporary_view(comment=...)` |
| Append-only multi-source | `@dp.append_flow(target=...)` |
| Upsert / CDC (replaces MERGE & `apply_changes`) | `dp.create_streaming_table(name=...)` + `dp.create_auto_cdc_flow(target=..., source=..., keys=[...], sequence_by=..., stored_as_scd_type=1or2)` |
| DQ warn (keep rows, log metrics) | `@dp.expect_all({name: sql_expr})` |
| DQ drop (remove violating rows) | `@dp.expect_all_or_drop({...})` |
| DQ fail (stop the flow) | `@dp.expect_or_fail(name, sql_expr)` |
| File ingest | `spark.readStream.format("cloudFiles")` (Auto Loader) |

## Layer conventions

- **bronze**: Auto Loader ingest, preserve source, add `_ingest_ts` +
  `_source_file` lineage columns. Table property `datalab.layer: bronze`.
- **silver**: clean via a pure transform → validated view carrying
  expectations → AUTO CDC into the silver table; a quarantine table captures
  rows violating `QUARANTINE_RULES` using
  `datalab.quality.violation_predicate` (one rules dict drives both sides).
  See `src/sales_etl/transformations/silver_customers.py` for the canonical
  shape.
- **gold**: `@dp.materialized_view` aggregates calling a pure summarize
  function.

## Add a table to an existing pipeline

1. Write/extend the pure function + rules dicts in
   `src/datalab/transforms/<domain>.py`; add unit tests.
2. Wire it in `src/<pipeline>/transformations/<layer>_<entity>.py` following
   the cheat sheet.
3. `make lint && make test && make validate`.
4. Verify with a dev refresh: `make run`.

## Add a new domain pipeline (e.g. finance)

1. Create `src/finance_etl/transformations/` (+ a short README like
   `src/sales_etl/README.md`).
2. Copy `resources/sales_etl.pipeline.yml` → `resources/finance_etl.pipeline.yml`;
   rename the resource key, `name`, `root_path`, the libraries glob, and the
   `configuration` keys it needs. Keep `serverless: true`,
   `environment_version`, and the `--editable ${workspace.file_path}`
   dependency.
3. Copy `resources/sales_etl.job.yml` → `resources/finance_etl.job.yml`; point
   `pipeline_task.pipeline_id` at `${resources.pipelines.finance_etl.id}`.
4. Add any new variables to `databricks.yml` (defaults + per-target overrides).
5. New transforms module `src/datalab/transforms/finance.py` + unit tests.
6. `make lint test validate`, then deploy + `databricks bundle run finance_etl -t dev`.

## Done check

- [ ] No `import dlt`, no writes/actions inside dataset functions
- [ ] Logic is in `src/datalab/transforms/` with passing unit tests
- [ ] Parameters declared in the resource `configuration:`; none hardcoded
- [ ] `make lint`, `make test`, `make validate` all pass
- [ ] Dev refresh succeeds (`make run`) and expectations show in the pipeline UI

## Not every target is a pipeline

Run the 3-question router in AGENTS.md ("Authoring rules") before reaching for
SDP: managed medallion Delta table → SDP (this skill); headless side-effectful
edge work (exports, API pulls) → python-file task (`src/jobs/<domain>/` +
`resources/sales_ops.job.yml` shape); human-gated runs → notebook task
(`notebooks/<domain>/`, on-demand, no trigger).
