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

    # domain-wide operational metadata (domain.yml): stamps land after mapping +
    # transforms and before dqx, so quarantine evidence carries them too
    assert valid[0]._record_source == "sales.silver.customers"
    assert "_loaded_at" in res.valid_df.columns
    assert quarantined[0]._record_source == "sales.silver.customers"


def test_run_dataset_scd2_history_opts_out_of_metadata(spark, bronze_customers):
    """silver.customers_history: SCD2 over the same bronze source, with the
    dataset-level `operational_metadata: false` opt-out honoured."""
    res = run_dataset(
        spark,
        CONFIG_DIR,
        "silver",
        "customers_history",
        params=PARAMS,
        inputs={"cat.bronze.customers": bronze_customers},
    )

    valid = res.valid_df.collect()
    assert [r.customer_id for r in valid] == [1]
    assert valid[0].email == "asha@example.com"  # shared normalize_email transform
    assert "_record_source" not in res.valid_df.columns  # opt-out honoured
    assert res.cdc_plan and "customer_id" in res.cdc_plan  # engine-owned SCD2


@pytest.fixture()
def bronze_products(spark):
    return spark.createDataFrame(
        [
            (10, "Widget", "Gadgets", "Small", "Acme", 9.99),
            (None, "Ghost widget", "Gadgets", "Small", "Acme", 1.0),
        ],
        "product_id long, product_name string, category string, subcategory string, "
        "brand string, price double",
    )


def test_run_dataset_snapshot_cdc_product_catalog(spark, bronze_products):
    """silver.product_catalog: cdc_from_snapshot pattern A — the BATCH bronze
    read is the snapshot; mapping/quality/metadata apply to the prepared frame."""
    res = run_dataset(
        spark,
        CONFIG_DIR,
        "silver",
        "product_catalog",
        params=PARAMS,
        inputs={"cat.bronze.products": bronze_products},
    )

    valid = res.valid_df.collect()
    assert [r.product_id for r in valid] == [10]
    assert valid[0]._record_source == "sales.silver.product_catalog"  # stamped
    quarantined = res.quarantine_df.collect()
    assert [e.name for e in quarantined[0]._errors] == ["product_id_is_not_null"]


def test_run_dataset_templated_rollup_expands_and_runs(spark):
    """gold.revenue_by_state exists only through templates/revenue_rollup.yml +
    the gold/revenue_rollups.yml instance — run_dataset sees it as an ordinary
    dataset (sql source over same-pipeline silver datasets)."""
    orders = spark.createDataFrame(
        [
            (1, 100, "completed", 50.0),
            (2, 100, "cancelled", 10.0),
            (3, 200, "shipped", 30.0),
        ],
        "order_id long, customer_id long, order_status string, total_amount double",
    )
    customers = spark.createDataFrame(
        [(100, "TX", "US"), (200, "NV", "US")],
        "customer_id long, state string, country string",
    )
    orders.createOrReplaceTempView("orders")
    customers.createOrReplaceTempView("customers")

    res = run_dataset(spark, CONFIG_DIR, "gold", "revenue_by_state", params=PARAMS)

    rows = {r.state: r for r in res.valid_df.collect()}
    assert rows["TX"].num_orders == 2  # cancelled still counts as an order …
    assert rows["TX"].gross_revenue == 50.0  # … but not as revenue
    assert rows["NV"].gross_revenue == 30.0


def test_run_dataset_sales_by_category_joins_the_declared_dimension(spark):
    """gold.sales_by_category: the ONLY dataset whose transform reads a second
    table. That dimension is declared by the artifact's ``transform[].tables``
    (products_table: {name: products, layer: silver}), so the framework resolves
    it to cat.silver.products and ``inputs=`` can substitute a sample frame —
    which is what makes this end-to-end test possible at all."""
    order_items = spark.createDataFrame(
        [
            (1, 100, 1, 2, 10.0, 0.0),
            (2, 100, 2, 1, 50.0, 10.0),
            (3, 101, 1, 3, 10.0, 0.0),
        ],
        "item_id long, order_id long, product_id long, quantity int, "
        "unit_price double, discount_pct double",
    )
    products = spark.createDataFrame(
        [(1, "Electronics", "Audio"), (2, "Electronics", "Wearables")],
        "product_id long, category string, subcategory string",
    )

    res = run_dataset(
        spark,
        CONFIG_DIR,
        "gold",
        "sales_by_category",
        params=PARAMS,
        inputs={
            "cat.silver.order_items": order_items,
            "cat.silver.products": products,  # the declared tables: ref
        },
    )

    rows = {(r.category, r.subcategory): r for r in res.valid_df.collect()}
    audio = rows[("Electronics", "Audio")]
    assert audio.units_sold == 5  # 2 + 3
    assert audio.num_orders == 2  # orders 100 and 101
    assert audio.gross_revenue == 50.0  # (2*10) + (3*10), no discount
    wearables = rows[("Electronics", "Wearables")]
    assert wearables.gross_revenue == 45.0  # 1 * 50 * (1 - 0.10)


def test_run_dataset_unknown_dataset_lists_options(spark):
    with pytest.raises(ConfigError, match="customers"):
        run_dataset(spark, CONFIG_DIR, "silver", "nope", params=PARAMS)


def test_plan_needs_no_spark_and_names_quarantine():
    out = plan(CONFIG_DIR)
    assert "customers_quarantine" in out
    assert "sales.normalize_email" in out
    assert "materialized_view" in out  # the gold aggregates
    assert "revenue_by_state" in out  # template-expanded datasets are ordinary datasets
    assert "revenue_by_country" in out
