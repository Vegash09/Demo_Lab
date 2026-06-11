"""customer_sales-domain transformations (bronze → silver → gold).

Pure functions only: DataFrame in, DataFrame out. Column selection, renames
and type casts are declared in the table artifacts (``columns:`` in
``config/customer_sales/<schema>/<table>.yml`` under this example) — these
functions carry only the logic a mapping cannot express. dqx quality rules
also live in the artifacts.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from datalab.framework.registry import transform


@transform("customer_sales.normalize_email")
def normalize_email(df: DataFrame) -> DataFrame:
    """Normalize ``email`` to trimmed lower-case (runs after the column
    mapping, so it sees target column names)."""
    return df.withColumn("email", F.lower(F.trim("email")))


@transform("customer_sales.summarize_customers_by_city")
def summarize_customers_by_city(df: DataFrame) -> DataFrame:
    """Gold aggregate: customer counts and average age per city."""
    return df.groupBy("city").agg(
        F.count("*").alias("customer_count"),
        F.round(F.avg("age"), 1).alias("avg_age"),
    )
