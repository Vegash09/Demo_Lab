"""Unit tests for the sales domain's pure transforms.

The join-based gold aggregate (sales_by_category) is split into a registered
transform that reads the dimension named by its artifact's ``transform[].tables``
ref, and a pure ``category_rollup`` helper; the helper is tested here with two
in-memory DataFrames (no live table needed), and the wired-up transform is
covered end to end in test_sales_run_dataset_contract.py."""

from pyspark.sql import Row

from datalab.framework.registry import TRANSFORMS, import_modules
from sales_etl.transforms.sales import (
    category_rollup,
    daily_sales,
    daily_sales_by_currency,
    normalize_email,
    revenue_per_customer,
    sales_by_category,
)


def test_normalize_email(spark):
    df = spark.createDataFrame(
        [Row(email="  Asha@Example.COM "), Row(email=None)],
        "email string",
    )
    out = [r.email for r in normalize_email(df).collect()]
    assert out == ["asha@example.com", None]


def test_transforms_are_registered_for_yaml():
    # the same mechanism the loader uses for the YAML `imports:` list
    import_modules(["sales_etl.transforms.sales"])
    assert TRANSFORMS["sales.normalize_email"] is normalize_email
    assert TRANSFORMS["sales.daily_sales"] is daily_sales
    assert TRANSFORMS["sales.daily_sales_by_currency"] is daily_sales_by_currency
    assert TRANSFORMS["sales.revenue_per_customer"] is revenue_per_customer
    assert TRANSFORMS["sales.sales_by_category"] is sales_by_category


def test_daily_sales_excludes_cancelled_and_returned(spark):
    orders = spark.createDataFrame(
        [
            Row(order_id=1, order_date="2025-01-01", order_status="completed", total_amount=100.0),
            Row(order_id=2, order_date="2025-01-01", order_status="cancelled", total_amount=50.0),
            Row(order_id=3, order_date="2025-01-01", order_status="returned", total_amount=30.0),
        ]
    )
    row = {r.order_date: r for r in daily_sales(orders).collect()}["2025-01-01"]
    assert row.num_orders == 3  # every order counted
    assert row.gross_revenue == 100.0  # cancelled + returned excluded from revenue
    assert row.avg_order_value == 60.0  # avg over all three: (100+50+30)/3


def test_daily_sales_by_currency_groups_by_day_and_currency(spark):
    orders = spark.createDataFrame(
        [
            Row(order_id=1, order_date="2025-01-01", currency="USD", order_status="completed", total_amount=100.0),
            Row(order_id=2, order_date="2025-01-01", currency="USD", order_status="cancelled", total_amount=50.0),
            Row(order_id=3, order_date="2025-01-01", currency="EUR", order_status="shipped", total_amount=80.0),
            Row(order_id=4, order_date="2025-01-02", currency="USD", order_status="completed", total_amount=20.0),
        ]
    )
    out = {(r.order_date, r.currency): r for r in daily_sales_by_currency(orders).collect()}
    assert set(out) == {("2025-01-01", "USD"), ("2025-01-01", "EUR"), ("2025-01-02", "USD")}

    usd = out[("2025-01-01", "USD")]
    assert usd.num_orders == 2  # cancelled still counted as an order
    assert usd.gross_revenue == 100.0  # ...but excluded from revenue
    assert usd.avg_order_value == 75.0  # (100 + 50) / 2

    assert out[("2025-01-01", "EUR")].gross_revenue == 80.0  # never summed with USD


def test_revenue_per_customer(spark):
    orders = spark.createDataFrame(
        [
            Row(order_id=1, customer_id=10, order_date="2025-01-01", order_status="completed", total_amount=100.0),
            Row(order_id=2, customer_id=10, order_date="2025-01-05", order_status="shipped", total_amount=40.0),
            Row(order_id=3, customer_id=10, order_date="2025-01-03", order_status="cancelled", total_amount=999.0),
        ]
    )
    c = {r.customer_id: r for r in revenue_per_customer(orders).collect()}[10]
    assert c.num_orders == 3
    assert c.total_revenue == 140.0  # cancelled excluded
    assert str(c.first_order_date) == "2025-01-01"
    assert str(c.last_order_date) == "2025-01-05"


def test_category_rollup_joins_products_and_nets_discount(spark):
    order_items = spark.createDataFrame(
        [
            Row(item_id=1, order_id=100, product_id=1, quantity=2, unit_price=10.0, discount_pct=0.0),
            Row(item_id=2, order_id=100, product_id=2, quantity=1, unit_price=50.0, discount_pct=10.0),
            Row(item_id=3, order_id=101, product_id=1, quantity=3, unit_price=10.0, discount_pct=0.0),
        ]
    )
    products = spark.createDataFrame(
        [
            Row(product_id=1, category="Electronics", subcategory="Audio"),
            Row(product_id=2, category="Electronics", subcategory="Wearables"),
        ]
    )
    out = {(r.category, r.subcategory): r for r in category_rollup(order_items, products).collect()}

    audio = out[("Electronics", "Audio")]
    assert audio.units_sold == 5  # 2 + 3
    assert audio.num_orders == 2  # orders 100 and 101
    assert audio.gross_revenue == 50.0  # (2*10) + (3*10), no discount

    wearables = out[("Electronics", "Wearables")]
    assert wearables.units_sold == 1
    assert wearables.gross_revenue == 45.0  # 1 * 50 * (1 - 0.10)
