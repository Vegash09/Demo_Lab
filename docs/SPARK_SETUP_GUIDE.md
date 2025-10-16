# 🚀 Simplified SparkSession Setup Guide

This guide explains the simplified SparkSession initialization pattern used in this repository.

## ✨ Quick Start

### In Notebooks (Databricks or Local)

```python
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark

# Single line to get SparkSession (works everywhere!)
try:
    spark  # type: ignore[name-defined]  # Databricks provides this
except NameError:
    spark = get_spark()  # Local development: creates configured session
```

**That's it!** No complex logic, no environment checks, just one simple pattern.

## 🎯 What `get_spark()` Does

The `get_spark()` function automatically:

1. **Detects your environment** (Databricks vs local)
2. **Returns existing session** in Databricks
3. **Creates local session** for development with:
   - Delta Lake support (auto-downloads jars)
   - Optimized settings for local testing
   - Minimal logging (ERROR level only)
   - Disabled Spark UI for cleaner output
   - Fast shuffle partitions (4 for testing)

## 📋 Example Notebooks

### Bronze to Silver Pipeline

```python
# Databricks notebook source
from pyspark.sql import functions as F
import json

from datalab_etl import process_batch, get_spark

# COMMAND ----------

# Get or create SparkSession
try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

def transform_to_silver(df):
    return df.select("customer_id", "customer_name", "age", "city")

# COMMAND ----------

# Process batch
process_batch(
    spark,
    source={"table": "bronze.customers"},
    transform=transform_to_silver,
    target={"table": "silver.customers"},
)
```

### DLT Pipeline

```python
import dlt
from datalab_etl import get_spark

@dlt.table(name="silver.cleaned_events")
def cleaned_events():
    # Get SparkSession (DLT provides it, but we need it for local testing)
    try:
        spark  # type: ignore[name-defined]
    except NameError:
        spark = get_spark()
    
    return spark.readStream.format("cloudFiles").load("/data/source")
```

## 🔧 Configuration Options

### Basic Usage

```python
from datalab_etl import get_spark

# Default: Delta enabled, local development optimized
spark = get_spark()
```

### Custom Configuration

```python
# Custom app name
spark = get_spark(app_name="MyCustomApp")

# Disable Delta (not recommended)
spark = get_spark(enable_delta=False)

# Add custom Spark config
spark = get_spark(extra_conf={"spark.sql.shuffle.partitions": "8"})

# Force local mode (for testing)
spark = get_spark(force_local=True)

# Use Databricks Connect (automatic if configured)
spark = get_spark(prefer_databricks_connect=True, databricks_profile="my-profile")
```

## 🏗️ Local Development Setup

### Prerequisites

1. **Python 3.13** (or 3.12+)
2. **PySpark 4.0+** (automatically installed)
3. **Delta Lake 4.0+** (automatically installed)

### Installation

```bash
# Install the package with PySpark extras
uv pip install -e ".[pyspark]"

# Or using pip
pip install -e ".[pyspark]"
```

### Running Notebooks Locally

```bash
# In VS Code with Jupyter extension or interactive window
# Just run the cells - SparkSession will be created automatically!
```

## 🌐 Environment Detection

`get_spark()` automatically detects your environment:

| Environment | Detection Method | Behavior |
|-------------|------------------|----------|
| **Databricks Runtime** | Checks env vars, `/databricks` folder | Returns existing session |
| **Databricks Connect** | Checks for config/credentials | Creates remote session |
| **Local Development** | Default fallback | Creates local session |

## ⚙️ Local Session Defaults

When running locally, `get_spark()` configures:

```python
{
    "spark.master": "local[*]",  # Use all CPU cores
    "spark.sql.shuffle.partitions": "4",  # Fast for small data
    "spark.ui.enabled": "false",  # No web UI (cleaner)
    "spark.ui.showConsoleProgress": "false",  # No progress bars
    "spark.sql.adaptive.enabled": "true",  # Smart query optimization
    
    # Delta Lake support (auto-downloads jars)
    "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
    "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
    "spark.jars.packages": "io.delta:delta-spark_2.13:4.0.0",
}
```

Plus:
- Log level set to `ERROR` (minimal noise)
- Java log level set to `WARN`

## 🧪 Testing

### Unit Tests

```python
# tests/conftest.py provides spark fixture
def test_my_transform(spark):
    df = spark.createDataFrame([...])
    result = my_transform(df)
    assert result.count() == expected_count
```

### Integration Tests

```python
# With Databricks Connect
@pytest.mark.dbconnect_only
def test_with_remote_cluster(dbconnect_spark_session):
    # Uses real Databricks cluster
    df = dbconnect_spark_session.read.table("bronze.my_table")
    ...
```

## ❓ Troubleshooting

### Issue: ModuleNotFoundError: No module named 'datalab_etl'

**Solution:**
```bash
uv pip install -e ".[pyspark]"
```

### Issue: ImportError with PySpark

**Solution:** Make sure you're using Python 3.12+ and PySpark 4.0+
```bash
python --version  # Should be 3.12+
pip show pyspark  # Should be 4.0+
```

### Issue: Delta Lake warnings

**Solution:** The first run may download Delta jars (this is normal). Subsequent runs will be faster.

### Issue: "Unable to locate a Java Runtime"

**Solution:** 
- macOS: `brew install openjdk@17`
- Linux: `sudo apt-get install openjdk-17-jdk`
- Windows: Download from [Adoptium](https://adoptium.net/)

## 📚 Related Documentation

- [README.md](../README.md) - Main project documentation
- [NOTEBOOK_PATTERNS.md](NOTEBOOK_PATTERNS.md) - **Simplified notebook config patterns**
- [NOTEBOOK_JOB_INTEGRATION.md](NOTEBOOK_JOB_INTEGRATION.md) - How notebooks work with jobs
- [src/datalab_etl/common/session.py](../src/datalab_etl/common/session.py) - SparkSession implementation
- [src/datalab_etl/common/notebook.py](../src/datalab_etl/common/notebook.py) - Config helpers implementation
- [notebooks/bronze_silver/bu_sales/bronze_to_silver.py](../notebooks/bronze_silver/bu_sales/bronze_to_silver.py) - Example notebook

## 🎓 Best Practices

1. ✅ **DO**: Use `get_spark()` at the start of your notebook
2. ✅ **DO**: Reuse the same SparkSession throughout your code
3. ✅ **DO**: Use the try/except pattern in notebooks (Databricks compatibility)
4. ❌ **DON'T**: Create multiple SparkSessions
5. ❌ **DON'T**: Hardcode environment-specific configs
6. ❌ **DON'T**: Call `spark.stop()` in notebooks (let the runtime handle it)

## 💡 Summary

**Before (Complex):**
```python
try:
    spark  # type: ignore[name-defined]
except NameError:
    from datalab_etl.common.session import get_spark
    if globals().get("spark") is None:
        spark = get_spark(force_local=True, enable_delta=True)
```

**After (Simple):**
```python
try:
    spark  # type: ignore[name-defined]
except NameError:
    from datalab_etl import get_spark
    spark = get_spark()
```

---

**Version:** 0.1.0 | **Last Updated:** October 2025

