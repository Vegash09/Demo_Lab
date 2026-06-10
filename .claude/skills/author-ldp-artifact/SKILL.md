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

Rules are databrickslabs/dqx metadata. Column-scoped rules go under the
column (the framework injects `column` and a `<col>_<function>` name);
multi-column/dataset rules go under `quality.checks` with explicit arguments.

| User says | dqx check |
|---|---|
| "required", "not null", "must have" | `{function: is_not_null}` |
| "not empty" | `{function: is_not_null_and_not_empty}` |
| "between X and Y", "at least/most N" | `{function: is_in_range, arguments: {min_limit: X, max_limit: Y}}` |
| "one of [A, B, C]", "allowed values" | `{function: is_in_list, arguments: {allowed: [A, B, C]}}` |
| "valid email/phone/pattern" | `{function: regex_match, arguments: {regex: '...'}}` |
| "valid date/timestamp format" | `{function: is_valid_date}` / `is_valid_timestamp` |
| "unique", "no duplicates" | `{function: is_unique, arguments: {columns: [...]}}` — dataset-level: needs a `materialized_view` target (or explicit `allow_streaming_dataset_checks: true`) |
| "must exist in <other table>" | `{function: foreign_key, arguments: {columns: [...], ref_columns: [...], ref_df_name: <key>}}` + `quality.references` |
| "fresh", "not older than N days" | `{function: is_data_fresh, arguments: {column: ..., max_age_minutes: ...}}` |
| anything else expressible in SQL | `{function: sql_expression, arguments: {expression: '...'}}` |

Criticality: rows that must NOT land in the table → `criticality: error`
(they go to `<table>_quarantine` automatically — never silently dropped);
"monitor/flag but keep" → `criticality: warn`. Conditional rules use
`filter:` (e.g. `email IS NOT NULL`).

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
