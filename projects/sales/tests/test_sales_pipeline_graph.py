"""Generated-graph contract of the sales example.

capture_graph registers every LDP object the config tree would create — locally,
with no Databricks — so this pins the full dataset/flow shape (4 silver CDC
tables + quarantines, 3 gold MVs). capture records registrations without running
the query bodies, so sales_by_category's products read is never executed here
(its join logic is covered by test_sales_transforms.category_rollup).
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

    # 3 gold materialized views
    assert {
        "daily_sales__input",
        "cat.gold.daily_sales",
        "revenue_per_customer__input",
        "cat.gold.revenue_per_customer",
        "sales_by_category__input",
        "cat.gold.sales_by_category",
    } <= names

    kinds = {name: kind for kind, name in captured if kind != "Flow"}
    assert kinds["cat.silver.orders"] == "StreamingTable"
    assert kinds["orders__cdc_flow"] == "auto_cdc_flow"
    assert kinds["cat.gold.daily_sales"] == "MaterializedView"
    assert kinds["cat.gold.sales_by_category"] == "MaterializedView"
    assert kinds["orders__valid"] == "TemporaryView"
