"""Gold: business-level aggregates, recomputed by the engine as materialized views."""

from pyspark import pipelines as dp

from datalab.config import fqn, pipeline_conf
from datalab.transforms.sales import summarize_customers_by_city

CATALOG = pipeline_conf(spark, "datalab.catalog")  # noqa: F821
SILVER_SCHEMA = pipeline_conf(spark, "datalab.silver_schema")  # noqa: F821
GOLD_SCHEMA = pipeline_conf(spark, "datalab.gold_schema")  # noqa: F821

SILVER_CUSTOMERS = fqn(CATALOG, SILVER_SCHEMA, "customers")


@dp.materialized_view(
    name=fqn(CATALOG, GOLD_SCHEMA, "customers_by_city"),
    comment="Customer counts and average age per city.",
    table_properties={"datalab.layer": "gold"},
)
def customers_by_city():
    return summarize_customers_by_city(spark.read.table(SILVER_CUSTOMERS))  # noqa: F821
