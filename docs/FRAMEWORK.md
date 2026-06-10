# The datalab framework (flowspec)

Config-driven Lakeflow Declarative Pipelines: a domain's whole medallion flow
is described in per-layer YAML files, validated by Pydantic models, and
generated into LDP datasets through reader/writer adapters. Data quality is
[databrickslabs/dqx](https://databrickslabs.github.io/dqx/) end to end.

```text
config/<domain>/{bronze,silver,gold}.yml      what to build (+ dqx rules)
        │  pydantic LayerConfig (validated at import, CI, and editor)
        ▼
datalab.framework.generate(spark, config_dir) the 3-line pipeline entrypoint
        │  readers: cloud_files / table / view          (batch or stream)
        │  transforms: registry of pure functions       (src/<domain>_etl/transforms)
        │  dq: DQX apply → valid / quarantine split     (src/<domain>_etl/checks too)
        ▼  writers: streaming table / AUTO CDC / MV / temporary view / sink
generated graph:  <name>__input → <name>__checked → <name>__valid → target
                                            └─────────→ <name>_quarantine (+ metrics MV)
```

## Add a table — YAML only

1. Add a dataset entry to the layer file (`config/sales/silver.yml`):

```yaml
- name: orders
  comment: Validated orders, SCD1 per order_id.
  source: {kind: table, name: orders_raw, schema_conf: datalab.bronze_schema, as_stream: true}
  transform:
    - function: sales.clean_orders          # pure fn in src/sales_etl/transforms/
  quality:
    checks:                                  # databrickslabs/dqx metadata, verbatim
      - name: valid_order_id
        criticality: error                   # error → dropped + quarantined
        check: {function: is_not_null, arguments: {column: order_id}}
      - name: plausible_amount
        criticality: warn                    # warn → flows through, flagged
        check: {function: is_in_range, arguments: {column: amount, min_limit: 0}}
    quarantine: {}                           # orders_quarantine, errors-only
  target:
    kind: streaming_table
    cdc: {keys: [order_id], sequence_by: _ingest_ts, scd_type: 1}
```

2. If you need a new transform, register a pure function in the DOMAIN
   package (`src/sales_etl/transforms/`) and make sure its module is in the
   layer's `imports:` list:

```python
@transform("sales.clean_orders")
def clean_orders(df: DataFrame) -> DataFrame: ...
```

```yaml
imports:
  - sales_etl.transforms.sales
```

3. `make validate-configs` → `make test` → verify interactively (below) →
   `make deploy run`.

## Add a domain — the framework is never edited

The framework (`src/datalab/`) contains zero domain code and hardcodes no
domain module paths; adopting it in a new domain (or lifting it into another
project) means creating only domain-owned artifacts:

1. `config/<domain>/{bronze,silver,gold}.yml` — datasets + dqx rules, with
   `imports:` naming the domain modules.
2. `src/<domain>_etl/` — `transforms/` (pure `@transform` functions),
   `checks/` (custom dqx checks), `transformations/pipeline.py` (copy the
   3-line sales one).
3. Add `src/<domain>_etl` to `[tool.hatch.build.targets.wheel]` packages.
4. Copy `resources/sales_etl.pipeline.yml` (+ job yml), rename, and point
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

- `checks:` entries are dqx metadata — anything from the
  [dqx checks reference](https://databrickslabs.github.io/dqx/docs/reference/quality_checks/)
  can be pasted in, including `filter:`, `for_each_column:`, and custom
  functions from `src/<domain>_etl/checks/`, declared via the layer `imports:` list.
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
  `yaml-language-server` header → `schemas/layer_config.schema.json`
  (regenerate with `make schema` after model changes).
- dqx local execution is experimental upstream; the pinned behaviors we rely
  on are locked by `tests/unit/framework/test_dq.py`. Upgrade
  `databricks-labs-dqx` only after reading its changelog (it is Beta).
