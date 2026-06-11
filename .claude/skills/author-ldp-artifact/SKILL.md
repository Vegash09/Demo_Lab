---
name: author-ldp-artifact
description: Create or modify a pipeline table from a natural-language request by authoring its YAML artifact (config/<domain>/<layer>/<table>.yml) — column mappings with data types, dqx data-quality rules, CDC/upsert targets. Use when the user asks to create/change a table, job, or pipeline, add columns, or add data-quality rules in plain language.
---

# Author an LDP artifact from a natural-language request

This repo is a config-driven framework: a target table is ONE YAML artifact.
You never write `dp.*` wiring. Full reference: `docs/FRAMEWORK.md`.

## Where the artifact goes

`config/<domain>/<layer>/<table>.yml` — the layer folder is the medallion
layer of the TARGET table; the **file name must equal the target table name**.
The domain's `domain.yml` maps layers → schema conf keys and lists the python
`imports:`.

**Never hardcode a catalog or schema name.** Locations are pipeline-conf KEYS
(`datalab.catalog`, `datalab.silver_schema`, …) resolved per environment by
bundle variables — promotion to stage/prod must never require editing an
artifact. If a request names a catalog literally, map it to the conf key.

## Artifact recipe

```yaml
# yaml-language-server: $schema=../../../schemas/table_config.schema.json
schema_version: 1
name: <table>                  # == file name
comment: <one line, business language>
source:                        # where the data comes from
  kind: table                  #   table | cloud_files | view
  name: <upstream table>
  layer: <upstream layer>      #   resolves via domain.yml (preferred)
  as_stream: true              #   stream for incremental, omit for batch
columns:                       # target columns: source→target + type + rules
  - name: <target col>         #   target column name
    source: <source col>       #   omit when identical
    type: <spark type>         #   casts are ANSI-safe (malformed → NULL)
    quality: [...]             #   this column's dqx rules (see below)
transform:                     # only logic a mapping can't express
  - function: <domain>.<fn>    #   @transform-registered pure function
quality:                       # table-level rules + quarantine settings
  checks: [...]                #   multi-column / dataset-level dqx rules
  quarantine: {}               #   error rules AUTO-quarantine even without this
target:
  kind: streaming_table        #   streaming_table | materialized_view |
                               #   temporary_view | delta_sink
  cdc:                         #   upsert/SCD — only with a streaming source
    keys: [<business key>]
    sequence_by: <ordering col>
    scd_type: 1                #   2 for history tracking
```

Choosing `target.kind`: incremental/append → `streaming_table`; upsert/SCD →
`streaming_table` + `cdc`; batch table or aggregate ("normal delta table") →
`materialized_view`; pipeline-scoped/dynamic view → `temporary_view`.

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

## Verify (always, in this order)

1. `make validate-configs` — pydantic + static dqx validation; fix what it
   names.
2. `make lint test`.
3. Behavior: `datalab.framework.run_dataset(spark, "config/<domain>",
   "<layer>", "<table>", params=..., inputs=...)` in a test or the
   `notebooks/framework/verify_dataset.py` notebook — check valid rows,
   quarantine evidence, casts.
4. `make validate` (bundle), then deploy/run from a dev refresh.

A brand-new domain additionally needs: `config/<domain>/domain.yml`,
`src/<domain>_etl/` package (+ hatch wheel packages entry in pyproject.toml),
a copied pipeline resource pointing `datalab.config_dir` at the config dir —
see "Add a domain" in `docs/FRAMEWORK.md`.
