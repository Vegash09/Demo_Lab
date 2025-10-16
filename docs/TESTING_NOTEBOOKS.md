# Notebook Testing Guide

Simple guide for testing notebook transformation functions.

## Overview

**Two types of tests:**
1. **Unit Tests** (`_unit.py`) - Test transformation functions locally (fast, no Databricks)
2. **Integration Tests** (`_integration.py`) - Test with Databricks Connect (real data)

## File Structure

```
notebooks/tests/
├── unit_testing/
│   ├── conftest.py                           # Unit test fixtures
│   └── bronze_silver/bu_sales/
│       └── test_bronze_to_silver_unit.py     # 3 unit tests
└── integration_testing/
    ├── conftest.py                           # Integration test fixtures
    └── bronze_silver/bu_sales/
        └── test_bronze_to_silver_integration.py  # 3 integration tests
```

## Running Tests

### Option 1: Unit Tests (Local Spark)

**Note:** If you have `databricks-connect` installed, unit tests will be skipped. Either:
- Create a separate venv without databricks-connect for unit tests
- OR just use integration tests (recommended if you have Databricks Connect)

```bash
# Run all unit tests
pytest notebooks/tests/unit_testing/ -v
```

### Option 2: Integration Tests (Databricks Connect - Recommended)

```bash
# Set your profile
export DATABRICKS_CONFIG_PROFILE="dev_diggi"

# Run all integration tests
pytest notebooks/tests/integration_testing/ -v

# Run specific test file
pytest notebooks/tests/integration_testing/bronze_silver/bu_sales/test_bronze_to_silver_integration.py -v
```

## What Each Test Does

### Unit Tests (`test_bronze_to_silver_unit.py`)

1. **test_transform_to_silver_selects_columns_and_casts_date**
   - ✅ Selects correct output columns
   - ✅ Removes extra columns
   - ✅ Converts `signup_date` string to date type

2. **test_transform_to_silver_handles_nulls**
   - ✅ Preserves null values in optional fields
   - ✅ Doesn't filter out rows with nulls

3. **test_transform_to_silver_preserves_all_rows**
   - ✅ No rows are filtered during transformation
   - ✅ Input count = Output count

### Integration Tests (`test_bronze_to_silver_integration.py`)

1. **test_transform_to_silver_with_remote_data**
   - ✅ Reads from actual `customer_sales._bronze.customer` table
   - ✅ Transformation produces correct columns
   - ✅ Date conversion works with real data

2. **test_bronze_table_has_required_columns**
   - ✅ Bronze table exists and is accessible
   - ✅ Contains all required columns

3. **test_config_is_valid**
   - ✅ Configuration file is properly structured
   - ✅ Source/target tables configured
   - ✅ Upsert mode with merge keys set
   - ✅ Quality checks configured

## Common Commands

```bash
# Run all tests (both unit and integration)
pytest notebooks/tests/ -v

# Run only integration tests
pytest notebooks/tests/integration_testing/ -v

# Run specific test
pytest notebooks/tests/integration_testing/bronze_silver/bu_sales/test_bronze_to_silver_integration.py::test_config_is_valid -v

# Show more details
pytest notebooks/tests/integration_testing/ -v -s

# Stop on first failure
pytest notebooks/tests/integration_testing/ -v -x
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -e .
pip install pytest pytest-cov
```

### 2. For Integration Tests, Set Databricks Profile

```bash
export DATABRICKS_CONFIG_PROFILE="dev_diggi"
```

### 3. Run Tests

```bash
pytest notebooks/tests/integration_testing/ -v
```

## Expected Output

```
test_transform_to_silver_with_remote_data PASSED ✓
test_bronze_table_has_required_columns PASSED ✓
test_config_is_valid PASSED ✓

=== 3 passed in 5.23s ===
```

## Troubleshooting

### Issue: Unit tests all SKIPPED

**Cause:** `databricks-connect` is installed, which disables local Spark.

**Solution:** Use integration tests instead, or create a separate venv for unit tests:
```bash
python -m venv .venv-unit
source .venv-unit/bin/activate
pip install -e ".[pyspark]"
pytest notebooks/tests/unit_testing/ -v
```

### Issue: Integration tests SKIPPED

**Cause:** Databricks Connect not configured.

**Solution:** Set credentials:
```bash
export DATABRICKS_CONFIG_PROFILE="dev_diggi"
# OR
export DATABRICKS_HOST="https://your-workspace.databricks.com"
export DATABRICKS_TOKEN="your-token"
```

### Issue: "Bronze table not accessible"

**Cause:** Table doesn't exist or no permissions.

**Solution:** Tests automatically skip if tables don't exist. This is normal behavior.

## Writing New Tests

### Unit Test Template

```python
from datalab_etl.testing import load_notebook_module_for_test

def test_my_transformation(spark_session):
    nb = load_notebook_module_for_test(__file__)
    
    input_df = spark_session.createDataFrame(
        [(1, "test")],
        "id int, name string"
    )
    
    result_df = nb.transform_to_silver(input_df)
    
    assert result_df.count() == 1
```

### Integration Test Template

```python
import pytest
from datalab_etl.testing import load_notebook_module

@pytest.mark.dbconnect_only
def test_with_real_data(dbconnect_spark_session):
    nb = load_notebook_module("notebooks/your_notebook.py")
    
    input_df = dbconnect_spark_session.table("catalog.schema.table")
    result_df = nb.transform(input_df)
    
    assert result_df.count() > 0
```

## Best Practices

- ✅ Keep tests simple (2-3 test cases per notebook)
- ✅ Test transformation logic, not infrastructure
- ✅ Use descriptive test names
- ✅ Unit tests should run in < 1 second
- ✅ Integration tests can skip if tables don't exist
