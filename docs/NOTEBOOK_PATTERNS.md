# 📓 Simplified Notebook Patterns

This guide shows the simplified patterns for writing Databricks notebooks that work seamlessly in both Databricks and local development.

## 🎯 Two Patterns - Choose Based on Your Needs

### Pattern 1: Explicit Parameters (Recommended for Jobs) ⭐

**Best for:** Notebooks that run as Databricks jobs with parameters

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import (
    process_batch, get_spark, get_widget_value, 
    load_config, load_quality_config, has_dbutils
)

# COMMAND ----------

# 1️⃣ Get SparkSession
try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# 2️⃣ NOTEBOOK PARAMETERS - Explicit and self-documenting
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")

# COMMAND ----------

# 3️⃣ Load configs (simple, no manual JSON!)
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)

# COMMAND ----------

# 4️⃣ Define your transformation
def transform_to_silver(df):
    return df.select("col1", "col2").filter(F.col("col1").isNotNull())

# COMMAND ----------

# 5️⃣ Run the pipeline
if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg,
    )
```

**Why this pattern?**
- ✅ Parameters are clearly visible
- ✅ Easy to integrate with job YAML
- ✅ Self-documenting
- ✅ Simple config loading (no manual JSON parsing)

### Pattern 2: All-in-One (Quick Prototyping)

**Best for:** Quick prototypes, exploratory notebooks, simple use cases

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, setup_notebook_config, has_dbutils

# COMMAND ----------

# 1️⃣ Get SparkSession
try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# 2️⃣ One-liner setup (creates widgets + loads configs)
cfg, dq_cfg = setup_notebook_config()

# COMMAND ----------

# 3️⃣ Define your transformation
def transform_to_silver(df):
    return df.select("col1", "col2").filter(F.col("col1").isNotNull())

# COMMAND ----------

# 4️⃣ Run the pipeline
if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg,
    )
```

**Why this pattern?**
- ✅ Fastest to write
- ✅ Good for prototypes
- ⚠️ Less visible what parameters are needed
- ⚠️ Harder to integrate with jobs

**That's it!** This single pattern works everywhere:
- ✅ Databricks notebooks
- ✅ Local Jupyter notebooks
- ✅ Interactive window in VS Code
- ✅ Unit tests

## 📚 Available Helper Functions

### 1. `setup_notebook_config()` - One-liner for everything

**The simplest way** to handle configs:

```python
from datalab_etl import setup_notebook_config

# This one line does everything:
# - Creates "config_path" and "dq_config_path" widgets in Databricks UI
# - Loads JSON config files
# - Handles quality config normalization
# - Returns empty dicts locally (for testing)
cfg, dq_cfg = setup_notebook_config()

# Use the configs
process_batch(
    spark,
    source=cfg["source"],
    transform=my_transform,
    target=cfg["target"],
    dq_config=dq_cfg,
)
```

**In Databricks UI:**
- You'll see two text input widgets at the top
- Enter paths like: `/Workspace/path/to/config.json`
- Click "Run All" to execute with your config

**Locally:**
- Returns empty dicts (you can provide test data instead)
- No errors, just works!

### 2. `get_widget_value()` - Custom widgets made easy

Create your own Databricks widgets:

```python
from datalab_etl import get_widget_value

# Creates a widget in Databricks, uses default locally
env = get_widget_value("environment", "dev", "Environment")
batch_date = get_widget_value("batch_date", "2024-01-01", "Batch Date")
debug_mode = get_widget_value("debug", "false", "Debug Mode")

print(f"Running in {env} environment for date {batch_date}")
```

**In Databricks:**
- Creates text widgets in the UI
- User can input values
- Returns the input value

**Locally:**
- Returns the default value
- No errors, seamless!

### 3. `load_config()` - Load JSON configs

```python
from datalab_etl import load_config

# Load any JSON config file
cfg = load_config("/path/to/pipeline_config.json")

# Returns empty dict if file doesn't exist (safe!)
cfg = load_config("")  # Returns {}
cfg = load_config("/nonexistent.json")  # Returns {}, logs warning

# Use the config
source = cfg.get("source", {"table": "default.table"})
```

### 4. `load_quality_config()` - Load DQ configs with normalization

```python
from datalab_etl import load_quality_config, load_config

# Option 1: From dedicated DQ file
dq_cfg = load_quality_config(dq_config_path="/path/to/quality.json")

# Option 2: From main config's "quality" section
cfg = load_config("/path/to/pipeline.json")
dq_cfg = load_quality_config(base_config=cfg)

# Option 3: Both (DQ file takes precedence)
cfg = load_config("/path/to/pipeline.json")
dq_cfg = load_quality_config(
    dq_config_path="/path/to/quality.json",
    base_config=cfg
)

# Handles different formats automatically:
# - Dict: {"checks_table": "...", "quarantine_table": "..."}
# - List: [{"column": "id", "rule": "not_null"}] → {"checks": [...]}
```

### 5. `has_dbutils()` - Detect Databricks environment

```python
from datalab_etl import has_dbutils

if has_dbutils():
    print("Running in Databricks - use production configs")
else:
    print("Running locally - use test data")

# Common pattern: run main logic only in Databricks
if has_dbutils():
    process_batch(...)
```

## 🌟 Complete Examples

### Example 1: Bronze to Silver Pipeline

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, setup_notebook_config, has_dbutils

# COMMAND ----------

try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

cfg, dq_cfg = setup_notebook_config()

# COMMAND ----------

def transform_to_silver(df):
    return (
        df.select("customer_id", "name", "email", "signup_date")
          .withColumn("signup_date", F.to_date("signup_date"))
          .dropDuplicates(["customer_id"])
    )

# COMMAND ----------

# Default DQ config (fallback if none provided)
default_dq = {
    "checks_table": "silver.quality_checks",
    "quarantine_table": "silver.quarantine",
}

if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg or default_dq,
    )
```

### Example 2: Custom Widgets for Parameterization

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import get_spark, get_widget_value, has_dbutils

# COMMAND ----------

try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# Custom parameterization
environment = get_widget_value("env", "dev", "Environment (dev/prod)")
start_date = get_widget_value("start_date", "2024-01-01", "Start Date")
end_date = get_widget_value("end_date", "2024-12-31", "End Date")

print(f"Processing {environment} data from {start_date} to {end_date}")

# COMMAND ----------

# Use parameters in your logic
df = spark.table(f"{environment}.bronze.events")
df_filtered = df.filter(
    F.col("event_date").between(start_date, end_date)
)

if has_dbutils():
    df_filtered.write.mode("overwrite").saveAsTable(f"{environment}.silver.events")
```

### Example 3: Advanced Config with Overrides

```python
# Databricks notebook source
from datalab_etl import (
    get_spark,
    load_config,
    get_widget_value,
    has_dbutils,
    process_batch
)

# COMMAND ----------

try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# Load base config
config_path = get_widget_value("config_path", "", "Config Path")
cfg = load_config(config_path)

# Allow runtime overrides via widgets
table_override = get_widget_value("output_table", "", "Output Table Override")
if table_override:
    cfg["target"]["table"] = table_override

# COMMAND ----------

def my_transform(df):
    return df.select("*").filter(F.col("status") == "ACTIVE")

# COMMAND ----------

if cfg:
    process_batch(spark, source=cfg["source"], transform=my_transform, target=cfg["target"])
```

## 📋 Comparison: Before vs After

### ❌ Before (Complex and Verbose)

```python
# Databricks notebook source
from pyspark.sql import functions as F
import json
from datalab_etl import process_batch

# COMMAND ----------

# Lots of boilerplate for Spark session
try:
    spark  # type: ignore[name-defined]
except NameError:
    from datalab_etl.common.session import get_spark
    if globals().get("spark") is None:
        spark = get_spark(force_local=True)

# COMMAND ----------

# Complex dbutils detection
def _has_dbutils() -> bool:
    try:
        from pyspark.dbutils import DBUtils  # type: ignore  # noqa: F401
        return bool(globals().get("dbutils") is not None)
    except Exception:
        return False

# Manual widget creation
if _has_dbutils():
    dbutils.widgets.text("config_path", "", "Config Path")
    dbutils.widgets.text("dq_config_path", "", "DQ Config Path")
    config_path = dbutils.widgets.get("config_path")
    dq_config_path = dbutils.widgets.get("dq_config_path")
else:
    config_path = ""
    dq_config_path = ""

# COMMAND ----------

# Manual config loading
cfg = {}
if config_path:
    with open(config_path) as f:
        cfg = json.load(f)

# Manual DQ config loading with complex logic
quality_cfg = {}
if dq_config_path:
    with open(dq_config_path) as dq_config_file:
        loaded_quality_cfg = json.load(dq_config_file)
        if isinstance(loaded_quality_cfg, dict):
            quality_cfg = loaded_quality_cfg
        elif isinstance(loaded_quality_cfg, list):
            quality_cfg = {"checks": loaded_quality_cfg}
else:
    base_quality = cfg.get("quality")
    if isinstance(base_quality, dict):
        quality_cfg = base_quality.copy()

# COMMAND ----------

def transform_to_silver(df):
    return df.select("customer_id", "name")

# COMMAND ----------

def _run_main():
    process_batch(spark, source=cfg["source"], transform=transform_to_silver, target=cfg["target"])

if _has_dbutils():
    _run_main()
```

### ✅ After (Simple and Clean)

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, setup_notebook_config, has_dbutils

# COMMAND ----------

try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

cfg, dq_cfg = setup_notebook_config()

# COMMAND ----------

def transform_to_silver(df):
    return df.select("customer_id", "name")

# COMMAND ----------

if has_dbutils() or cfg:
    process_batch(spark, source=cfg["source"], transform=transform_to_silver, target=cfg["target"])
```

**Reduction:** ~60 lines → ~20 lines! 🎉

## 🎓 Best Practices

### ✅ DO

1. **Use `setup_notebook_config()`** for standard config loading
2. **Use `get_widget_value()`** for custom parameters
3. **Provide defaults** for local testing
4. **Check `has_dbutils()`** before running production code
5. **Keep transforms pure** (just DataFrame → DataFrame)

### ❌ DON'T

1. **Don't** manually check for dbutils
2. **Don't** manually create widgets with boilerplate
3. **Don't** manually parse JSON configs
4. **Don't** forget to handle empty configs gracefully
5. **Don't** hardcode paths or values

## 🔧 Troubleshooting

### Issue: Widgets don't appear in Databricks

**Cause:** You might be running in a local environment

**Solution:** This is normal! Widgets only appear in Databricks. Locally, defaults are used.

### Issue: Config not loading

**Cause:** File path might be wrong or file doesn't exist

**Solution:** 
```python
cfg = load_config(config_path)
if not cfg:
    print(f"Warning: No config loaded from {config_path}")
    # Provide test config
    cfg = {"source": {"table": "test.data"}, "target": {"table": "test.output"}}
```

### Issue: Empty configs in notebook

**Cause:** Widget values might be empty

**Solution:**
```python
cfg, dq_cfg = setup_notebook_config()

# Always provide fallbacks
source = cfg.get("source") or {"table": "bronze.default"}
target = cfg.get("target") or {"table": "silver.default"}
```

## 📖 Related Documentation

- [README.md](../README.md) - Main project documentation
- [NOTEBOOK_JOB_INTEGRATION.md](NOTEBOOK_JOB_INTEGRATION.md) - How notebooks work with Databricks jobs
- [SPARK_SETUP_GUIDE.md](SPARK_SETUP_GUIDE.md) - SparkSession setup
- [src/datalab_etl/common/notebook.py](../src/datalab_etl/common/notebook.py) - Implementation

---

**Version:** 0.1.0 | **Last Updated:** October 2025

