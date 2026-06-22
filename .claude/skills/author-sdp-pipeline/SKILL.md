---
name: author-sdp-pipeline
description: Hand-write Lakeflow SDP (pyspark.pipelines) code for the RARE case the config-driven framework cannot express — after checking the capability matrix. Use when a request needs dp.* wiring beyond the YAML artifact surface (e.g. Kinesis/Pub/Sub sources, preview features) or when extending the framework itself. For normal add/change-a-table requests use the author-ldp-artifact skill instead.
---

# Hand-written SDP code — the escape hatch, not the default

**STOP first**: in this repo a target table is ONE YAML artifact
(`author-ldp-artifact` skill). Hand-written `dp.*` wiring is reserved for
what the framework genuinely cannot express. Check the **SDP capability
matrix** in `docs/FRAMEWORK.md` — fan-in sources, backfills, AUTO CDC
(feed + snapshot), kafka in/out, file batch reads, clustering and MV refresh
policies are ALL config-expressible. If a gap is real, prefer EXTENDING the
framework (models + readers/writers + tests + FRAMEWORK.md) over a one-off
file; one-off wiring is for true edge cases and prototypes.

## Hard rules (apply to any hand-written dataset)

1. `from pyspark import pipelines as dp` — **never** `import dlt` (deprecated).
2. Dataset functions return a DataFrame. No `.write`, `.saveAsTable`,
   `.start()`, `.collect()`, `.count()`, `.toPandas()` inside definitions —
   the engine evaluates them multiple times and owns materialization.
3. Data quality goes through dqx (`datalab.framework.dq`), NOT `dp.expect_*`
   (retired in this repo — quarantine evidence beats event-log metrics).
4. Business logic = pure functions in the DOMAIN package
   (`src/<domain>_etl/transforms/`) with unit tests; the pipeline file stays
   thin wiring placed next to the generated entrypoint
   (`transformations/` folder, globbed by the pipeline resource).
5. No hardcoded catalogs/schemas/paths — declare under the resource
   `configuration:` mapping, read with
   `datalab.config.pipeline_conf(spark, "datalab.<key>")`.
6. `spark` exists at module scope in pipeline files (runtime-injected); the
   transformations folder has a ruff `F821` allowance.
7. Single-writer invariant: never touch tables another pipeline/lane owns.

## Current API cheat sheet (June 2026)

| Need | Use |
|---|---|
| Streaming table | `@dp.table(name=..., comment=...)` over `spark.readStream` |
| Batch table / aggregate | `@dp.materialized_view(...)` over `spark.read` |
| Pipeline-scoped intermediate | `@dp.temporary_view(...)` |
| Fan-in / multi-source append | `dp.create_streaming_table(name=...)` + N × `@dp.append_flow(target=..., name=<stable>)` — flow names are checkpoint identities |
| One-time backfill | `@dp.append_flow(target=..., name=..., once=True)` over a BATCH read; re-runs on full refresh |
| Upsert / CDC (replaces MERGE & `apply_changes`) | `dp.create_streaming_table(...)` + `dp.create_auto_cdc_flow(target=, source=, keys=, sequence_by=, stored_as_scd_type=1|2, apply_as_deletes=, ...)` |
| SCD from full snapshots | `dp.create_auto_cdc_from_snapshot_flow(target=, source=<view or (version)->(df,version) fn>, keys=, ...)` |
| External delta/kafka destination | `dp.create_sink(name, format="delta"|"kafka", options)` + `@dp.append_flow(target=<sink>)` |
| File ingest | `spark.readStream.format("cloudFiles")` (Auto Loader; SDP manages schemaLocation/checkpoints) |
| Stream from an SCD/updated table | `spark.readStream.option("skipChangeCommits", "true").table(...)` or CDF (`readChangeFeed`) |

Databricks-only symbols/knobs (AUTO CDC fns, `once`, `cluster_by_auto`, MV
`refresh_policy`) are missing from local OSS pyspark — route through
`datalab.framework.compat` so local tests/capture stay green.

Avoid (Public Preview, deliberately unused here): `@dp.update_flow`,
`@dp.foreach_batch_sink`, real-time mode, pipeline-level row filters/masks
(ABAC is display-only SQL — see ARCHITECTURE.md).

## If the gap is worth keeping: extend the framework instead

The framework lives in its OWN repo
([dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework)) —
extending it is a change THERE, not in this repo:

1. Model the field(s) in the framework repo's `src/datalab/framework/models.py`
   (+ validators).
2. Read/write it in its `readers.py` / `writers.py` (late-binding rule: closures
   bind loop state via DEFAULT ARGUMENTS only).
3. Add unit tests (`tests/unit/framework/`), regenerate its schemas, and document
   the field + matrix row in its `docs/FRAMEWORK.md` — same commit. Then cut a
   release tag and, here, bump the pin (`pyproject.toml` `[tool.uv.sources]` +
   `var.datalab_version`) + `make publish-wheel`.

## Done check

- [ ] Capability matrix consulted; artifact lane genuinely insufficient
- [ ] No `import dlt`, no writes/actions inside dataset functions, dqx not dp.expect_*
- [ ] Logic in the domain package with passing unit tests
- [ ] Parameters via `configuration:`; nothing hardcoded
- [ ] `make validate-configs lint test validate` pass; dev refresh verified (`make run`)
