---
name: author-ldp-artifact
description: Create or modify a pipeline table from a natural-language request by authoring its YAML artifact (config/<domain>/<layer>/<table>.yml) — column mappings with data types, dqx data-quality rules, CDC/upsert targets. Use when the user asks to create/change a table, job, or pipeline, add columns, or add data-quality rules in plain language.
---

# Author an LDP artifact from a natural-language request

This repo is a config-driven framework: a target table is ONE YAML artifact.
You never write `dp.*` wiring. Full reference (every field + the SDP
capability matrix): `docs/FRAMEWORK.md`, which links the framework's reference
AT THE PINNED VERSION (`pyproject.toml` `[tool.uv.sources]`) — never author
against a feature newer than the pin. Every kind the pinned framework offers is
listed under "Source and target kinds" below (CI checks this list against the
vendored schema: `make check-framework-surface`).

## Where the artifact goes

`config/<catalog>/<schema>/<table>.yml` — the path mirrors the UC namespace
(`docs/NAMING.md`): the folder is the domain's BASE CATALOG name, the
subfolder is the target table's schema (medallion layer), and the **file name
must equal the target table name**. The domain's `domain.yml` maps layers →
schema conf keys and lists the python `imports:`. In THIS repo the domains
live under `projects/<catalog>/config/`
(e.g. `projects/customer_sales/config/customer_sales/silver/customers.yml`);
adopter repos use root-level `config/<catalog>/`.

**Never hardcode a catalog or schema name.** Locations are pipeline-conf KEYS
(`datalab.catalog`, `datalab.silver_schema`, …) resolved per environment by
bundle variables — promotion to stage/prod must never require editing an
artifact. If a request names a catalog literally, map it to the conf key.

## Artifact recipe

```yaml
# yaml-language-server: $schema=<relative path to>/schemas/table_config.schema.json
schema_version: 1
name: <table>                  # == file name
comment: <one line, business language>
source:                        # where the data comes from (OR sources:, below)
  kind: table                  #   table | cloud_files | files | view | kafka |
                               #   sql | python | snapshot_function (kinds below)
  name: <upstream table>
  layer: <upstream layer>      #   resolves via domain.yml (preferred)
  as_stream: true              #   stream for incremental, omit for batch
  options: {}                  #   reader options verbatim (e.g.
                               #   skipChangeCommits when streaming from an
                               #   SCD/CDC table; readChangeFeed for CDF)
columns:                       # target columns: source→target + type + rules
  - name: <target col>         #   target column name
    source: <source col>       #   omit when identical
    type: <spark type>         #   casts are ANSI-safe (malformed → NULL)
    quality: [...]             #   this column's dqx rules (see below)
transform:                     # only logic a mapping can't express
  - function: <domain>.<fn>    #   @transform-registered pure function
    args: {k: v}               #   extra kwargs (${conf:<key>} resolves here)
    tables:                    #   extra TABLES the fn reads — resolved to a
      <kwarg>: {name: <t>, layer: <l>}   #   per-env FQN, passed as that kwarg
quality:                       # table-level rules + quarantine settings
  checks: [...]                #   multi-column / dataset-level dqx rules
  quarantine: {}               #   error rules AUTO-quarantine even without this
target:
  kind: streaming_table        #   streaming_table | managed_table |
                               #   materialized_view | temporary_view |
                               #   delta_sink | kafka_sink | foreach_batch_sink
  cdc:                         #   upsert/SCD from a change feed (streaming source)
    keys: [<business key>]
    sequence_by: <ordering col>   # list for tiebreaks: [ts, seq_no]
    scd_type: 1                #   2 for history tracking (__START_AT/__END_AT)
    # apply_as_deletes / apply_as_truncates / column_list / except_columns /
    # ignore_null_updates / track_history_*: see docs/FRAMEWORK.md
    # partial updates (ONE NULL-handling form): ignore_null_updates_columns /
    # ignore_null_updates_except_columns / columns_to_update (an array<string>
    # column — list it under columns: so it survives the projection)
```

### Source and target kinds

| `source.kind` | Use for |
|---|---|
| `table` | a UC table — batch, or `as_stream: true` for incremental; `change_data_feed: true` reads its CDF |
| `view` | a dataset defined earlier in the SAME pipeline (streams by default) |
| `cloud_files` | files landing in cloud storage, ingested incrementally (Auto Loader) |
| `files` | a BATCH read of files — materialized views and backfills |
| `kafka` | Kafka / Event Hubs / MSK (`bootstrap_servers_conf` is a conf KEY) |
| `sql` | a batch SELECT (`${conf:<key>}` placeholders; same-pipeline datasets by short name) |
| `python` | a registered `@dataframe_source` function (JDBC pulls, custom connectors) |
| `snapshot_function` | a `@snapshot_source` walker over historical snapshot SETS — only with `cdc_from_snapshot` |

| `target.kind` | Use for |
|---|---|
| `streaming_table` | incremental append; + `cdc:` (upsert/SCD), + `cdc_from_snapshot:`, + `replace_where:` (atomic predicate-slice replace, single BATCH source) |
| `managed_table` | a plain, NON-streaming managed table fed by append flows (`sources:` fan-in + batch `backfill:`), no CDC / `replace_where` — framework ≥ 1.0.0, SDP **Beta**, Databricks runtime only (the local profile makes it an MV); the workspace must have the managed-tables Beta enabled; it can't take over an existing table's name (switching `kind` = drop + reprocess) |
| `materialized_view` | batch tables and aggregates ("normal delta tables") |
| `temporary_view` | pipeline-scoped / dynamic views (quality is annotate-only) |
| `delta_sink` | streaming append to an EXTERNAL Delta table or path |
| `kafka_sink` | publish to Kafka (value column via `framework.to_json_value`) |
| `foreach_batch_sink` | any other destination: a `@batch_sink` handler `fn(df, batch_id, **args)` writes each micro-batch — keep it idempotent on `batch_id`; may run SQL `BEGIN ATOMIC … END;` transactions |

Choosing `target.kind`: incremental/append → `streaming_table`; upsert/SCD
from a change feed → `streaming_table` + `cdc`; SCD from periodic FULL
snapshots (nightly dumps) → `streaming_table` + `cdc_from_snapshot` (batch
source); rolling-window batch reprocessing → `streaming_table` +
`replace_where`; append-only table that must be a plain, NON-streaming managed
table → `managed_table`; batch table or aggregate ("normal delta table") →
`materialized_view`; pipeline-scoped/dynamic view → `temporary_view`;
external destinations → `delta_sink` / `kafka_sink`, or `foreach_batch_sink`
when no built-in sink fits.

NL cues for the rest of the surface (details: `docs/FRAMEWORK.md`):

| User says | Authoring move |
|---|---|
| "from both/all of …", "merge the EU and US feeds" | `sources:` fan-in list (one NAMED flow per feed — names are checkpoint identities, keep them stable) |
| "load the history / one-time backfill" | `backfill:` entry (batch source for plain tables, STREAMING source when the target has `cdc:`); it re-runs on full refresh by design |
| "from Kafka / Event Hubs / MSK" | `source.kind: kafka` (`bootstrap_servers_conf` is a conf KEY; decode value in columns/transforms) |
| "read the files as a batch / one-off folder" | `source.kind: files` (MVs and backfills) |
| "we get a full dump every night, keep history" | `target.cdc_from_snapshot` (+ `@snapshot_source` function for historical snapshot SETS) |
| "publish to Kafka" | `target.kind: kafka_sink` + `transform: [{function: framework.to_json_value, args: {key: <id>}}]` |
| "cluster/partition by …" | `cluster_by:` / `cluster_by_auto: true` / `partition_cols:` (clustering XOR partitioning) |
| "the MV must never silently full-recompute" | `target.refresh_policy: incremental_strict` |
| "reprocess the last N days on every run" | `target.replace_where: <SQL predicate>` (streaming_table, one BATCH source, no fan-in/backfill) |
| "several feeds into ONE plain (non-streaming) table" | `target.kind: managed_table` + `sources:` (Beta; append flows only) |
| "move our existing Structured Streaming job here without reprocessing" | `sources[].import_checkpoint_conf: <conf key holding the checkpoint path>` on a `managed_table` or sink target (imported on the flow's FIRST update only; stop the old job first) |
| "write every micro-batch to our API / JDBC / two places at once" | `target.kind: foreach_batch_sink` + a `@batch_sink` handler in `src/<domain>_etl/` |
| "only update the columns present in each change", "NULL must not overwrite X" | `cdc.columns_to_update: <array col>` / `cdc.ignore_null_updates_columns: [...]` (or `_except_columns`) |
| "threshold differs per environment" in a dq rule | `{{ name }}` in the rule + `domain.yml` `dq.variables_conf: [datalab.name]` (substituted since framework 1.0.0; an undeclared placeholder fails `make validate-configs`) |

## Natural language → dqx rules

Rules are databrickslabs/dqx metadata, verbatim. Column-scoped rules go under
the column (the framework injects `check.arguments.column` and a
`<column>_<function>` rule name — the dqx rule-generator naming convention);
multi-column/dataset rules go under `quality.checks` with explicit arguments.
Always map the request to the MOST SPECIFIC dqx function — `sql_expression` /
`sql_query` are last resorts, never shortcuts. Argument names are validated
statically (`make validate-configs`); full catalog:
[dqx checks reference](https://databrickslabs.github.io/dqx/docs/reference/quality_checks/).

Column-level (row-scoped, under `columns[].quality`):

| User says | dqx check |
|---|---|
| "required", "not null", "must have" | `is_not_null` |
| "not empty/blank" | `is_not_null_and_not_empty` (`is_not_empty` if NULL is fine) |
| "non-empty array" | `is_not_null_and_not_empty_array` |
| "one of [A, B, C]", "allowed values" | `is_in_list {allowed}` (`is_not_null_and_is_in_list` if also required) |
| "never one of", "forbidden values" | `is_not_in_list {forbidden}` |
| "between X and Y", "at least/most N" | `is_in_range {min_limit, max_limit}` (`is_not_in_range` for outside) |
| "equals / must not equal X" | `is_equal_to` / `is_not_equal_to` |
| "no less/greater than <col or value>" | `is_not_less_than` / `is_not_greater_than` |
| "valid email/phone/code pattern" | `regex_match {regex}` |
| "parseable date/timestamp string" | `is_valid_date` / `is_valid_timestamp` |
| "not in the future" | `is_not_in_future` (`is_not_in_near_future {offset}`) |
| "at least N days old", "A ≥ N days after B" | `is_older_than_n_days` / `is_older_than_col2_for_n_days` |
| "valid JSON", "JSON with keys" | `is_valid_json` / `has_json_keys` |
| "valid IPv4/IPv6", "inside CIDR" | `is_valid_ipv4_address` / `is_ipv4_address_in_cidr` (+ `ipv6` variants) |
| "no PII" | `does_not_contain_pii` |
| "valid latitude/longitude" | `is_latitude` / `is_longitude` |
| "fresh", "updated within N minutes" | `is_data_fresh {max_age_minutes}` |
| anything else row-scoped in SQL | `sql_expression {expression}` — last resort |

Dataset-level (under `quality.checks`; needs a `materialized_view` target or
explicit `allow_streaming_dataset_checks: true`):

| User says | dqx check |
|---|---|
| "unique", "no duplicates", "primary key" | `is_unique {columns}` |
| "must exist in <table>", "referential integrity" | `foreign_key {columns, ref_columns, ref_df_name}` + `quality.references` |
| "row count/sum/avg at least|most N" | `is_aggr_not_less_than` / `is_aggr_not_greater_than` / `is_aggr_equal` / `is_aggr_not_equal` `{aggr_type, group_by}` |
| "matches/reconciles with <dataset>" | `compare_datasets` |
| "data arrives every N minutes" | `is_data_fresh_per_time_window` |
| "schema matches the contract" | `has_valid_schema` |
| "no statistical outliers" | `has_no_outliers` |
| dataset-scoped SQL assertion | `sql_query` — last resort |

Criticality (dqx rule-generator convention): rows that must NOT land in the
table — keys, ids, business invariants → `criticality: error` (they go to
`<table>_quarantine` automatically — never silently dropped); "monitor/flag
but keep" — formats and ranges on optional fields → `warn`; omitted →
`error`. Conditional rules use `filter:` (e.g. `email IS NOT NULL`); the same
check across many columns uses `for_each_column:`. A request no dqx function
covers → custom `@check_function` in `src/<domain>_etl/checks/` (module
listed in `domain.yml` `imports:`), not a pile of `sql_expression`s.

## If new python is needed

Pure function in `src/<domain>_etl/transforms/` with
`@transform("<domain>.<name>")` + a unit test; ensure the module is in
`domain.yml` `imports:`. Custom checks: `src/<domain>_etl/checks/` with
`@check_function`.

**Never hardcode a table, catalog or schema in a transform, and never read
`spark.conf` there.** A transform that needs a SECOND table (the classic case:
joining a dimension into a gold aggregate) declares it in the artifact and
receives the resolved name as a keyword argument:

```yaml
transform:
  - function: sales.sales_by_category
    tables:
      products_table: {name: products, layer: silver}
```

```python
@transform("sales.sales_by_category")
def sales_by_category(df, products_table: str):
    return category_rollup(df, df.sparkSession.read.table(products_table))
```

`layer:` resolves through `domain.yml`'s layer→schema mapping; use
`catalog_conf:`/`schema_conf:` for a table outside this domain (`layer:` and
`schema_conf:` are mutually exclusive). Why it matters: the artifact stays the
single declaration of every table the dataset touches, the same config works in
dev/stage/prod, and `run_dataset(inputs={"<cat>.silver.products": df})` can
substitute the dimension so the join is testable without a live table. A wrong or
missing kwarg fails `make validate-configs`, not the pipeline update.

Caveat: a `tables:` ref is a batch read OUTSIDE the SDP graph — it adds no
dependency edge. When you need a genuine in-graph join, use `source.kind: sql`
over same-pipeline datasets by short name (see `config/sales/templates/`).
Live example: `projects/sales/config/sales/gold/sales_by_category.yml`.

## Verify (always, in this order)

1. `make validate-configs` — pydantic + static dqx validation; fix what it
   names.
2. `make lint test`.
3. Behavior: `datalab.framework.run_dataset(spark, "config/<domain>",
   "<layer>", "<table>", params=..., inputs=...)` in a test or a notebook/REPL
   (or `make validate-connect` against a live cluster) — check valid rows,
   quarantine evidence, casts.
4. `make validate` (bundle), then deploy/run from a dev refresh.

A brand-new domain additionally needs: `config/<catalog>/domain.yml`,
`src/<catalog>_etl/` package (+ hatch wheel packages entry in pyproject.toml),
a copied pipeline resource pointing `datalab.config_dir` at the config dir —
follow `docs/GETTING_STARTED.md` end to end (copy the
`projects/customer_sales/` shape; naming contract: `docs/NAMING.md`).
