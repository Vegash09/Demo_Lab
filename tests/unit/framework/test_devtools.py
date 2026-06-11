"""run_dataset/plan on a synthetic domain — framework-only, no example code.

(The shipped customer_sales example exercises the same APIs end to end in
examples/customer_sales/tests/test_run_dataset_contract.py.)
"""

import pytest
from pyspark.sql import functions as F

from datalab.framework import plan, run_dataset
from datalab.framework.errors import ConfigError

EVENTS_YML = """
schema_version: 1
name: events
source: {kind: table, name: events_raw, layer: bronze, as_stream: true}
columns:
  - name: event_id
    source: id
    type: string
    quality:
      - criticality: error
        check: {function: is_not_null}
  - name: amount
    type: decimal(10,2)
  - name: email
    type: string
transform:
  - function: testkit.lower_email
target:
  kind: streaming_table
  cdc: {keys: [event_id], sequence_by: event_id}
"""

PARAMS = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
}


@pytest.fixture()
def sample(spark):
    return spark.createDataFrame(
        [
            ("E1", "12.50", "  Asha@Example.COM "),
            (None, "oops", "ghost@example.com"),
        ],
        "id string, amount string, email string",
    )


def test_run_dataset_full_chain(spark, write_domain, sample):
    config_dir = write_domain({"silver/events.yml": EVENTS_YML})
    res = run_dataset(
        spark,
        config_dir,
        "silver",
        "events",
        params=PARAMS,
        inputs={"cat.bronze.events_raw": sample},
    )

    valid = res.valid_df.collect()
    assert [r.event_id for r in valid] == ["E1"]
    assert valid[0].email == "asha@example.com"  # transform ran post-mapping
    assert str(valid[0].amount) == "12.50"  # columns: cast string→decimal
    assert "_errors" not in res.valid_df.columns  # result cols stripped

    quarantined = res.quarantine_df.collect()
    assert len(quarantined) == 1  # the null-id row, with dqx evidence
    assert [e.name for e in quarantined[0]._errors] == ["event_id_is_not_null"]
    assert quarantined[0].amount is None  # try_cast: malformed → NULL

    assert res.cdc_plan and "event_id" in res.cdc_plan  # engine-owned part


def test_run_dataset_unknown_dataset_lists_options(spark, write_domain):
    config_dir = write_domain({"silver/events.yml": EVENTS_YML})
    with pytest.raises(ConfigError, match="events"):
        run_dataset(spark, config_dir, "silver", "nope", params=PARAMS)


def test_plan_needs_no_spark_and_names_quarantine(write_domain):
    config_dir = write_domain({"silver/events.yml": EVENTS_YML})
    out = plan(config_dir)
    assert "events_quarantine" in out
    assert "3 mapped column(s)" in out
    assert "testkit.lower_email" in out
    assert "streaming_table" in out


def test_run_dataset_force_batch_displays_streaming_sources(spark, write_domain, sample):
    # force_batch is what lets a notebook display() a streaming dataset's
    # frames; with an `inputs` substitution no table read happens at all.
    config_dir = write_domain({"silver/events.yml": EVENTS_YML})
    res = run_dataset(
        spark, config_dir, "silver", "events",
        params=PARAMS, inputs={"cat.bronze.events_raw": sample},
    )
    assert not res.valid_df.isStreaming
    assert res.valid_df.count() + res.quarantine_df.count() == sample.count()


def test_run_dataset_warn_rows_flow_through(spark, write_domain):
    warn_yml = EVENTS_YML.replace(
        "      - criticality: error\n        check: {function: is_not_null}",
        "      - criticality: warn\n        check: {function: is_not_null}",
    )
    config_dir = write_domain({"silver/events.yml": warn_yml})
    sample = spark.createDataFrame([(None, "1.00", "x@y.zz")], "id string, amount string, email string")
    res = run_dataset(
        spark, config_dir, "silver", "events",
        params=PARAMS, inputs={"cat.bronze.events_raw": sample},
    )
    assert res.valid_df.count() == 1  # warn rows are kept
    assert res.quarantine_df is None  # warn-only rules create no quarantine
    flagged = res.checked_df.where(F.col("_warnings").isNotNull())
    assert flagged.count() == 1  # but the evidence is annotated
