"""Sales-domain transformations (bronze → silver → gold).

Pure functions only: DataFrame in, DataFrame out. The pipeline wiring lives in
``config/sales/*.yml``, which references these by registry name; data-quality
rules also live there, in databrickslabs/dqx metadata form.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from datalab.framework.registry import transform

# Business columns of the customer feed. Lineage columns added in bronze
# (_ingest_ts, _source_file) are passed through when present.
CUSTOMER_COLUMNS = ["customer_id", "customer_name", "age", "city", "signup_date", "email"]
LINEAGE_COLUMNS = ["_ingest_ts", "_source_file"]


@transform("sales.clean_customers")
def clean_customers(df: DataFrame) -> DataFrame:
    """Standardize the raw customer feed for the silver layer.

    - keeps only the business + lineage columns
    - casts ``signup_date`` to DATE and ``age`` to INT — tolerant casts:
      malformed values become NULL (and get flagged by quality rules) instead
      of failing the stream under Spark 4 ANSI mode
    - normalizes ``email`` to trimmed lower-case
    """
    lineage = [c for c in LINEAGE_COLUMNS if c in df.columns]
    return (
        df.select(*CUSTOMER_COLUMNS, *lineage)
        .withColumn("signup_date", F.try_to_date("signup_date"))
        .withColumn("age", F.col("age").try_cast("int"))
        .withColumn("email", F.lower(F.trim("email")))
    )


@transform("sales.summarize_customers_by_city")
def summarize_customers_by_city(df: DataFrame) -> DataFrame:
    """Gold aggregate: customer counts and average age per city."""
    return df.groupBy("city").agg(
        F.count("*").alias("customer_count"),
        F.round(F.avg("age"), 1).alias("avg_age"),
    )
