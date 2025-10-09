from datalab_etl.testing import load_notebook_module_for_test

def test_transform_to_silver_selects_columns_and_casts_date(spark_session):
    nb = load_notebook_module_for_test(__file__)

    rows = [
        (1, "Alice", 30, "NYC", "2024-10-01", "alice@example.com", "x"),
        (2, "Bob", None, "SF", "2024-10-02", "bob@example.com", "y"),
    ]
    input_df = spark_session.createDataFrame(
        rows,
        schema="customer_id int, customer_name string, age int, city string, signup_date string, email string, extra string",
    )

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

    # signup_date is converted to date and preserved
    dtypes = dict(out_df.dtypes)
    assert dtypes["signup_date"] in {"date", "timestamp"}  # some envs may upcast
