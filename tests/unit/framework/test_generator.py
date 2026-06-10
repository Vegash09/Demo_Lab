"""Generated graph shape + the late-binding regression test."""

import pytest

from datalab.framework.devtools import capture_graph

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


def test_sales_graph_matches_handwritten_pipeline(configured_spark):
    captured = capture_graph(configured_spark, "config/sales")
    names = {name for _, name in captured}

    # bronze: input view + streaming table (was bronze_customers.py)
    assert {"customers_raw__input", "cat.bronze.customers_raw"} <= names
    # silver: dq chain + CDC target + quarantine (was silver_customers.py)
    assert {
        "customers__input",
        "customers__checked",
        "customers__valid",
        "cat.silver.customers",
        "customers__cdc_flow",
        "cat.silver.customers_quarantine",
    } <= names
    # gold: input view + MV (was gold_customers.py)
    assert {"customers_by_city__input", "cat.gold.customers_by_city"} <= names

    # outputs only — each output's flow is captured under the same name
    kinds = {name: kind for kind, name in captured if kind != "Flow"}
    assert kinds["cat.silver.customers"] == "StreamingTable"
    assert kinds["customers__cdc_flow"] == "auto_cdc_flow"
    assert kinds["cat.gold.customers_by_city"] == "MaterializedView"
    assert kinds["customers__checked"] == "TemporaryView"


def test_late_binding_regression(configured_spark, tmp_path):
    # Two datasets in one layer: each generated closure must capture ITS spec,
    # not the last loop iteration's (the classic generator bug).
    (tmp_path / "gold.yml").write_text(
        """
schema_version: 1
domain: sales
layer: gold
defaults:
  schema_conf: datalab.gold_schema
datasets:
  - name: agg_one
    source: {kind: table, name: customers, schema_conf: datalab.silver_schema}
    transform: [{function: framework.select, args: {columns: [city]}}]
    target: {kind: materialized_view}
  - name: agg_two
    source: {kind: table, name: customers, schema_conf: datalab.silver_schema}
    transform: [{function: framework.select, args: {columns: [age]}}]
    target: {kind: materialized_view}
"""
    )
    captured = capture_graph(configured_spark, tmp_path)
    names = [name for _, name in captured]
    assert "cat.gold.agg_one" in names and "cat.gold.agg_two" in names
    # distinct input views registered, one per dataset
    assert names.count("agg_one__input") == 2  # output + its flow
    assert names.count("agg_two__input") == 2
