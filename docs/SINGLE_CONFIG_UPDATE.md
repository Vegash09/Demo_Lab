# 🎉 Single Config File Update

## What Changed

You requested to consolidate the configuration into a **single JSON file** instead of having separate config and quality files. This is now complete!

## ✅ Changes Made

### 1. **Merged Configuration Files**

**Before:** Two separate files
- `config/bronze_silver/bu_sales/bronze_to_silver.json` (source & target)
- `config/bronze_silver/bu_sales/bronze_to_silver_quality.json` (quality checks)

**After:** One unified file
- `config/bronze_silver/bu_sales/bronze_to_silver.json` (source, target, AND quality!)

**New Structure:**
```json
{
  "source": { 
    "table": "customer_sales._bronze.customer" 
  },
  "target": {
    "table": "customer_sales._silver.customer",
    "clusterBy": "city",
    "mode": "upsert",
    "merge": { "keys": ["customer_id"] }
  },
  "quality": {
    "checks": [
      {
        "criticality": "error",
        "check": {
          "function": "is_not_null",
          "arguments": { "column": "customer_id" }
        }
      },
      {
        "criticality": "warn",
        "check": {
          "function": "regex_match",
          "arguments": {
            "column": "email",
            "regex": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
          }
        }
      }
    ],
    "quarantine_table": "customer_sales._silver.customer_quarantine"
  }
}
```

### 2. **Simplified Notebook**

**Before:** Two parameters
```python
config_path = get_widget_value("config_path", "", "Config Path")
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")

cfg = load_config(config_path)
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

**After:** One parameter
```python
config_path = get_widget_value("config_path", "", "Config Path")

cfg = load_config(config_path)
dq_cfg = cfg.get("quality", {})
```

### 3. **Simplified Job YAML**

**Before:** Two parameters
```yaml
parameters:
  - name: config_path
    default: "${workspace.root_path}/files/config/bronze_silver/bu_sales/bronze_to_silver.json"
  - name: dq_config_path
    default: "${workspace.root_path}/files/config/bronze_silver/bu_sales/bronze_to_silver_quality.json"

base_parameters:
  config_path: "{{ job.parameters.config_path }}"
  dq_config_path: "{{ job.parameters.dq_config_path }}"
```

**After:** One parameter
```yaml
parameters:
  - name: config_path
    default: "${workspace.root_path}/files/config/bronze_silver/bu_sales/bronze_to_silver.json"

base_parameters:
  config_path: "{{ job.parameters.config_path }}"
```

### 4. **Organized Documentation**

All documentation moved to `docs/` folder:
- ✅ `docs/NOTEBOOK_PATTERNS.md`
- ✅ `docs/NOTEBOOK_JOB_INTEGRATION.md`
- ✅ `docs/SPARK_SETUP_GUIDE.md`
- ✅ `docs/SIMPLIFICATION_SUMMARY.md`
- ✅ `docs/FINAL_SUMMARY.md`
- ✅ `docs/SINGLE_CONFIG_UPDATE.md` (this file)
- ✅ `README.md` (stays in root)

## 🎯 Benefits

### 1. **Simpler Configuration Management**

**Before:**
- 2 files to maintain per pipeline
- Risk of config files getting out of sync
- More complex job parameters

**After:**
- ✅ 1 file per pipeline
- ✅ Everything in one place
- ✅ Simpler job configuration

### 2. **Cleaner Notebook**

**Lines Removed:**
```python
# Don't need this anymore!
dq_config_path = get_widget_value("dq_config_path", "", "DQ Config Path")
dq_cfg = load_quality_config(dq_config_path, base_config=cfg)
```

**What You Have Now:**
```python
# Just extract quality from main config
dq_cfg = cfg.get("quality", {})
```

### 3. **Better Developer Experience**

- **One config file** to look at
- **One widget** in Databricks UI
- **One parameter** in job YAML
- **Less confusion** about what goes where

## 📁 Updated File Structure

```
datalab/
├── config/
│   └── bronze_silver/
│       └── bu_sales/
│           └── bronze_to_silver.json        # ✅ All-in-one config!
│
├── notebooks/
│   └── bronze_silver/
│       └── bu_sales/
│           └── bronze_to_silver.py         # ✅ Simplified notebook
│
├── pipelines/
│   └── sales_bronze_to_silver.job.yml     # ✅ Single parameter
│
├── docs/                                   # ✅ All documentation here
│   ├── NOTEBOOK_PATTERNS.md
│   ├── NOTEBOOK_JOB_INTEGRATION.md
│   ├── SPARK_SETUP_GUIDE.md
│   ├── SIMPLIFICATION_SUMMARY.md
│   ├── FINAL_SUMMARY.md
│   └── SINGLE_CONFIG_UPDATE.md
│
└── README.md                               # ✅ Stays in root
```

## 📋 Your Notebook Now

```python
# Databricks notebook source
from pyspark.sql import functions as F
from datalab_etl import process_batch, get_spark, get_widget_value, load_config, has_dbutils

# COMMAND ----------

# Get SparkSession
try:
    spark  # type: ignore[name-defined]
except NameError:
    spark = get_spark()

# COMMAND ----------

# Single config parameter!
config_path = get_widget_value("config_path", "", "Config Path")

# COMMAND ----------

# Load everything from one file
cfg = load_config(config_path)
dq_cfg = cfg.get("quality", {})

# COMMAND ----------

def transform_to_silver(df):
    return (
        df.select("customer_id", "customer_name", "age", "city", "signup_date", "email")
          .withColumn("signup_date", F.to_date("signup_date"))
    )

# COMMAND ----------

if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg,
    )
```

## 🚀 How to Use

### In Databricks UI

1. Open the notebook
2. You'll see **ONE widget**: `Config Path`
3. Enter: `/Workspace/config/bronze_silver/bu_sales/bronze_to_silver.json`
4. Click "Run All"
5. Done! The config includes source, target, AND quality settings

### In Databricks Job

Your job YAML is now simpler:
```yaml
parameters:
  - name: config_path
    default: "${workspace.root_path}/files/config/bronze_silver/bu_sales/bronze_to_silver.json"
```

### Locally (VS Code)

Same as before - works seamlessly with empty configs for testing.

## 📚 Config File Template

For new pipelines, use this template:

```json
{
  "source": {
    "table": "catalog.schema.source_table"
  },
  "target": {
    "table": "catalog.schema.target_table",
    "mode": "overwrite",
    "partitionBy": ["date_column"]
  },
  "quality": {
    "checks": [
      {
        "criticality": "error",
        "check": {
          "function": "is_not_null",
          "arguments": {
            "column": "id_column"
          }
        }
      }
    ],
    "quarantine_table": "catalog.schema.target_table_quarantine"
  }
}
```

## ✨ Summary

| Aspect | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Config files** | 2 files | 1 file | **50% fewer files** |
| **Notebook parameters** | 2 widgets | 1 widget | **50% simpler** |
| **Job parameters** | 2 parameters | 1 parameter | **50% simpler** |
| **Lines in notebook** | 4 lines for config | 2 lines for config | **50% less code** |
| **Documentation** | Root + docs/ | Only docs/ | **Better organized** |

---

**Result:** One config file to rule them all! 🎉

