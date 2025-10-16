# 📋 Notebook & Job Integration Guide

This guide explains how notebooks work seamlessly with Databricks job parameters while maintaining excellent developer experience.

## 🎯 The Improved Pattern

### ✅ Explicit Widget Declarations + Simple Config Loading

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import (
    process_batch, 
    get_spark, 
    get_widget_value,      # Creates widgets explicitly
    load_config,           # Loads JSON configs
    load_quality_config,   # Loads DQ configs
    has_dbutils
)

# COMMAND ----------

# Get SparkSession
try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# NOTEBOOK PARAMETERS - Creates widgets in Databricks UI
# When running as a job, these values come from job parameters
# When running in UI, user can input values in the widgets
config_path = get_widget_value(
    name="config_path",
    default="",
    label="Config Path"
)

dq_config_path = get_widget_value(
    name="dq_config_path",
    default="",
    label="DQ Config Path"
)

# COMMAND ----------

# Load configurations from the paths (simple, no manual JSON parsing!)
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)

# COMMAND ----------

# Your transformation
def transform_to_silver(df):
    return df.select("customer_id", "name")

# COMMAND ----------

# Run the pipeline
if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg,
    )
```

## 🔄 How It Works in Different Contexts

### 1. Running as a Databricks Job

**Job YAML:**
```yaml
resources:
  jobs:
    sales_bronze_to_silver:
      name: sales-bronze-to-silver-job
      
      parameters:
        - name: config_path
          default: "/Workspace/config/bronze_silver.json"
        - name: dq_config_path
          default: "/Workspace/config/quality.json"
      
      tasks:
        - task_key: bronze_to_silver
          notebook_task:
            notebook_path: "/notebooks/bronze_to_silver"
            base_parameters:
              config_path: "{{ job.parameters.config_path }}"
              dq_config_path: "{{ job.parameters.dq_config_path }}"
```

**What Happens:**
1. ✅ Job passes parameters to notebook
2. ✅ `get_widget_value()` receives those parameters
3. ✅ `load_config()` loads the JSON files
4. ✅ Pipeline runs with the provided configs
5. ✅ **Widgets are NOT displayed** (job mode)

### 2. Running in Databricks UI

**What You See:**
```
┌─────────────────────────────────────────────┐
│ Config Path:     [________________________] │
│ DQ Config Path:  [________________________] │
└─────────────────────────────────────────────┘
```

**What Happens:**
1. ✅ Widgets appear at the top of the notebook
2. ✅ User enters paths: `/Workspace/path/to/config.json`
3. ✅ Click "Run All"
4. ✅ `get_widget_value()` reads from widgets
5. ✅ `load_config()` loads the JSON files
6. ✅ Pipeline runs with user-provided configs

### 3. Running Locally (VS Code, Jupyter)

**What Happens:**
1. ✅ No widgets (not needed)
2. ✅ `get_widget_value()` returns empty string `""`
3. ✅ `load_config("")` returns empty dict `{}`
4. ✅ No errors, everything just works!
5. ✅ You can test with mock data

## 💡 Key Benefits of This Pattern

### 1. **Self-Documenting**

The notebook clearly shows what parameters it expects:

```python
# Anyone reading the notebook immediately sees:
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")
```

✅ Clear parameter names  
✅ Clear labels  
✅ Default values visible  

### 2. **Works with Job Parameters**

The widget names match your job parameters:

**Job YAML:**
```yaml
base_parameters:
  config_path: "{{ job.parameters.config_path }}"      # ✅ Matches widget name
  dq_config_path: "{{ job.parameters.dq_config_path }}" # ✅ Matches widget name
```

**Notebook:**
```python
config_path = get_widget_value("config_path", ...)      # ✅ Same name
dq_config_path = get_widget_value("dq_config_path", ...) # ✅ Same name
```

### 3. **Simple Config Loading**

No more manual JSON parsing! Before vs After:

**❌ Before:**
```python
cfg = {}
if config_path:
    with open(config_path) as f:
        cfg = json.load(f)

quality_cfg = {}
if dq_config_path:
    with open(dq_config_path) as dq_config_file:
        loaded_quality_cfg = json.load(dq_config_file)
        if isinstance(loaded_quality_cfg, dict):
            quality_cfg = loaded_quality_cfg
        elif isinstance(loaded_quality_cfg, list):
            quality_cfg = {"checks": loaded_quality_cfg}
# ... more complex logic
```

**✅ After:**
```python
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

### 4. **Safe and Robust**

- ✅ Handles missing files gracefully
- ✅ Handles empty paths
- ✅ Normalizes different config formats
- ✅ Works in all environments
- ✅ No crashes on edge cases

## 📋 Examples with Different Parameter Patterns

### Example 1: Config Paths (Your Current Pattern)

```python
# NOTEBOOK PARAMETERS
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")

# Load configs
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

**Job YAML:**
```yaml
base_parameters:
  config_path: "/Workspace/config/bronze_silver.json"
  dq_config_path: "/Workspace/config/quality.json"
```

### Example 2: Direct Table Names

```python
# NOTEBOOK PARAMETERS
source_table = get_widget_value("source_table", "bronze.customers", "Source Table")
target_table = get_widget_value("target_table", "silver.customers", "Target Table")

# Build config dynamically
cfg = {
    "source": {"table": source_table},
    "target": {"table": target_table}
}
```

**Job YAML:**
```yaml
base_parameters:
  source_table: "bronze.prod_customers"
  target_table: "silver.prod_customers"
```

### Example 3: Environment-Based

```python
# NOTEBOOK PARAMETERS
environment = get_widget_value("environment", "dev", "Environment (dev/staging/prod)")
batch_date = get_widget_value("batch_date", "2024-01-01", "Batch Date")

# Build paths based on environment
config_path = f"/Workspace/config/{environment}/bronze_silver.json"
cfg = load_config(config_path)

# Add runtime parameters
cfg["batch_date"] = batch_date
```

**Job YAML:**
```yaml
base_parameters:
  environment: "{{ job.parameters.environment }}"
  batch_date: "{{ job.parameters.batch_date }}"
```

### Example 4: Hybrid (Config + Overrides)

```python
# NOTEBOOK PARAMETERS - Base config
config_path = get_widget_value("config_path", "", "Config Path")

# NOTEBOOK PARAMETERS - Optional overrides
output_table_override = get_widget_value("output_table", "", "Output Table (optional override)")
partition_override = get_widget_value("partition_by", "", "Partition By (optional override)")

# Load base config
cfg = load_config(config_path)

# Apply overrides if provided
if output_table_override:
    cfg["target"]["table"] = output_table_override
if partition_override:
    cfg["target"]["partitionBy"] = partition_override.split(",")
```

**Job YAML:**
```yaml
base_parameters:
  config_path: "/Workspace/config/base.json"
  output_table: "silver.special_customers"  # Override from job
  partition_by: "region,date"                # Override from job
```

## 🎓 Best Practices

### ✅ DO

1. **Use descriptive widget names** that match job parameters
   ```python
   config_path = get_widget_value("config_path", "", "Config Path")  # ✅ Clear
   ```

2. **Provide meaningful labels**
   ```python
   env = get_widget_value("env", "dev", "Environment (dev/staging/prod)")  # ✅ Helpful
   ```

3. **Add comments explaining parameters**
   ```python
   # NOTEBOOK PARAMETERS - Creates widgets in Databricks UI
   # When running as a job, these values come from job parameters
   config_path = get_widget_value("config_path", "", "Config Path")
   ```

4. **Group related parameters**
   ```python
   # Config parameters
   config_path = get_widget_value("config_path", "", "Config Path")
   dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")
   
   # Runtime parameters
   batch_date = get_widget_value("batch_date", "", "Batch Date")
   ```

5. **Use safe config access**
   ```python
   source = cfg.get("source", {"table": "default.table"})  # ✅ Safe with default
   ```

### ❌ DON'T

1. **Don't hide parameters in helper functions**
   ```python
   # ❌ BAD - parameters are hidden
   cfg, dq_cfg = setup_notebook_config()  # What parameters does this need?
   
   # ✅ GOOD - parameters are explicit
   config_path = get_widget_value("config_path", "", "Config Path")
   dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")
   cfg = load_config(config_path)
   dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
   ```

2. **Don't manually parse JSON**
   ```python
   # ❌ BAD
   with open(config_path) as f:
       cfg = json.load(f)
   
   # ✅ GOOD
   cfg = load_config(config_path)  # Handles errors, missing files, etc.
   ```

3. **Don't use hardcoded widget defaults for production values**
   ```python
   # ❌ BAD
   table = get_widget_value("table", "prod.customers", ...)  # Dangerous!
   
   # ✅ GOOD
   table = get_widget_value("table", "", ...)  # Empty default, force explicit value
   ```

## 🔍 Comparison: Parameter Visibility

### ❌ Hidden Parameters (Bad for Jobs)

```python
# What parameters does this notebook need? 
# You have to read the function source code to know!
cfg, dq_cfg = setup_notebook_config()
```

**Issues:**
- ⚠️ Parameters are hidden in the function
- ⚠️ Not clear what job parameters to provide
- ⚠️ Hard to document
- ⚠️ Difficult for new developers

### ✅ Explicit Parameters (Good for Jobs)

```python
# Clear! This notebook needs config_path and dq_config_path
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

**Benefits:**
- ✅ Parameters clearly visible in notebook
- ✅ Easy to match with job YAML
- ✅ Self-documenting
- ✅ Easy for new developers

## 📊 Summary

| Aspect | Hidden Approach | **Explicit Approach** |
|--------|----------------|---------------------|
| **Parameter Visibility** | Hidden in function | ✅ **Clear in notebook** |
| **Job Integration** | Must read function code | ✅ **Matches job params** |
| **Developer Experience** | Magic, hard to understand | ✅ **Self-documenting** |
| **Config Loading** | Complex manual parsing | ✅ **Simple helpers** |
| **Error Handling** | Must implement yourself | ✅ **Built-in** |
| **Flexibility** | Limited to function design | ✅ **Highly flexible** |

## 🚀 Migration: Hidden → Explicit

**Before (Too Hidden):**
```python
cfg, dq_cfg = setup_notebook_config()  # What does this create?
```

**After (Clear & Explicit):**
```python
# NOTEBOOK PARAMETERS
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")

# Load configurations
cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

**Benefits:**
- Same simplicity for config loading
- Better visibility of parameters
- Easier integration with jobs
- Self-documenting code

---

**Conclusion:** Explicit widget creation + helper functions for config loading = **Best of both worlds!** 🎉

