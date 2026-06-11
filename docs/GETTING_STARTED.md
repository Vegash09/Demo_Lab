# Getting started — build your first pipeline

This walkthrough takes a brand-new domain (`finance`) from empty folder to a
deployed, quality-gated medallion pipeline **without touching the framework
and without asking the framework team**. Every step names the file you create
and the command that proves it works.

Where things are explained in depth:

| Question | Doc |
|---|---|
| What does every artifact field mean? | [FRAMEWORK.md](FRAMEWORK.md) — the reference |
| What does a finished domain look like? | [examples/sales/](../examples/sales/README.md) — copy it |
| How do the pieces fit (lanes, governance)? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How does CI/CD deploy this? | [CICD.md](CICD.md) |
| Conventions, gotchas, protected files | [AGENTS.md](../AGENTS.md) |

## 0. One-time machine setup

Prereqs: [uv](https://docs.astral.sh/uv/), Java 17+ (local Spark for tests),
Databricks CLI ≥ v0.294.0.

```bash
make install            # creates .venv from the committed uv.lock
make enable-githooks    # protected-files pre-commit guard
make lint test          # prove the toolchain works before you write anything
databricks auth login --host <your-workspace-url>
```

## 1. The mental model (60 seconds)

- A **target table = one YAML artifact** at `config/<domain>/<layer>/<table>.yml`.
  You describe *what* (source, columns + types, quality rules, target kind);
  the framework (`src/datalab`) generates all the Lakeflow SDP wiring.
- **Python is only for logic a mapping can't express** — pure functions
  registered with `@transform`, living in your domain package, never in the
  framework.
- **Quality is declarative** (databrickslabs/dqx): `criticality: error` rows
  are dropped into an auto-created `<table>_quarantine` with evidence;
  `warn` rows pass through flagged.
- **Nothing is hardcoded**: catalogs/schemas/paths are conf KEYS resolved per
  environment by bundle variables — promotion never edits your configs.
- Anything that is *not* a managed medallion table (exports, API pulls,
  human-gated triage) is an **edge job**, not a pipeline — see step 8.

## 2. Create the domain skeleton

Copy the example's shape (in an adopter repo these folders sit at the repo
root; in this repo new reference domains live under `examples/<domain>/`):

```
config/finance/domain.yml
config/finance/bronze/  silver/  gold/
src/finance_etl/__init__.py
src/finance_etl/transformations/pipeline.py     # copy VERBATIM from the example
src/finance_etl/transforms/__init__.py
src/finance_etl/checks/__init__.py
```

`config/finance/domain.yml` — the only place your domain names its layers:

```yaml
# yaml-language-server: $schema=<relative path to>/schemas/domain_config.schema.json
schema_version: 1
domain: finance
imports: []                      # add python modules as you create them
catalog_conf: datalab.catalog    # conf KEYS, never literal names
layers:
  bronze: {schema_conf: datalab.bronze_schema}
  silver: {schema_conf: datalab.silver_schema}
  gold:   {schema_conf: datalab.gold_schema}
```

`src/finance_etl/transformations/pipeline.py` is 3 lines and never grows —
copy it from `examples/sales/src/sales_etl/transformations/pipeline.py`.

## 3. Author your first artifacts

**Bronze — incremental file ingest (Auto Loader):**
`config/finance/bronze/invoices_raw.yml`

```yaml
schema_version: 1
name: invoices_raw
comment: Raw invoice feed from the landing volume.
source:
  kind: cloud_files
  path_conf: datalab.finance_landing_path
  format: json
  options:
    cloudFiles.inferColumnTypes: "true"
    cloudFiles.schemaEvolutionMode: addNewColumns
  add_lineage: true              # adds _ingest_ts + _source_file
target:
  kind: streaming_table
```

**Silver — validated, deduplicated, SCD1:**
`config/finance/silver/invoices.yml`

```yaml
schema_version: 1
name: invoices
comment: Current invoice state per invoice_id, validated.
source:
  kind: table
  name: invoices_raw
  layer: bronze                  # resolves via domain.yml — no schema names
  as_stream: true
columns:
  - name: invoice_id
    type: string
    quality:
      - criticality: error       # rows without an id are quarantined
        check: {function: is_not_null}
  - name: amount
    type: decimal(12,2)          # ANSI-safe cast: malformed → NULL
    quality:
      - criticality: warn
        check: {function: is_in_range, arguments: {min_limit: 0}}
  - name: _ingest_ts
    type: timestamp
target:
  kind: streaming_table
  cdc: {keys: [invoice_id], sequence_by: _ingest_ts, scd_type: 1}
```

**Gold — batch aggregate:** `config/finance/gold/revenue_by_month.yml`

```yaml
schema_version: 1
name: revenue_by_month
comment: Monthly invoiced revenue.
source: {kind: table, name: invoices, layer: silver}
transform:
  - function: finance.summarize_revenue
target:
  kind: materialized_view
```

Every field, every source kind (files/kafka/fan-in `sources:`), backfills,
snapshot CDC and sinks: [FRAMEWORK.md](FRAMEWORK.md).

## 4. Add python only where a mapping can't express it

`src/finance_etl/transforms/finance.py`:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from datalab.framework.registry import transform


@transform("finance.summarize_revenue")
def summarize_revenue(df: DataFrame) -> DataFrame:
    return df.groupBy(F.date_trunc("month", "invoice_date").alias("month")).agg(
        F.sum("amount").alias("revenue")
    )
```

Then declare it in `domain.yml`: `imports: [finance_etl.transforms.finance]`
— and add a unit test next to your domain (copy the shape of
`examples/sales/tests/test_sales_transforms.py`).

## 5. Validate before any deploy

```bash
make validate-configs    # pydantic shape + dqx rule validation, exact file+field on failure
make lint test           # ruff + pytest (local Spark)
```

Run a single dataset through the REAL framework path — no workspace needed —
in a test (copy `examples/sales/tests/test_run_dataset_contract.py`) or in
the `notebooks/framework/verify_dataset.py` notebook on Databricks:

```python
from datalab.framework import run_dataset
res = run_dataset(spark, "config/finance", "silver", "invoices",
                  params={...}, inputs={"cat.bronze.invoices_raw": sample_df})
res.valid_df.show(); res.quarantine_df.show()
```

`datalab.framework.devtools.capture_graph(spark, "config/finance")` prints
every dataset/flow the config will generate, locally.

## 6. Wire the bundle

1. Copy `examples/sales/resources/sales_etl.pipeline.yml` →
   `resources/finance_etl.pipeline.yml`; rename the resource key and `name`,
   point `root_path`/`libraries` at `src/finance_etl`, and set
   `datalab.config_dir: ${workspace.file_path}/config/finance`. Keep
   `serverless: true`, `environment_version`, and the
   `--editable ${workspace.file_path}` dependency exactly as they are.
2. Copy `sales_etl.job.yml` → `finance_etl.job.yml` (the scheduled refresh);
   point `pipeline_task.pipeline_id` at
   `${resources.pipelines.finance_etl.id}`.
3. Add your variables (e.g. `finance_landing_path`) to `databricks.yml` and
   pass them through the pipeline's `configuration:` mapping.
4. Add the domain package to `pyproject.toml` →
   `[tool.hatch.build.targets.wheel] packages` (e.g. `"src/finance_etl"`),
   then `make install`.

```bash
make validate            # databricks bundle validate -t dev
```

## 7. Bootstrap UC once, then deploy and run

```bash
make bootstrap-uc TARGET=dev                  # dry-run: prints schemas/volumes/grants SQL
make bootstrap-uc TARGET=dev WAREHOUSE_ID=…   # applies it (one time per target)
make deploy                                   # deploy to dev ([dev <you>] prefixed)
make run                                      # refresh the pipeline
```

Drop a sample file into the landing volume, `make run` again, and check:
silver has the valid rows, `<table>_quarantine` holds the rejects with
`_errors` evidence.

## 8. Edge work is NOT a pipeline

Route with the 3-question router (AGENTS.md "Authoring rules"):
managed medallion table → SDP artifact (always); headless side effects
(exports, API pulls) → python-file task (copy
`examples/sales/src/jobs/sales/` + its job yml); a human must read the run →
notebook task with **no trigger** (copy `examples/sales/notebooks/sales/`).
Jobs/notebooks READ pipeline tables, never write them.

## 9. Ship it

```bash
git switch main && git pull
git switch -c feature/finance-domain     # always branch from main
# … commit …
gh pr create --title "Add finance domain" --body-file /tmp/pr-body.md
```

PR template is enforced (`.github/pull_request_template.md`); CI runs the
same `make` gates you ran locally, merge to `main` auto-deploys dev, tags
promote to stage/prod, and the head branch is deleted on merge
([CICD.md](CICD.md), AGENTS.md "Branching & releases").

## When something fails

| Symptom | Where to look |
|---|---|
| `make validate-configs` fails | The error names file + dotted field + fix; field reference in [FRAMEWORK.md](FRAMEWORK.md) |
| Unknown transform/check/snapshot function | Its module isn't in `domain.yml` `imports:`, or the package isn't in pyproject `packages` |
| Stream fails on UPDATE/DELETE from a source table | Add `options: {skipChangeCommits: "true"}` — see FRAMEWORK.md gotchas |
| `Missing pipeline configuration 'datalab.…'` | Add the key to the pipeline resource `configuration:` mapping |
| `ModuleNotFoundError` on Databricks | `pyproject.toml`/source tree didn't ship (`.databricksignore`) or the env cached an old install — full restart |
| Bundle validate/deploy errors | `deploy-databricks-bundle` skill troubleshooting table; [CICD.md](CICD.md) for OIDC |
| Anything SDP the YAML can't express | The capability matrix in [FRAMEWORK.md](FRAMEWORK.md) — extend the framework, don't hand-wire |
