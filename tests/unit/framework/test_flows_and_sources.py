"""New-surface coverage: fan-in sources, backfill once-flows, snapshot CDC,
kafka source/sink, reader options — models, loader, generator and devtools."""

import pytest
from pydantic import ValidationError

from datalab.framework.devtools import capture_graph, plan, run_dataset
from datalab.framework.errors import ConfigError
from datalab.framework.loader import load_domain_configs
from datalab.framework.models import DatasetSpec
from datalab.framework.registry import TRANSFORMS, snapshot_source

CONF = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
    "datalab.eu_landing": "/tmp/eu",
    "datalab.us_landing": "/tmp/us",
    "datalab.kafka_brokers": "broker:9092",
    "datalab.history_dump": "/tmp/history",
}


@pytest.fixture()
def configured_spark(spark):
    for key, value in CONF.items():
        spark.conf.set(key, value)
    return spark


def _dataset(**overrides):
    base = {
        "name": "orders",
        "source": {"kind": "table", "name": "orders_raw", "as_stream": True},
        "target": {"kind": "streaming_table"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Models: fan-in sources
# ---------------------------------------------------------------------------
def test_source_xor_sources():
    with pytest.raises(ValidationError, match="exactly one of source"):
        DatasetSpec.model_validate({"name": "orders", "target": {"kind": "streaming_table"}})
    with pytest.raises(ValidationError, match="exactly one of source"):
        DatasetSpec.model_validate(
            _dataset(sources=[{"name": "eu", "source": {"kind": "cloud_files", "path_conf": "datalab.eu_landing"}}])
        )


def test_fan_in_sources_must_stream():
    with pytest.raises(ValidationError, match="must be.*streaming"):
        DatasetSpec.model_validate(
            {
                "name": "orders",
                "sources": [
                    {"name": "eu", "source": {"kind": "table", "name": "eu_orders"}},
                ],
                "target": {"kind": "streaming_table"},
            }
        )


def test_fan_in_rejected_for_materialized_view():
    with pytest.raises(ValidationError, match="fan-in"):
        DatasetSpec.model_validate(
            {
                "name": "orders",
                "sources": [
                    {
                        "name": "eu",
                        "source": {"kind": "cloud_files", "path_conf": "datalab.eu_landing"},
                    }
                ],
                "target": {"kind": "materialized_view"},
            }
        )


def test_flow_names_must_be_unique_across_sources_and_backfill():
    with pytest.raises(ValidationError, match="duplicate flow name"):
        DatasetSpec.model_validate(
            {
                "name": "orders",
                "sources": [
                    {"name": "eu", "source": {"kind": "cloud_files", "path_conf": "datalab.eu_landing"}},
                ],
                "backfill": [
                    {"name": "eu", "source": {"kind": "files", "path_conf": "datalab.history_dump"}},
                ],
                "target": {"kind": "streaming_table"},
            }
        )


# ---------------------------------------------------------------------------
# Models: backfill rules
# ---------------------------------------------------------------------------
def test_backfill_must_be_batch_for_plain_streaming_table():
    with pytest.raises(ValidationError, match="BATCH source"):
        DatasetSpec.model_validate(
            _dataset(
                backfill=[
                    {"name": "hist", "source": {"kind": "table", "name": "old", "as_stream": True}}
                ]
            )
        )


def test_backfill_must_stream_for_cdc_target():
    with pytest.raises(ValidationError, match="must be STREAMING"):
        DatasetSpec.model_validate(
            _dataset(
                backfill=[{"name": "hist", "source": {"kind": "files", "path_conf": "datalab.history_dump"}}],
                target={
                    "kind": "streaming_table",
                    "cdc": {"keys": ["order_id"], "sequence_by": "ts"},
                },
            )
        )


def test_backfill_rejected_on_sinks():
    with pytest.raises(ValidationError, match="streaming_table targets"):
        DatasetSpec.model_validate(
            _dataset(
                backfill=[{"name": "hist", "source": {"kind": "files", "path_conf": "datalab.history_dump"}}],
                target={"kind": "delta_sink", "path_conf": "datalab.history_dump"},
            )
        )


# ---------------------------------------------------------------------------
# Models: CDC completions + snapshot CDC
# ---------------------------------------------------------------------------
def test_cdc_column_list_xor_except():
    with pytest.raises(ValidationError, match="column_list or except_columns"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "cdc": {
                        "keys": ["id"],
                        "sequence_by": "ts",
                        "column_list": ["id", "a"],
                        "except_columns": ["b"],
                    },
                }
            )
        )


def test_cdc_truncates_scd1_only():
    with pytest.raises(ValidationError, match="SCD type 1 only"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "cdc": {
                        "keys": ["id"],
                        "sequence_by": "ts",
                        "scd_type": 2,
                        "apply_as_truncates": "op = 'TRUNCATE'",
                    },
                }
            )
        )


def test_cdc_multi_column_sequence_and_keys_in_column_list():
    ds = DatasetSpec.model_validate(
        _dataset(
            target={
                "kind": "streaming_table",
                "cdc": {"keys": ["id"], "sequence_by": ["ts", "seq_no"], "column_list": ["id", "ts", "seq_no", "v"]},
            }
        )
    )
    assert ds.target.cdc.sequence_columns == ["ts", "seq_no"]
    with pytest.raises(ValidationError, match="must be included in cdc.column_list"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "cdc": {"keys": ["id"], "sequence_by": "ts", "column_list": ["ts", "v"]},
                }
            )
        )


def test_scd2_explicit_schema_needs_period_columns():
    with pytest.raises(ValidationError, match="__START_AT"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "schema": "id STRING, v STRING",
                    "cdc": {"keys": ["id"], "sequence_by": "ts", "scd_type": 2},
                }
            )
        )


def test_snapshot_cdc_requires_batch_source_and_excludes_cdc():
    with pytest.raises(ValidationError, match="cannot share a target"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "cdc": {"keys": ["id"], "sequence_by": "ts"},
                    "cdc_from_snapshot": {"keys": ["id"]},
                }
            )
        )
    with pytest.raises(ValidationError, match="BATCH snapshots"):
        DatasetSpec.model_validate(
            _dataset(
                target={"kind": "streaming_table", "cdc_from_snapshot": {"keys": ["id"]}}
            )
        )
    # batch source is the valid shape
    ds = DatasetSpec.model_validate(
        _dataset(
            source={"kind": "table", "name": "orders_snap"},
            target={"kind": "streaming_table", "cdc_from_snapshot": {"keys": ["id"]}},
        )
    )
    assert not ds.is_streaming


def test_snapshot_function_source_rejects_quality():
    with pytest.raises(ValidationError, match="quality rules cannot gate"):
        DatasetSpec.model_validate(
            _dataset(
                source={"kind": "snapshot_function", "function": "demo.snapshots"},
                columns=[
                    {
                        "name": "id",
                        "quality": [{"criticality": "error", "check": {"function": "is_not_null"}}],
                    }
                ],
                target={"kind": "streaming_table", "cdc_from_snapshot": {"keys": ["id"]}},
            )
        )


def test_snapshot_function_only_with_snapshot_target():
    with pytest.raises(ValidationError, match="snapshot_function source is only valid"):
        DatasetSpec.model_validate(
            _dataset(source={"kind": "snapshot_function", "function": "demo.snapshots"})
        )


# ---------------------------------------------------------------------------
# Models: kafka source/sink
# ---------------------------------------------------------------------------
def test_kafka_source_topic_xor_pattern():
    with pytest.raises(ValidationError, match="exactly one of topic"):
        DatasetSpec.model_validate(
            _dataset(source={"kind": "kafka", "bootstrap_servers_conf": "datalab.kafka_brokers"})
        )


def test_kafka_sink_needs_streaming_source():
    with pytest.raises(ValidationError, match="appends from a stream"):
        DatasetSpec.model_validate(
            _dataset(
                source={"kind": "table", "name": "orders"},
                target={"kind": "kafka_sink", "bootstrap_servers_conf": "datalab.kafka_brokers"},
            )
        )


def test_liquid_clustering_excludes_partitioning():
    with pytest.raises(ValidationError, match="liquid clustering"):
        DatasetSpec.model_validate(
            _dataset(
                target={
                    "kind": "streaming_table",
                    "partition_cols": ["day"],
                    "cluster_by_auto": True,
                }
            )
        )


# ---------------------------------------------------------------------------
# Loader: nested layer refs + snapshot function resolution
# ---------------------------------------------------------------------------
FAN_IN_YML = """
schema_version: 1
name: orders
sources:
  - name: eu
    source: {kind: cloud_files, path_conf: datalab.eu_landing}
  - name: legacy
    source: {kind: table, name: legacy_orders, layer: bronze, as_stream: true}
backfill:
  - name: hist
    source: {kind: files, path_conf: datalab.history_dump, format: json}
target:
  kind: streaming_table
"""


def test_loader_resolves_layer_in_fan_in_and_backfill(write_domain):
    cfgs = load_domain_configs(write_domain({"silver/orders.yml": FAN_IN_YML}), ["silver"])
    ds = cfgs[0].datasets[0]
    assert ds.sources[1].source.schema_conf == "datalab.bronze_schema"
    assert [b.name for b in ds.backfill] == ["hist"]


def test_loader_rejects_unknown_snapshot_function(write_domain):
    yml = """
schema_version: 1
name: customers_dim
source: {kind: snapshot_function, function: demo.no_such_walker}
target:
  kind: streaming_table
  cdc_from_snapshot: {keys: [customer_id]}
"""
    with pytest.raises(ConfigError, match="unknown snapshot source"):
        load_domain_configs(write_domain({"silver/customers_dim.yml": yml}), ["silver"])


# ---------------------------------------------------------------------------
# Generator: captured graph shapes for the new write paths
# ---------------------------------------------------------------------------
def test_fan_in_graph_has_target_plus_flow_per_source(configured_spark, write_domain):
    yml = """
schema_version: 1
name: orders
sources:
  - name: eu
    source: {kind: cloud_files, path_conf: datalab.eu_landing}
  - name: us
    source: {kind: cloud_files, path_conf: datalab.us_landing}
columns:
  - name: order_id
    quality:
      - criticality: error
        check: {function: is_not_null}
target:
  kind: streaming_table
"""
    captured = capture_graph(configured_spark, write_domain({"silver/orders.yml": yml}))
    names = [name for _, name in captured]
    # per-flow view chains
    assert "orders__eu__input" in names and "orders__us__input" in names
    assert "orders__eu__checked" in names and "orders__us__valid" in names
    # explicit target + one named append flow per source
    assert "cat.silver.orders" in names
    assert "orders__eu__flow" in names and "orders__us__flow" in names
    # shared quarantine fed by one flow per source
    assert "cat.silver.orders_quarantine" in names
    assert "orders_quarantine__eu__flow" in names
    assert "orders_quarantine__us__flow" in names


def test_backfill_graph_adds_once_flow(configured_spark, write_domain):
    yml = """
schema_version: 1
name: orders
source: {kind: cloud_files, path_conf: datalab.eu_landing}
backfill:
  - name: hist_2024
    source: {kind: files, path_conf: datalab.history_dump, format: json}
target:
  kind: streaming_table
"""
    captured = capture_graph(configured_spark, write_domain({"silver/orders.yml": yml}))
    names = [name for _, name in captured]
    assert "orders__input" in names  # primary keeps legacy view names
    assert "orders__hist_2024__input" in names
    assert "cat.silver.orders" in names
    assert "orders__flow" in names  # explicit target form renames the primary flow
    assert "orders__hist_2024__backfill" in names


def test_single_source_keeps_legacy_graph(configured_spark, write_domain):
    yml = """
schema_version: 1
name: orders
source: {kind: cloud_files, path_conf: datalab.eu_landing}
target: {kind: streaming_table}
"""
    captured = capture_graph(configured_spark, write_domain({"silver/orders.yml": yml}))
    names = [name for _, name in captured]
    # one-step @dp.table: the only flow is the default one named after the table
    assert "cat.silver.orders" in names
    assert "orders__flow" not in names


def test_snapshot_cdc_graph(configured_spark, write_domain):
    yml = """
schema_version: 1
name: customers_dim
source: {kind: table, name: customers_snapshot, layer: bronze}
target:
  kind: streaming_table
  cdc_from_snapshot: {keys: [customer_id], scd_type: 2}
"""
    captured = capture_graph(configured_spark, write_domain({"silver/customers_dim.yml": yml}))
    kinds = dict((name, kind) for kind, name in captured)
    assert kinds.get("cat.silver.customers_dim") == "StreamingTable"
    assert kinds.get("customers_dim__snapshot_cdc_flow") == "auto_cdc_from_snapshot_flow"


def test_kafka_sink_graph(configured_spark, write_domain):
    yml = """
schema_version: 1
name: order_events
source: {kind: kafka, bootstrap_servers_conf: datalab.kafka_brokers, topic: orders_in}
transform:
  - function: framework.to_json_value
target:
  kind: kafka_sink
  bootstrap_servers_conf: datalab.kafka_brokers
  topic: orders_out
"""
    captured = capture_graph(configured_spark, write_domain({"silver/order_events.yml": yml}))
    names = [name for _, name in captured]
    assert "order_events__sink" in names
    assert "order_events__sink_flow" in names


# ---------------------------------------------------------------------------
# Devtools: flow picking + snapshot preview + plan rendering
# ---------------------------------------------------------------------------
@snapshot_source("demo.walker")
def _walker(version):
    return None  # never yields — registration is what the tests need


def test_run_dataset_picks_backfill_flow(spark, write_domain):
    config_dir = write_domain({"silver/orders.yml": FAN_IN_YML})
    sample = spark.createDataFrame([("O1",)], "order_id string")
    res = run_dataset(
        spark, config_dir, "silver", "orders",
        params={**CONF}, inputs={"/tmp/history": sample}, flow="hist",
    )
    assert res.valid_df.count() == 1
    with pytest.raises(ConfigError, match="no flow 'nope'"):
        run_dataset(spark, config_dir, "silver", "orders", params={**CONF}, flow="nope")


def test_run_dataset_snapshot_function_preview_requires_first_frame(spark, write_domain):
    yml = """
schema_version: 1
name: customers_dim
source: {kind: snapshot_function, function: demo.walker}
target:
  kind: streaming_table
  cdc_from_snapshot: {keys: [customer_id]}
"""
    config_dir = write_domain({"silver/customers_dim.yml": yml})
    with pytest.raises(ConfigError, match="no first snapshot"):
        run_dataset(spark, config_dir, "silver", "customers_dim", params={**CONF})


def test_plan_renders_fan_in_and_backfill(write_domain):
    out = plan(write_domain({"silver/orders.yml": FAN_IN_YML}))
    assert "fan-in[eu, legacy]" in out
    assert "+1 backfill once-flow(s)" in out


def test_to_json_value_builtin(spark):
    df = spark.createDataFrame([("O1", 5)], "order_id string, qty int")
    out = TRANSFORMS["framework.to_json_value"](df, key="order_id")
    row = out.first()
    assert out.columns == ["key", "value"]
    assert row.key == "O1" and '"qty":5' in row.value
