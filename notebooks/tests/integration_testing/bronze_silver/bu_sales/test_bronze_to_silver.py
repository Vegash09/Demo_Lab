import pytest
from datalab_etl.testing import load_notebook_module


@pytest.mark.dbconnect_only
def test_transform_to_silver_remote(dbconnect_spark_session):
    nb = load_notebook_module("notebooks/bronze_silver/bu_sales/bronze_to_silver.py")

    input_df = dbconnect_spark_session.table("customer_sales._bronze.customer")

    out_df = nb.transform_to_silver(input_df)

    # Columns reduced and ordered
    assert out_df.columns == [
        "customer_id",
        "customer_name",
        "age",
        "city",
        "signup_date",
        "email",
    ]

    # signup_date is converted to date and preserved (remote env may upcast to timestamp)
    dtypes = dict(out_df.dtypes)
    assert dtypes["signup_date"] in {"date", "timestamp"}

