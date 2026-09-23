"""sales-domain transformations (bronze → silver → gold).

Pure functions only: DataFrame in, DataFrame out. Column selection, renames and
ANSI-safe type casts are declared in the table artifacts (``columns:`` in
``config/sales/<schema>/<table>.yml``) — these functions carry only the logic a
mapping cannot express (email normalization, the gold aggregates). dqx quality
rules also live in the artifacts.

``sales_by_category`` is the one transform that joins a sibling dataset: gold
"sales by category" needs the product ``category``, which lives only in
``silver.products``. That dimension is DECLARED in the artifact
(``transform[].tables``) and arrives as an already-resolved table name, so the
function stays free of catalog/schema knowledge and the join is exercisable with
sample frames via ``run_dataset``. The join + rollup itself lives in the pure
:func:`category_rollup` helper. Note the declared table is still a plain batch
read outside the SDP graph — it creates no pipeline dependency edge.
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


def _order_rollup(df: DataFrame, *keys: str) -> DataFrame:
    """Order count, recognized revenue and average order value per ``keys``.
    Cancelled/returned orders are excluded from revenue but still counted as
    orders."""
    recognized = ~F.col("order_status").isin(*_NON_REVENUE_STATUSES)
    return df.groupBy(*keys).agg(
        F.count("*").alias("num_orders"),
        F.round(
            F.sum(F.when(recognized, F.col("total_amount")).otherwise(F.lit(0.0))), 2
        ).alias("gross_revenue"),
        F.round(F.avg("total_amount"), 2).alias("avg_order_value"),
    )


@transform("sales.daily_sales")
def daily_sales(df: DataFrame) -> DataFrame:
    """Gold aggregate: per-day order count, recognized revenue and average order
    value over ``silver.orders``."""
    return _order_rollup(df, "order_date")


@transform("sales.daily_sales_by_currency")
def daily_sales_by_currency(df: DataFrame) -> DataFrame:
    """Gold aggregate: the ``daily_sales`` measures per day AND currency over
    ``silver.orders``. Amounts stay in their original currency — summing across
    currencies without FX conversion would be meaningless, so ``currency`` is a
    grouping key, never collapsed."""
    return _order_rollup(df, "order_date", "currency")


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
def sales_by_category(df: DataFrame, products_table: str) -> DataFrame:
    """Gold aggregate: revenue and units per product category. ``df`` is
    ``silver.order_items``; ``products_table`` is the RESOLVED name of the
    dimension, supplied by the artifact's ``transform[].tables`` block. The
    function therefore names no catalog or schema of its own — the artifact
    declares every table it touches, and ``run_dataset`` can substitute a sample
    frame for the dimension."""
    products = df.sparkSession.read.table(products_table)
    return category_rollup(df, products)
