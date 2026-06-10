# The datalab framework (flowspec)

The baseline LDP framework reused across customers: every **target table is
one YAML artifact**, authored by a coding agent from a natural-language
request (skill: `author-ldp-artifact`), validated by Pydantic models, and
generated into Lakeflow Declarative Pipelines datasets through reader/writer
adapters. Data quality is
[databrickslabs/dqx](https://databrickslabs.github.io/dqx/) end to end.

```text
config/<domain>/domain.yml                    domain settings (imports, conf keys per layer)
config/<domain>/<layer>/<table>.yml           ONE artifact per target table:
        │                                       columns (source→target + types + DQ rules),
        │                                       transforms, target kind
        │  pydantic DomainConfig/TableFile (validated at import, CI, and editor)
        ▼
datalab.framework.generate(spark, config_dir) the 3-line pipeline entrypoint
        │  readers: cloud_files / table / view          (batch or stream)
        │  columns: projection (rename + ANSI-safe casts)
        │  transforms: registry of pure functions       (src/<domain>_etl/transforms)
        │  dq: DQX apply → valid / quarantine split     (src/<domain>_etl/checks too)
        ▼  writers: streaming table / AUTO CDC / MV / temporary view / sink
generated graph:  <name>__input → <name>__checked → <name>__valid → target
                                            └─────────→ <name>_quarantine (+ metrics MV)
```

**No hardcoded catalogs — ever.** Every location in an artifact is a
pipeline-conf KEY (`datalab.catalog`, `datalab.silver_schema`, …) resolved per
environment through bundle variables, so promoting dev → stage → prod never
edits a config file.

## Add a table — one artifact

Create `config/<domain>/<layer>/<table>.yml` (file name == target table
name). Example `config/sales/silver/orders.yml`:

```yaml
# yaml-language-server: $schema=../../../schemas/table_config.schema.json
schema_version: 1
name: orders
comment: Validated orders, SCD1 per order_id.
source:
  kind: table
  name: orders_raw
  layer: bronze              # resolves via domain.yml — no hardcoded schemas
  as_stream: true
columns:                     # target columns: source→target names + types + rules
  - name: order_id
    source: src_order_id     # rename
    type: string
    quality:
      - criticality: error   # → dropped + quarantined (auto-named order_id_is_not_null)
        check: {function: is_not_null}
  - name: amount
    type: decimal(12,2)      # ANSI-safe cast: malformed → NULL for DQ to flag
    quality:
      - criticality: warn    # → flows through, flagged
        check: {function: is_in_range, arguments: {min_limit: 0}}
  - name: _ingest_ts
    type: timestamp
transform:
  - function: sales.enrich_orders   # only for logic a mapping can't express
target:
  kind: streaming_table
  cdc: {keys: [order_id], sequence_by: _ingest_ts, scd_type: 1}
```

Error rules **auto-create** `orders_quarantine` (rows are never silently
dropped); add a `quality:` block only for table-level rules, quarantine
tuning (`include_warnings`, `enabled: false`), metrics, or references.

If a new transform is needed, register a pure function in the DOMAIN package
and make sure its module is in `domain.yml` `imports:`:

```python
@transform("sales.enrich_orders")
def enrich_orders(df: DataFrame) -> DataFrame: ...
```

Then: `make validate-configs` → `make test` → verify interactively (below) →
`make deploy run`.

## Add a domain — the framework is never edited

The framework (`src/datalab/`) contains zero domain code and hardcodes no
domain module paths; adopting it in a new domain (or lifting it into another
customer project) means creating only domain-owned artifacts:

1. `config/<domain>/domain.yml` — domain name, `imports:`, `catalog_conf`,
   per-layer `layers:` schema conf keys.
2. `config/<domain>/<layer>/<table>.yml` — one artifact per target table.
3. `src/<domain>_etl/` — `transforms/` (pure `@transform` functions),
   `checks/` (custom dqx checks), `transformations/pipeline.py` (copy the
   3-line sales one).
4. Add `src/<domain>_etl` to `[tool.hatch.build.targets.wheel]` packages.
5. Copy `resources/sales_etl.pipeline.yml` (+ job yml), rename, and point
   `datalab.config_dir` at `config/<domain>`.

## Choosing a target kind

| Target kind | LDP object | When |
|---|---|---|
| `streaming_table` | `dp.table` (streaming) | incremental ingest/append |
| `streaming_table` + `cdc:` | `dp.create_streaming_table` + AUTO CDC flow | upserts / SCD1 / SCD2 |
| `materialized_view` | `dp.materialized_view` | batch tables & aggregates (the default for "normal delta tables") |
| `temporary_view` | `dp.temporary_view` | pipeline-scoped ("dynamic") views; quality is annotate-only |
| `delta_sink` | `dp.create_sink` + `append_flow` | streaming append to EXTERNAL delta destinations only |

## Data quality (dqx) semantics

- Rules are dqx metadata — anything from the
  [dqx checks reference](https://databrickslabs.github.io/dqx/docs/reference/quality_checks/)
  can be pasted in, including `filter:`, `for_each_column:`, and custom
  functions from `src/<domain>_etl/checks/` (declared via `domain.yml`
  `imports:`). The NL→check-function mapping table lives in the
  `author-ldp-artifact` skill.
- **Column-level rules** (`columns[].quality`) get `check.arguments.column`
  and a `<column>_<function>` rule name injected automatically. Table-level
  and multi-column rules go under `quality.checks` with explicit arguments.
- **Auto-quarantine**: any error-criticality rule creates
  `<table>_quarantine` even without a `quality.quarantine` block — rows are
  never silently dropped. Opt out explicitly with
  `quality: {quarantine: {enabled: false}}`.
- `criticality: error` rows never reach the target; they land in the
  quarantine table with `_errors` evidence structs.
  `criticality: warn` rows flow into the target (flagged in `_warnings`
  before the result columns are stripped) and enter quarantine only when
  `quarantine.include_warnings: true`.
- Default `include_warnings: false` keeps the repo's contract: quarantine ==
  exactly the dropped rows.
- `quality.metrics.enabled: true` adds a `<name>_dq_metrics` MV (per-rule
  violation counts); it requires `include_warnings: true`.
- Dataset-level rules (`is_unique`, `foreign_key`, `is_aggr_*`) are blocked on
  streaming targets (they'd validate per micro-batch); use a
  `materialized_view` target or opt in with
  `allow_streaming_dataset_checks: true`.
- The DQ engine pins static `run_time`/`run_id` overwrites — required to keep
  materialized views incrementalizable. Don't change this; per-row event time
  belongs in the data (`_ingest_ts`).

## Verify before deploying

- `make validate-configs` — pydantic + static dqx validation of every domain.
- `notebooks/framework/verify_dataset.py` — run ONE dataset through the real
  framework path on sample or live data, no deploy: shows the plan, valid
  rows, quarantine evidence, and warnings. The same `run_dataset` API backs
  `tests/unit/framework/test_devtools.py`, so notebook and pytest are
  literally the same code path.
- `datalab.framework.devtools.capture_graph(spark, "config/sales")` — list
  the full generated dataset/flow graph locally.
- CDC caveat: the SCD merge itself is engine-owned; `run_dataset` verifies
  everything up to the valid/quarantine frames and prints the CDC plan. The
  merge is verified by a dev refresh (`make run`).

## Gotchas

- Quote YAML-1.1 ambiguous scalars in `options:` (`"true"`, `"no"`, `"1"`).
- One malformed YAML fails the whole domain pipeline at import — intended
  (fail fast before data moves); CI and `make validate-configs` catch it first.
- If a source already has `_errors`/`_warnings` columns, rename the result
  columns per layer: `dq: {result_columns: {errors: _dq_errors, warnings: _dq_warnings}}`.
- The editor autocompletes/validates configs via the
  `yaml-language-server` headers → `schemas/table_config.schema.json` and
  `schemas/domain_config.schema.json` (regenerate with `make schema` after
  model changes).
- dqx local execution is experimental upstream; the pinned behaviors we rely
  on are locked by `tests/unit/framework/test_dq.py`. Upgrade
  `databricks-labs-dqx` only after reading its changelog (it is Beta).
