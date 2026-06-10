# sales_etl — Lakeflow Spark Declarative Pipeline

Medallion pipeline for the sales domain. This folder is the pipeline `root_path`
(see `resources/sales_etl.pipeline.yml`); every file under `transformations/`
is pipeline source code interpreted by the SDP engine.

```
transformations/
  bronze_customers.py   Auto Loader ingest of the raw customer feed → bronze
  silver_customers.py   clean + expectations + quarantine + AUTO CDC upsert → silver
  gold_customers.py     business aggregates as materialized views → gold
```

Conventions (enforced — see `AGENTS.md` and the `author-sdp-pipeline` skill):

- `from pyspark import pipelines as dp` — never `import dlt` (deprecated).
- Dataset functions return DataFrames. No `.write`, `.saveAsTable`, `.start()`,
  or `.collect()` inside definitions — the engine owns materialization.
- Business logic lives in `src/datalab/transforms/` as pure functions so it is
  unit-testable; files here only wire those functions into datasets.
- Parameters (catalog, schemas, landing paths) come from the pipeline
  `configuration` mapping — read them with `datalab.config.pipeline_conf`.
  Never hardcode catalogs, schemas, or workspace paths.

Run a development refresh:

```bash
make run          # databricks bundle run sales_etl -t dev
```
