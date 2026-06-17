"""sales-domain transformations (bronze → silver → gold).

Pure functions only: DataFrame in, DataFrame out. Column selection, renames and
ANSI-safe type casts are declared in the table artifacts (``columns:`` in
``config/sales/<schema>/<table>.yml``) — these functions carry only the logic a
mapping cannot express (email normalization, the gold aggregates). dqx quality
rules also live in the artifacts.

``sales_by_category`` is the one transform that joins a sibling dataset: gold
"sales by category" needs the product ``category``, which lives only in
``silver.products``. It reads that table through the active Spark session
(resolving catalog/schema from pipeline conf) and delegates the join + rollup to
the pure, unit-testable :func:`category_rollup` helper. Because it reads a
concrete UC table, this MV's full materialization is verified on Databricks
(dev refresh / ``make validate-connect``) rather than the local OSS run; the
join logic itself is covered by a direct unit test on ``category_rollup``.
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from datalab.framework.registry import transform

# Order statuses that do NOT count toward recognized revenue.
_NON_REVENUE_STATUSES = ("cancelled", "returned")


@transform("sales.normalize_email")
def normalize_email(df: DataFrame) -> DataFrame:
    """Normalize ``email`` to trimmed lower-case (runs after the column mapping,
    so it sees target column names)."""
    return df.withColumn("email", F.lower(F.trim("email")))


@transform("sales.daily_sales")
def daily_sales(df: DataFrame) -> DataFrame:
    """Gold aggregate: per-day order count, recognized revenue and average order
    value over ``silver.orders``. Cancelled/returned orders are excluded from
    revenue but still counted as orders."""
    recognized = ~F.col("order_status").isin(*_NON_REVENUE_STATUSES)
    return df.groupBy("order_date").agg(
        F.count("*").alias("num_orders"),
        F.round(
            F.sum(F.when(recognized, F.col("total_amount")).otherwise(F.lit(0.0))), 2
        ).alias("gross_revenue"),
        F.round(F.avg("total_amount"), 2).alias("avg_order_value"),
    )


@transform("sales.revenue_per_customer")
def revenue_per_customer(df: DataFrame) -> DataFrame:
    """Gold aggregate: lifetime order count, recognized revenue and order-date
    span per customer over ``silver.orders``."""
    recognized = ~F.col("order_status").isin(*_NON_REVENUE_STATUSES)
    return df.groupBy("customer_id").agg(
        F.count("*").alias("num_orders"),
        F.round(
            F.sum(F.when(recognized, F.col("total_amount")).otherwise(F.lit(0.0))), 2
        ).alias("total_revenue"),
        F.min("order_date").alias("first_order_date"),
        F.max("order_date").alias("last_order_date"),
    )


def category_rollup(order_items: DataFrame, products: DataFrame) -> DataFrame:
    """Pure join + rollup: revenue and units per product category/subcategory.

    Line revenue = quantity * unit_price * (1 - discount_pct/100). Kept separate
    from :func:`sales_by_category` so the join logic is unit-testable with two
    in-memory DataFrames (no live table needed)."""
    line_revenue = (
        F.col("quantity")
        * F.col("unit_price")
        * (F.lit(1.0) - F.coalesce(F.col("discount_pct"), F.lit(0.0)) / F.lit(100.0))
    )
    joined = order_items.join(
        products.select("product_id", "category", "subcategory"),
        on="product_id",
        how="left",
    ).withColumn("line_revenue", line_revenue)
    return joined.groupBy("category", "subcategory").agg(
        F.countDistinct("order_id").alias("num_orders"),
        F.sum("quantity").alias("units_sold"),
        F.round(F.sum("line_revenue"), 2).alias("gross_revenue"),
    )


@transform("sales.sales_by_category")
def sales_by_category(df: DataFrame) -> DataFrame:
    """Gold aggregate: revenue and units per product category. ``df`` is
    ``silver.order_items``; the product ``category`` is joined in from
    ``silver.products`` (resolved from pipeline conf — same catalog, silver
    schema)."""
    spark = df.sparkSession
    catalog = spark.conf.get("datalab.catalog")
    silver_schema = spark.conf.get("datalab.silver_schema")
    products = spark.read.table(f"{catalog}.{silver_schema}.products")
    return category_rollup(df, products)
