"""Integration tests for bronze_to_silver using Databricks Connect.

Run with: pytest notebooks/tests/integration_testing/bronze_silver/bu_sales/test_bronze_to_silver.py -v
"""
import pytest
from datalab_etl.testing import load_notebook_module


@pytest.mark.dbconnect_only
def test_transform_to_silver_with_remote_data(dbconnect_spark_session):
    """Test transformation function with actual bronze table data."""
    nb = load_notebook_module("notebooks/bronze_silver/bu_sales/bronze_to_silver.py")

    # Read from actual bronze table
    try:
        input_df = dbconnect_spark_session.table("customer_sales._bronze.customer")
    except Exception as e:
        pytest.skip(f"Bronze table not accessible: {e}")

    if input_df.count() == 0:
        pytest.skip("Bronze table is empty")

    # Execute transformation
    result_df = nb.transform_to_silver(input_df)

    # Assert: Correct output columns
    assert result_df.columns == [
        "customer_id", "customer_name", "age", "city", "signup_date", "email"
    ]

    # Assert: Date type conversion
    dtypes = dict(result_df.dtypes)
    assert dtypes["signup_date"] in {"date", "timestamp"}

    # Assert: Data exists
    assert result_df.count() > 0


@pytest.mark.dbconnect_only  
def test_bronze_table_has_required_columns(dbconnect_spark_session):
    """Test that bronze table contains all required columns."""
    try:
        input_df = dbconnect_spark_session.table("customer_sales._bronze.customer")
    except Exception as e:
        pytest.skip(f"Bronze table not accessible: {e}")

    # Check for required columns
    required_columns = {
        "customer_id", "customer_name", "age", "city", "signup_date", "email"
    }
    actual_columns = set(input_df.columns)

    missing = required_columns - actual_columns
    assert not missing, f"Bronze table missing columns: {missing}"


@pytest.mark.dbconnect_only
def test_config_is_valid(config_dir):
    """Test that pipeline configuration is properly structured."""
    import json
    from pathlib import Path

    config_path = config_dir / "bronze_silver" / "bu_sales" / "bronze_to_silver.json"

    with open(config_path) as f:
        config = json.load(f)

    # Assert: Required config sections
    assert "source" in config
    assert "target" in config
    assert "quality" in config

    # Assert: Table names configured
    assert "table" in config["source"]
    assert "table" in config["target"]

    # Assert: Upsert mode with merge keys
    assert config["target"]["mode"] == "upsert"
    assert "merge" in config["target"]
    assert "customer_id" in config["target"]["merge"]["keys"]
