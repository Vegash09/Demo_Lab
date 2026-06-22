"""End-to-end contract of the customer_sales example via run_dataset.

run_dataset backs both this pytest contract and make validate-connect (same
code path) — this is the test an adopter copies for their own domain.
"""

from pathlib import Path

import pytest
from pyspark.sql import functions as F

from datalab.framework import plan, run_dataset
from datalab.framework.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "customer_sales"

PARAMS = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
    "datalab.sales_landing_path": "/tmp/landing",
}


@pytest.fixture()
def bronze_sample(spark):
    return (
        spark.createDataFrame(
            [
                ("C001", "Asha", "34", "Bengaluru", "2025-01-15", "  Asha@Example.COM "),
                (None, "Ghost", "x", "Chennai", "2025-02-20", "not-an-email"),
            ],
            "customer_id string, customer_name string, age string, city string, "
            "signup_date string, email string",
        )
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.lit("lp/a.json"))
    )


def test_run_dataset_reproduces_silver_contract(spark, bronze_sample):
    res = run_dataset(
        spark,
        CONFIG_DIR,
        "silver",
        "customers",
        params=PARAMS,
        inputs={"cat.bronze.customers_raw": bronze_sample},
    )

    valid = res.valid_df.collect()
    assert [r.customer_id for r in valid] == ["C001"]
    assert valid[0].email == "asha@example.com"  # transform ran post-mapping
    assert valid[0].age == 34  # columns: cast string→int
    assert dict(res.valid_df.dtypes)["signup_date"] == "date"
    assert "_errors" not in res.valid_df.columns  # result cols stripped

    quarantined = res.quarantine_df.collect()
    assert len(quarantined) == 1
    # derived per-column rule name: <column>_<function>
    assert [e.name for e in quarantined[0]._errors] == ["customer_id_is_not_null"]

    assert res.cdc_plan and "customer_id" in res.cdc_plan  # engine-owned part


def test_run_dataset_unknown_dataset_lists_options(spark):
    with pytest.raises(ConfigError, match="customers"):
        run_dataset(spark, CONFIG_DIR, "silver", "nope", params=PARAMS)


def test_plan_needs_no_spark_and_names_quarantine():
    out = plan(CONFIG_DIR)
    assert "customers_quarantine" in out
    assert "8 mapped column(s)" in out
    assert "customer_sales.normalize_email" in out
    assert "materialized_view" in out
