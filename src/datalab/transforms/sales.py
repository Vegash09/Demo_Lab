"""Sales-domain transformations (bronze → silver → gold).

Pure functions only: DataFrame in, DataFrame out. The SDP wiring (decorators,
expectations, AUTO CDC) lives in ``src/sales_etl/transformations/``.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# Business columns of the customer feed. Lineage columns added in bronze
# (_ingest_ts, _source_file) are passed through when present.
CUSTOMER_COLUMNS = ["customer_id", "customer_name", "age", "city", "signup_date", "email"]
LINEAGE_COLUMNS = ["_ingest_ts", "_source_file"]

# Quality rules in SDP expectation shape ({name: sql_boolean_expression}).
# QUARANTINE_RULES (old DQX criticality "error"): violating rows are dropped
# from silver and captured in the quarantine table.
# WARN_RULES (old DQX criticality "warn"): violating rows still land in
# silver; counts are logged in the pipeline event log.
QUARANTINE_RULES = {
    "valid_customer_id": "customer_id IS NOT NULL",
}
WARN_RULES = {
    "valid_email": r"email IS NULL OR email RLIKE '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'",
}


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


def summarize_customers_by_city(df: DataFrame) -> DataFrame:
    """Gold aggregate: customer counts and average age per city."""
    return df.groupBy("city").agg(
        F.count("*").alias("customer_count"),
        F.round(F.avg("age"), 1).alias("avg_age"),
    )


def quarantine_breakdown(df: DataFrame, rules: dict[str, str]) -> DataFrame:
    """Violation count per quality rule, as ``(rule, violations)`` rows.

    A NULL rule result counts as a violation, matching expectation semantics
    (``@dp.expect_all*`` passes a row only when the expression is true).
    """
    if not rules:
        return df.sparkSession.createDataFrame([], "rule string, violations long")
    counts = df.agg(
        *[
            F.sum(F.when(F.expr(expr), 0).otherwise(1)).cast("long").alias(name)
            for name, expr in rules.items()
        ]
    )
    return counts.unpivot([], list(rules), "rule", "violations")
