from datetime import date, datetime

from pyspark.sql import Row

from datalab.framework.registry import TRANSFORMS, discover
from datalab.transforms.sales import clean_customers, summarize_customers_by_city

# Explicit schema: _rescued_data is None in every row, so Spark cannot infer
# its type from the data alone.
_RAW_SCHEMA = (
    "customer_id string, customer_name string, age string, city string, "
    "signup_date string, email string, _ingest_ts timestamp, "
    "_source_file string, _rescued_data string"
)


def _raw_customers(spark):
    return spark.createDataFrame(
        [
            Row(
                customer_id="C001",
                customer_name="Asha",
                age="34",
                city="Bengaluru",
                signup_date="2025-01-15",
                email="  Asha@Example.COM ",
                _ingest_ts=datetime(2026, 6, 1, 10, 0, 0),
                _source_file="lp/a.json",
                _rescued_data=None,
            ),
            Row(
                customer_id=None,
                customer_name="Ghost",
                age="x",
                city="Chennai",
                signup_date="2025-02-20",
                email="not-an-email",
                _ingest_ts=datetime(2026, 6, 1, 11, 0, 0),
                _source_file="lp/b.json",
                _rescued_data=None,
            ),
        ],
        schema=_RAW_SCHEMA,
    )


def test_clean_customers_standardizes_types_and_email(spark):
    out = clean_customers(_raw_customers(spark))

    assert out.columns == [
        "customer_id",
        "customer_name",
        "age",
        "city",
        "signup_date",
        "email",
        "_ingest_ts",
        "_source_file",
    ]
    first = out.orderBy("customer_name").collect()[0]
    assert first.signup_date == date(2025, 1, 15)
    assert first.age == 34
    assert first.email == "asha@example.com"


def test_clean_customers_tolerates_malformed_values(spark):
    # Spark 4 ANSI mode: plain casts would throw on 'x'; try_cast yields NULL
    # for the dqx rules to flag instead of failing the stream.
    ghost = clean_customers(_raw_customers(spark)).orderBy("customer_name").collect()[1]
    assert ghost.age is None


def test_clean_customers_drops_unknown_columns(spark):
    out = clean_customers(_raw_customers(spark))
    assert "_rescued_data" not in out.columns


def test_transforms_are_registered_for_yaml():
    discover()
    assert TRANSFORMS["sales.clean_customers"] is clean_customers
    assert TRANSFORMS["sales.summarize_customers_by_city"] is summarize_customers_by_city


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
