"""Generated-graph contract of the customer_sales example.

capture_graph registers every LDP object the config tree would create —
locally, with no Databricks — so this pins the example's full dataset/flow
shape (the same assertion an adopter writes for their own domain).
"""

from pathlib import Path

import pytest

from datalab.framework.devtools import capture_graph

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "customer_sales"

CONF = {
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
    "datalab.sales_landing_path": "/tmp/landing",
}


@pytest.fixture()
def configured_spark(spark):
    for key, value in CONF.items():
        spark.conf.set(key, value)
    return spark


def test_customer_sales_graph_shape(configured_spark):
    captured = capture_graph(configured_spark, CONFIG_DIR)
    names = {name for _, name in captured}

    # bronze: input view + streaming table
    assert {"customers_raw__input", "cat.bronze.customers_raw"} <= names
    # silver: dq chain + CDC target + quarantine
    assert {
        "customers__input",
        "customers__valid",
        "cat.silver.customers",
        "customers__cdc_flow",
        "cat.silver.customers_quarantine",
    } <= names
    # gold: input view + MV
    assert {"customers_by_city__input", "cat.gold.customers_by_city"} <= names

    # outputs only — each output's flow is captured under the same name
    kinds = {name: kind for kind, name in captured if kind != "Flow"}
    assert kinds["cat.silver.customers"] == "StreamingTable"
    assert kinds["customers__cdc_flow"] == "auto_cdc_flow"
    assert kinds["cat.gold.customers_by_city"] == "MaterializedView"
    assert kinds["customers__valid"] == "TemporaryView"
