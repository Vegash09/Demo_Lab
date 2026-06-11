"""dqx on local Spark 4.1: the smoke test the whole framework rests on.

dqx local execution is officially experimental and upstream-tested on
pyspark 3.5; this suite pins the behaviors we depend on so a dqx or pyspark
upgrade that breaks them fails here, not in a pipeline."""

import pytest
from pyspark.sql import functions as F

from datalab.framework.context import ResolveContext
from datalab.framework.dq import STATIC_RUN_TIME, DQAdapter, summarize_dq_results
from datalab.framework.loader import load_domain_configs

DOMAIN = """
schema_version: 1
domain: demo
layers:
  silver: {schema_conf: datalab.silver_schema}
dq:
  result_columns: {errors: _errs, warnings: _warns}
"""

CUSTOMERS = """
schema_version: 1
name: customers
source: {kind: table, name: customers_raw, schema_conf: datalab.bronze_schema, as_stream: true}
columns:
  - name: customer_id
    type: string
    quality:
      - name: valid_id
        criticality: error
        check: {function: is_not_null}
  - name: email
    type: string
    quality:
      - name: valid_email
        criticality: warn
        filter: email IS NOT NULL
        check:
          function: regex_match
          arguments: {regex: '^[^@]+@[^@]+$'}
quality:
  quarantine: {include_warnings: false}
target:
  kind: streaming_table
  cdc: {keys: [customer_id], sequence_by: customer_id}
"""


@pytest.fixture(scope="module")
def layer(tmp_path_factory):
    root = tmp_path_factory.mktemp("cfg")
    (root / "domain.yml").write_text(DOMAIN)
    (root / "silver").mkdir()
    (root / "silver" / "customers.yml").write_text(CUSTOMERS)
    return load_domain_configs(root, ["silver"])[0]


@pytest.fixture(scope="module")
def sample(spark):
    return spark.createDataFrame(
        [
            ("C001", "asha@example.com"),
            (None, "ghost@example.com"),
            ("C002", "not-an-email"),
        ],
        "customer_id string, email string",
    )


@pytest.fixture(scope="module")
def adapter(spark, layer):
    ctx = ResolveContext.from_dict(spark, {})
    return DQAdapter.for_layer(spark, layer, ctx)


def test_static_extra_params_pinned(adapter):
    # MV incrementalization depends on deterministic result columns: the
    # run_time overwrite must stay static, and the layer's column rename must
    # reach the adapter (the rename's runtime effect is asserted in
    # test_split_semantics via the _errs/_warns columns).
    assert adapter.errors_col == "_errs"
    assert adapter.warnings_col == "_warns"
    assert STATIC_RUN_TIME == "1970-01-01T00:00:00"


def test_split_semantics(spark, adapter, layer, sample):
    ds = layer.datasets[0]
    checked = adapter.apply(spark, sample, ds)
    assert {"_errs", "_warns"} <= set(checked.columns)

    valid = adapter.valid(checked)
    # error row (null id) dropped; warn row kept; result columns stripped
    assert valid.count() == 2
    assert "_errs" not in valid.columns
    assert {r.customer_id for r in valid.collect()} == {"C001", "C002"}

    quarantine = adapter.invalid(checked, include_warnings=False)
    assert quarantine.count() == 1  # exactly the dropped row
    assert quarantine.first().customer_id is None

    with_warns = adapter.invalid(checked, include_warnings=True)
    assert with_warns.count() == 2  # dropped row + flagged warn row


def test_warn_evidence_flows_to_target_rows(spark, adapter, layer, sample):
    ds = layer.datasets[0]
    checked = adapter.apply(spark, sample, ds)
    flagged = checked.where(F.col("_warns").isNotNull()).collect()
    assert len(flagged) == 1
    assert flagged[0].customer_id == "C002"
    assert [w.name for w in flagged[0]._warns] == ["valid_email"]


def test_summarize_dq_results(spark, adapter, layer, sample):
    ds = layer.datasets[0]
    checked = adapter.apply(spark, sample, ds)
    quarantine = adapter.invalid(checked, include_warnings=True)
    counts = {
        (r.check_name, r.criticality): r.violations
        for r in summarize_dq_results(quarantine, "_errs", "_warns").collect()
    }
    assert counts[("valid_id", "error")] == 1
    assert counts[("valid_email", "warn")] == 1
