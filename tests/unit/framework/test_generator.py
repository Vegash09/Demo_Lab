"""Generator behavior on synthetic configs (the customer_sales example's
graph-shape contract lives in examples/customer_sales/tests/test_pipeline_graph.py)."""

import pytest

from datalab.framework.devtools import capture_graph

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


def test_late_binding_regression(configured_spark, tmp_path):
    # Two tables in one layer: each generated closure must capture ITS spec,
    # not the last loop iteration's (the classic generator bug).
    (tmp_path / "domain.yml").write_text(
        """
schema_version: 1
domain: demo
layers:
  gold: {schema_conf: datalab.gold_schema}
"""
    )
    (tmp_path / "gold").mkdir()
    (tmp_path / "gold" / "agg_one.yml").write_text(
        """
name: agg_one
source: {kind: table, name: customers, schema_conf: datalab.silver_schema}
transform: [{function: framework.select, args: {columns: [city]}}]
target: {kind: materialized_view}
"""
    )
    (tmp_path / "gold" / "agg_two.yml").write_text(
        """
name: agg_two
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
