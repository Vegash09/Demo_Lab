from pyspark.sql import Row

from customer_sales_etl.transforms.customers import normalize_email, summarize_customers_by_city
from datalab.framework.registry import TRANSFORMS, import_modules


def test_normalize_email(spark):
    df = spark.createDataFrame(
        [Row(email="  Asha@Example.COM "), Row(email=None)],
        "email string",
    )
    out = [r.email for r in normalize_email(df).collect()]
    assert out == ["asha@example.com", None]


def test_transforms_are_registered_for_yaml():
    # the same mechanism the loader uses for the YAML `imports:` list
    import_modules(["customer_sales_etl.transforms.customers"])
    assert TRANSFORMS["customer_sales.normalize_email"] is normalize_email
    assert TRANSFORMS["customer_sales.summarize_customers_by_city"] is summarize_customers_by_city


def test_summarize_customers_by_city(spark):
    customers = spark.createDataFrame(
        [
            Row(customer_id="C1", city="Bengaluru", age=30),
            Row(customer_id="C2", city="Bengaluru", age=41),
            Row(customer_id="C3", city="Chennai", age=25),
        ]
    )
    out = {r.city: r for r in summarize_customers_by_city(customers).collect()}

    assert out["Bengaluru"].customer_count == 2
    assert out["Bengaluru"].avg_age == 35.5
    assert out["Chennai"].customer_count == 1
