"""End-to-end contract of the sales example via run_dataset (silver.customers).

run_dataset backs both this pytest contract and make validate-connect (same code path).
Covers the column mapping (ANSI-safe casts), the post-mapping transform
(normalize_email), the dqx error gate (customer_id not null) and the
valid/quarantine split — the same shape an adopter copies for their domain.
"""

from pathlib import Path

import pytest
from pyspark.sql import functions as F

from datalab.framework import plan, run_dataset
from datalab.framework.errors import ConfigError

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "sales"

PARAMS = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
}


@pytest.fixture()
def bronze_customers(spark):
    return (
        spark.createDataFrame(
            [
                (1, "Asha", "Rao", "  Asha@Example.COM ", "555-1", "Austin", "TX", "US",
                 "2025-01-15T00:00:00.000Z", "2025-02-01T00:00:00.000Z"),
                (None, "Ghost", "X", "not-an-email", "555-2", "Reno", "NV", "US",
                 "2025-01-16T00:00:00.000Z", "2025-02-02T00:00:00.000Z"),
            ],
            "customer_id long, first_name string, last_name string, email string, phone string, "
            "city string, state string, country string, created_at string, updated_at string",
        )
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.lit("lp/a.json"))
    )


def test_run_dataset_reproduces_silver_customers_contract(spark, bronze_customers):
    res = run_dataset(
        spark,
        CONFIG_DIR,
        "silver",
        "customers",
        params=PARAMS,
        inputs={"cat.bronze.customers": bronze_customers},
    )

    valid = res.valid_df.collect()
    assert [r.customer_id for r in valid] == [1]
    assert valid[0].email == "asha@example.com"  # transform ran post-mapping
    assert dict(res.valid_df.dtypes)["created_at"] == "timestamp"  # columns: cast string→timestamp
    assert "_errors" not in res.valid_df.columns  # result cols stripped

    quarantined = res.quarantine_df.collect()
    assert len(quarantined) == 1  # the null-id row
    # derived per-column rule name: <column>_<function>
    assert [e.name for e in quarantined[0]._errors] == ["customer_id_is_not_null"]

    assert res.cdc_plan and "customer_id" in res.cdc_plan  # engine-owned SCD1


def test_run_dataset_unknown_dataset_lists_options(spark):
    with pytest.raises(ConfigError, match="customers"):
        run_dataset(spark, CONFIG_DIR, "silver", "nope", params=PARAMS)


def test_plan_needs_no_spark_and_names_quarantine():
    out = plan(CONFIG_DIR)
    assert "customers_quarantine" in out
    assert "sales.normalize_email" in out
    assert "materialized_view" in out  # the gold aggregates
