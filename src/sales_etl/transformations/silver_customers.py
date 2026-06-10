"""Silver: cleaned, validated, deduplicated customers.

Flow:

1. ``customers_cleaned``    — temporary view applying the pure transform from
   ``datalab.transforms.sales`` to the bronze stream.
2. ``customers_validated``  — temporary view carrying the expectations:
   QUARANTINE_RULES drop violating rows (old DQX criticality "error"),
   WARN_RULES only record metrics (old criticality "warn").
3. ``customers``            — silver streaming table kept current by an
   AUTO CDC flow (replaces the legacy Delta MERGE upsert): upsert by
   ``customer_id`` ordered by ``_ingest_ts``, stored as SCD type 1.
4. ``customers_quarantine`` — rows dropped by QUARANTINE_RULES, preserved for
   triage (replaces the legacy DQX quarantine table).
"""

from pyspark import pipelines as dp

from datalab.config import fqn, pipeline_conf
from datalab.quality import violation_predicate
from datalab.transforms.sales import QUARANTINE_RULES, WARN_RULES, clean_customers

CATALOG = pipeline_conf(spark, "datalab.catalog")  # noqa: F821
BRONZE_SCHEMA = pipeline_conf(spark, "datalab.bronze_schema")  # noqa: F821
SILVER_SCHEMA = pipeline_conf(spark, "datalab.silver_schema")  # noqa: F821

BRONZE_CUSTOMERS = fqn(CATALOG, BRONZE_SCHEMA, "customers_raw")
SILVER_CUSTOMERS = fqn(CATALOG, SILVER_SCHEMA, "customers")


@dp.temporary_view(comment="Bronze customers with standardized types and normalized email.")
def customers_cleaned():
    return clean_customers(spark.readStream.table(BRONZE_CUSTOMERS))  # noqa: F821


@dp.temporary_view(comment="Cleaned customers that passed the quarantine-grade quality rules.")
@dp.expect_all_or_drop(QUARANTINE_RULES)
@dp.expect_all(WARN_RULES)
def customers_validated():
    return spark.readStream.table("customers_cleaned")  # noqa: F821


# Target table first, then the AUTO CDC flow that keeps it current
# (the SDP replacement for hand-written MERGE/upsert logic).
dp.create_streaming_table(
    name=SILVER_CUSTOMERS,
    comment="Current customer profile per customer_id (SCD1), validated and deduplicated.",
    table_properties={"datalab.layer": "silver"},
)

dp.create_auto_cdc_flow(
    target=SILVER_CUSTOMERS,
    source="customers_validated",
    keys=["customer_id"],
    sequence_by="_ingest_ts",
    stored_as_scd_type=1,
)


@dp.table(
    name=fqn(CATALOG, SILVER_SCHEMA, "customers_quarantine"),
    comment="Customer rows that violated quarantine-grade quality rules, kept for triage.",
    table_properties={"datalab.layer": "silver"},
)
def customers_quarantine():
    return spark.readStream.table("customers_cleaned").where(  # noqa: F821
        violation_predicate(QUARANTINE_RULES)
    )
