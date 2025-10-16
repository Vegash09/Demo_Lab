# 🔗 Databricks Connect Setup Guide

## What Was Wrong

You were manually creating a `DatabricksSession` in your notebook:

```python
# ❌ DON'T DO THIS
from databricks.connect import DatabricksSession
spark = DatabricksSession.builder.profile("dev_diggi").getOrCreate()
```

This caused the error because:
1. It bypasses our helper functions
2. It conflicts with the automatic session management
3. The `return` statement was in the wrong place

## ✅ The Correct Way

**The `get_spark()` helper already handles Databricks Connect automatically!**

```python
# ✅ DO THIS
try:
    spark  # In Databricks, use the provided session
except NameError:
    # Locally, get_spark() handles Databricks Connect automatically
    spark = get_spark(databricks_profile="dev_diggi")
```

## How It Works

The `get_spark()` function automatically:

1. **Detects Databricks runtime** → Returns existing session
2. **Detects Databricks Connect** → Creates remote session
3. **Falls back to local** → Creates local SparkSession

### Detection Logic

```python
# Databricks Connect is used when:
# 1. databricks-connect is installed
# 2. AND one of these is set:
#    - DATABRICKS_CONFIG_PROFILE or DATABRICKS_PROFILE env var
#    - databricks_profile parameter
#    - DATABRICKS_HOST + DATABRICKS_TOKEN env vars
```

## 🔧 Setup Databricks Connect

### Option 1: Using Profile (Recommended)

1. **Configure Databricks CLI:**
   ```bash
   databricks configure --profile dev_diggi
   ```

2. **In your notebook:**
   ```python
   spark = get_spark(databricks_profile="dev_diggi")
   ```

### Option 2: Using Environment Variables

1. **Set environment variables:**
   ```bash
   export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
   export DATABRICKS_TOKEN="dapi..."
   ```
   
   Or in your `.env` file:
   ```env
   DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   DATABRICKS_TOKEN=dapi...
   ```

2. **In your notebook:**
   ```python
   spark = get_spark()  # Automatically uses env vars
   ```

### Option 3: Using Profile Environment Variable

1. **Set the profile:**
   ```bash
   export DATABRICKS_CONFIG_PROFILE=dev_diggi
   ```

2. **In your notebook:**
   ```python
   spark = get_spark()  # Automatically uses the profile
   ```

## 📋 Your Notebook Pattern

This is the **correct pattern** for your notebook:

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, get_widget_value, load_config, has_dbutils

# COMMAND ----------

# Get or create SparkSession
try:
    spark  # type: ignore[name-defined]  # Databricks runtime provides this
except NameError:
    # Local: get_spark() handles Databricks Connect + local fallback
    spark = get_spark(databricks_profile="dev_diggi")
```

**What happens:**
- **In Databricks:** Uses the pre-existing `spark` session
- **Locally with Databricks Connect:** Creates remote session using "dev_diggi" profile
- **Locally without Databricks Connect:** Creates local SparkSession

## 🔍 Troubleshooting

### Seeing warnings when connecting?

**Don't worry!** We've configured `get_spark()` to suppress most warnings:
- ✅ Deprecation warnings are suppressed
- ✅ Log level set to ERROR (only shows critical issues)
- ✅ Java/Scala logs minimized

You might still see a brief "Connecting..." message on **first connection only**. This is normal and can't be suppressed.

**First connection (one-time):**
```
Connecting to Databricks cluster...
Connected successfully!
```

**Subsequent calls:** Silent! ✅

### Error: "No module named 'databricks.connect'"

**Solution:** Install databricks-connect:
```bash
pip install databricks-connect
# or
uv pip install databricks-connect
```

### Error: "Databricks Connect not configured"

**Solution:** Set up your profile or environment variables (see Setup section above)

### Error: "AttributeError: 'SparkSession' has no attribute 'Hook'"

**Solution:** Don't manually import and create `DatabricksSession`. Use `get_spark()` instead!

### Want to force local mode (disable Databricks Connect)?

```python
spark = get_spark(force_local=True)  # Always use local, even if Connect is configured
```

### Want to disable Databricks Connect but keep profile for other tools?

```python
spark = get_spark(prefer_databricks_connect=False)  # Skip Connect, use local
```

## 🎛️ Advanced Configuration

### Custom Spark Config with Databricks Connect

```python
spark = get_spark(
    databricks_profile="dev_diggi",
    extra_conf={
        "spark.sql.shuffle.partitions": "200",
        "spark.executor.memory": "4g",
    }
)
```

### Check What Session Type You're Using

```python
spark = get_spark(databricks_profile="dev_diggi")

# Check if it's a remote session
if hasattr(spark, '_jsc'):
    print("Local SparkSession")
else:
    print("Databricks Connect Session")
```

## 📖 Full Example

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, get_widget_value, load_config, has_dbutils

# COMMAND ----------

# SparkSession setup with Databricks Connect support
try:
    spark  # Databricks runtime
except NameError:
    # Local development with Databricks Connect
    spark = get_spark(
        databricks_profile="dev_diggi",  # Your Databricks profile
        enable_delta=True,                # Delta Lake support
    )

# COMMAND ----------

# Rest of your notebook works the same way!
config_path = get_widget_value("config_path", "", "Config Path")
cfg = load_config(config_path)

# Now you can read from your Databricks workspace
df = spark.table("catalog.schema.table")
df.show()
```

## 🎯 Summary

| Approach | Code | When to Use |
|----------|------|-------------|
| **Databricks Runtime** | `spark` (global) | Running in Databricks notebooks |
| **Databricks Connect** | `spark = get_spark(databricks_profile="dev_diggi")` | Local development, connecting to remote cluster |
| **Local Spark** | `spark = get_spark()` | Local development, no connection needed |
| **Force Local** | `spark = get_spark(force_local=True)` | Testing locally without Connect |

## ✅ Key Takeaways

1. **Never manually create `DatabricksSession`** in notebooks
2. **Use `get_spark()`** - it handles everything automatically
3. **Pass `databricks_profile`** parameter for Databricks Connect
4. **Set environment variables** for automatic profile detection
5. **The same code works** in Databricks, Databricks Connect, and local mode

---

**Now restart your Jupyter kernel and try again!** It should work perfectly. 🎉

