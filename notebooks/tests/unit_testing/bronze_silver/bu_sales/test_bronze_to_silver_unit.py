"""Unit tests for bronze_to_silver transform_to_silver() function.

Run with: pytest notebooks/tests/unit_testing/bronze_silver/bu_sales/test_bronze_to_silver.py -v
"""
import pytest
from datalab_etl.testing import load_notebook_module_for_test


def test_transform_to_silver_selects_columns_and_casts_date(spark_session):
    """Test that transformation selects correct columns and converts date."""
    nb = load_notebook_module_for_test(__file__)

    # Create test input data
    rows = [
        (1, "Alice", 30, "NYC", "2024-10-01", "alice@example.com", "extra"),
        (2, "Bob", None, "SF", "2024-10-02", "bob@example.com", "extra"),
    ]
    input_df = spark_session.createDataFrame(
        rows,
        schema="customer_id int, customer_name string, age int, city string, "
               "signup_date string, email string, extra string",
    )

    # Execute transformation
    result_df = nb.transform_to_silver(input_df)

    # Assert: Correct columns (extra column removed)
    assert result_df.columns == [
        "customer_id", "customer_name", "age", "city", "signup_date", "email"
    ]

    # Assert: signup_date converted to date type
    dtypes = dict(result_df.dtypes)
    assert dtypes["signup_date"] in {"date", "timestamp"}


def test_transform_to_silver_handles_nulls(spark_session):
    """Test that transformation preserves null values correctly."""
    nb = load_notebook_module_for_test(__file__)

    # Create test data with nulls
    rows = [
        (1, "Alice", None, "NYC", "2024-10-01", "alice@example.com"),
        (2, "Bob", 25, None, "2024-10-02", None),
    ]
    input_df = spark_session.createDataFrame(
        rows,
        schema="customer_id int, customer_name string, age int, city string, "
               "signup_date string, email string",
    )

    # Execute transformation
    result_df = nb.transform_to_silver(input_df)

    # Assert: All rows preserved
    assert result_df.count() == 2

    # Assert: Nulls maintained
    collected = result_df.collect()
    assert collected[0]["age"] is None
    assert collected[1]["city"] is None
    assert collected[1]["email"] is None


def test_transform_to_silver_preserves_all_rows(spark_session):
    """Test that no rows are filtered during transformation."""
    nb = load_notebook_module_for_test(__file__)

    # Create multiple rows
    rows = [
        (i, f"Customer_{i}", 20 + i, f"City_{i}", f"2024-01-{i:02d}", f"user{i}@example.com")
        for i in range(1, 11)
    ]
    input_df = spark_session.createDataFrame(
        rows,
        schema="customer_id int, customer_name string, age int, city string, "
               "signup_date string, email string",
    )

    # Execute transformation
    result_df = nb.transform_to_silver(input_df)

    # Assert: Same number of rows (no filtering)
    assert result_df.count() == 10
