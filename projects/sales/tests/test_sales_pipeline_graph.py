"""Generated-graph contract of the sales example.

capture_graph registers every LDP object the config tree would create — locally,
with no Databricks — so this pins the full dataset/flow shape: 4 silver AUTO CDC
SCD1 tables + quarantines, one SCD2 history table (customers_history), one
snapshot-CDC table (product_catalog, quarantine as MV), 3 hand-written gold MVs
and 2 template-expanded gold MVs (revenue_by_state / revenue_by_country).
capture records registrations without running the query bodies, so
sales_by_category's products read is never executed here (the join is covered by
test_sales_transforms.category_rollup and, end to end, by
test_sales_run_dataset_contract.test_run_dataset_sales_by_category_joins_the_declared_dimension).
"""

from pathlib import Path

import pytest

from datalab.framework.devtools import capture_graph

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "sales"

CONF = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
}


@pytest.fixture()
def configured_spark(spark):
    for key, value in CONF.items():
        spark.conf.set(key, value)
    return spark


def test_sales_graph_shape(configured_spark):
    captured = capture_graph(configured_spark, CONFIG_DIR)
    names = {name for _, name in captured}

    # 4 silver streaming tables with CDC + quarantine
    for table in ("customers", "products", "orders", "order_items"):
        assert {
            f"{table}__input",
            f"{table}__valid",
            f"cat.silver.{table}",
            f"{table}__cdc_flow",
            f"cat.silver.{table}_quarantine",
        } <= names, table

    # 4 gold materialized views
    assert {
        "daily_sales__input",
        "cat.gold.daily_sales",
        "daily_sales_by_currency__input",
        "cat.gold.daily_sales_by_currency",
        "revenue_per_customer__input",
        "cat.gold.revenue_per_customer",
        "sales_by_category__input",
        "cat.gold.sales_by_category",
    } <= names

    # SCD2 history table (AUTO CDC, scd_type 2) over the same bronze source
    assert {
        "customers_history__input",
        "customers_history__valid",
        "cat.silver.customers_history",
        "customers_history__cdc_flow",
        "cat.silver.customers_history_quarantine",
    } <= names

    # snapshot CDC (cdc_from_snapshot, pattern A) — quarantine materializes as an MV
    assert {
        "product_catalog__input",
        "product_catalog__valid",
        "cat.silver.product_catalog",
        "product_catalog__snapshot_cdc_flow",
        "cat.silver.product_catalog_quarantine",
    } <= names

    # 2 template-expanded gold MVs (templates/revenue_rollup.yml, sql source)
    assert {"cat.gold.revenue_by_state", "cat.gold.revenue_by_country"} <= names

    kinds = {name: kind for kind, name in captured if kind != "Flow"}
    assert kinds["cat.silver.orders"] == "StreamingTable"
    assert kinds["orders__cdc_flow"] == "auto_cdc_flow"
    assert kinds["customers_history__cdc_flow"] == "auto_cdc_flow"
    assert kinds["product_catalog__snapshot_cdc_flow"] == "auto_cdc_from_snapshot_flow"
    assert kinds["cat.silver.product_catalog_quarantine"] == "MaterializedView"
    assert kinds["cat.gold.daily_sales"] == "MaterializedView"
    assert kinds["cat.gold.daily_sales_by_currency"] == "MaterializedView"
    assert kinds["cat.gold.sales_by_category"] == "MaterializedView"
    assert kinds["cat.gold.revenue_by_state"] == "MaterializedView"
    assert kinds["orders__valid"] == "TemporaryView"
