"""project_columns: the source→target mapping generated from `columns:`."""

from datalab.framework.models import ColumnSpec
from datalab.framework.readers import project_columns


def test_projection_renames_casts_and_reorders(spark):
    df = spark.createDataFrame(
        [("C1", "34", "x", "extra")],
        "cust_id string, age string, bad_age string, dropme string",
    )
    out = project_columns(
        df,
        [
            ColumnSpec(name="customer_id", source="cust_id", type="string"),
            ColumnSpec(name="age", type="int"),
            ColumnSpec(name="age_malformed", source="bad_age", type="int"),
        ],
    )
    assert out.columns == ["customer_id", "age", "age_malformed"]  # dropme gone
    row = out.first()
    assert row.customer_id == "C1"
    assert row.age == 34  # cast applied
    assert row.age_malformed is None  # try_cast: malformed → NULL, no ANSI crash


def test_projection_without_columns_is_identity(spark):
    df = spark.createDataFrame([("a",)], "x string")
    assert project_columns(df, []) is df
