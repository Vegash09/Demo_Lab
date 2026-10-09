# The customer_sales example — a complete framework adoption

This folder is the worked example for the datalab framework: a medallion
(bronze → silver → gold) customer pipeline, generated entirely from YAML
artifacts, plus the two edge-job lanes and the domain's own tests. It mirrors
an adopter repo root and follows the repo's naming contract — **folder paths
mirror the Unity Catalog namespace** (`customer_sales` is the base catalog;
config subfolders are the schemas; see [docs/NAMING.md](../../docs/NAMING.md)).
Copy its contents to your repo and rename every `customer_sales` token to your
catalog (see [projects/README.md](../README.md) for the mapping table, and
[docs/GETTING_STARTED.md](../../docs/GETTING_STARTED.md) for the
step-by-step).

## What it builds

```
landing volume (JSON)
   │  Auto Loader (source: cloud_files + lineage columns)
   ▼
bronze.customers_raw            streaming table — raw + _ingest_ts/_source_file
   ▼
customers__input                framework view — 8 mapped columns (rename/cast)
   │                              + pure fn customer_sales.normalize_email
   ▼
customers__valid                framework view — dqx applied INLINE, then get_valid
   │                              error → dropped   (customer_id_is_not_null)
   │                              warn  → flagged   (email_regex_match)
   ├──────────────▶ silver.customers_quarantine   dropped rows + dqx evidence
   ▼
silver.customers                streaming table + AUTO CDC flow
   │                              (upsert by customer_id, ordered by _ingest_ts, SCD1)
   ▼
gold.customers_by_city          materialized view — aggregates
```

Catalog, layer schemas and the landing path come from bundle variables
(`databricks.yml`) through the pipeline `configuration:` mapping — nothing is
hardcoded anywhere in this folder.

## File-by-file

| File | Role |
|---|---|
| `config/customer_sales/domain.yml` | Domain settings: python `imports:`, catalog/schema **conf keys** per layer (never literal names) |
| `config/customer_sales/bronze/customers_raw.yml` | Auto Loader ingest artifact: `cloud_files` source, schema evolution, lineage columns |
| `config/customer_sales/silver/customers.yml` | The full-featured artifact: column mappings + types, per-column dqx rules, a registered transform, quarantine, AUTO CDC (SCD1) |
| `config/customer_sales/gold/customers_by_city.yml` | Batch aggregate artifact: `materialized_view` over silver |
| `src/customer_sales_etl/transformations/pipeline.py` | The 3-line pipeline entrypoint — `generate(spark, datalab.config_dir)`; never grows beyond 3 lines |
| `src/customer_sales_etl/transforms/customers.py` | Pure DataFrame functions registered `@transform("customer_sales.*")`, unit-tested in `tests/` |
| `src/customer_sales_etl/checks/__init__.py` | Custom dqx check example (`@check_function`) for rules the dqx catalog doesn't cover |
| `src/jobs/customer_sales/export_customer_summary.py` | python-file lane: weekly headless CSV export of gold to the exports volume (reads pipeline tables READ-ONLY) |
| `notebooks/customer_sales/quarantine_report.py` | notebook lane: on-demand, human-gated quarantine triage (no trigger by design) |
| `resources/customer_sales_etl.pipeline.yml` | The SDP pipeline: serverless, `environment_version`, `configuration:` params, framework + domain wheel deps |
| `resources/customer_sales_etl.job.yml` | Daily refresh job (`pipeline_task`; trigger paused automatically in dev) |
| `resources/customer_sales_export.job.yml` | Weekly export job (`spark_python_task` + job parameters from bundle variables) |
| `resources/customer_sales_quarantine_report.job.yml` | On-demand triage job (`notebook_task`, **no trigger**) |
| `tests/test_customers_transforms.py` | Unit tests for the pure transforms |
| `tests/test_run_dataset_contract.py` | End-to-end contract via `run_dataset` — valid rows, quarantine evidence, casts |
| `tests/test_pipeline_graph.py` | Pins the generated LDP dataset/flow graph (`capture_graph`, no Databricks needed) |
| `sql/abac/mask_customer_email.sql` | Display-only column-mask SQL — an admin reviews and applies it; CI/agents never execute it |
| `config/customer_sales/ingestion/mysql/customer_sales_mysql.yml` | Framework-style Lakeflow Connect MySQL source config (managed CDC ingestion) — see [docs/LAKEFLOW_CONNECT_MYSQL.md](../../docs/LAKEFLOW_CONNECT_MYSQL.md) |
| `config/customer_sales/ingestion/mysql/_template.yml` | Short instructions for copying/rendering a real source config after framework v2.0.0 is released |
| `config/customer_sales/bronze/examples/customers_mysql_raw.yml` | Non-deployed bronze example for reading the Lakeflow-ingested table after the raw table exists |
| `resources/examples/customer_sales_mysql_gateway.pipeline.yml` | Non-deployed rendered gateway example; outside the live DAB include glob |
| `resources/examples/customer_sales_mysql_ingest.pipeline.yml` | Non-deployed rendered ingestion example; outside the live DAB include glob |
| `resources/examples/customer_sales_mysql_ingest_schedule.job.yml` | Optional schedule example, kept `PAUSED` |
| `tests/test_mysql_ingestion_contract.py` | Static contract: no live placeholder deployment, source/examples agreement, bootstrap schema coverage |

**Status: staged config, not deployed.** The MySQL resources and bronze reader
are examples only until a real UC Connection, run-as identity, source grants,
and framework v2.0.0 renderer release exist. Full writeup:
[docs/LAKEFLOW_CONNECT_MYSQL.md](../../docs/LAKEFLOW_CONNECT_MYSQL.md).

## Run it

```bash
make validate-configs       # pydantic + dqx validation of the artifacts
make test                   # the example's tests run with the framework suite
make deploy                 # deploy the bundle to dev (prefixed per user)
make run                    # refresh the customer_sales_etl pipeline
databricks bundle run customer_sales_export -t dev              # python-file lane
databricks bundle run customer_sales_quarantine_report -t dev   # notebook lane
```

To verify a single dataset without deploying, call
`datalab.framework.run_dataset(...)` in a test or notebook/REPL (or
`make validate-connect` against a live cluster) with
`config_dir = projects/customer_sales/config/customer_sales`.
