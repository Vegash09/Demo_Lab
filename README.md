# Datalab – Minimal Data Processing Toolkit

This repository provides a minimal, simple toolkit for reading, transforming, writing, and validating data using common helpers. Developers use shared methods for moving data from one layer to another.

## Philosophy

- Keep only essential, shared building blocks in `src/`.
- Everyone uses the same read/write and data-quality helpers.
- Pipelines are thin: provide a transform function and call common processors.

## Key Features

- Shared IO: supports managed/external tables, paths, partitionBy, bucketBy, clusterBy, modes
- Delta merge (upsert) support when configured
- Common batch/stream processing helpers with optional DQ hooks

## Quick Start

### Step 1: Copy Configuration Template

```bash
cp templates/conf/bronze_silver/example_pipeline.json \
   conf/bronze_silver/my_pipeline.json
```

### Step 2: Use common API

```python
from pyspark.sql import functions as F
from datalab_etl import process_batch, process_streaming
from datalab_etl.common.session import get_spark

spark = get_spark()

def to_silver(df):
    return (
        df.filter(F.col("status") == F.lit("ACTIVE"))
          .withColumn("ingest_date", F.to_date("ingest_ts"))
    )

process_batch(
    spark,
    source={"table": "bronze.my_data"},
    transform=to_silver,
    target={"table": "silver.my_data", "partitionBy": "ingest_date"},
)
```

### Step 3: Run Generic Notebook

```python
# In Databricks
config_file = "conf/bronze_silver/my_pipeline.json"
%run notebooks/generic_bronze_silver
```

**Done!** No custom code needed!

## Repository Structure

```
datalab/
├── src/
│   ├── datalab_etl/
│   │   ├── common/
│   │   │   ├── session.py         # Spark session helper
│   │   │   ├── io.py              # read/write helpers
│   │   │   └── processing.py      # common batch/stream processors
│   │   └── quality/
│   │       └── dqx_runner.py      # optional DQX wrapper
│
├── notebooks/
│   ├── source_bronze/
│   │   └── bu_sales/
│   ├── bronze_silver/
│   │   └── bu_sales/
│   ├── silver_gold/
│   │   └── bu_sales/
│   └── tests/bronze_silver/bu_sales/test_*.py
│
├── config/
│   ├── source_bronze/
│   │   └── bu_sales/
│   ├── bronze_silver/
│   │   └── bu_sales/
│   └── silver_gold/
│       └── bu_sales/
│
├── pipelines/                    # Job specifications referencing notebooks
│   └── sales_bronze_to_silver.job.yml
│
├── databricks.yml               # Databricks Asset Bundles (targets, resources)

## DLT usage

- Use `src/datalab_etl/dlt/api.py` helpers to build DLT datasets safely (return DataFrames only).
- Example DLT notebook: `notebooks/bronze_silver/bu_sales/dlt_silver_sales_events.py`.
- The DLT pipeline resource is defined in `databricks.yml` under `resources.pipelines` with a notebook library.
- Follow Databricks guidance: do not call save/saveAsTable/start/collect in dataset definitions; return a DataFrame. See the DLT Python reference.

References:
- DLT Python language reference: https://docs.databricks.com/aws/en/dlt-ref/python-ref
- DQX framework docs: https://github.com/databrickslabs/dqx
│
├── conf/                   # ✅ YOUR CONFIGS (Edit these)
│   ├── source_bronze/
│   ├── bronze_silver/
│   ├── silver_gold/
│   └── environments/       # dev, staging, prod
│
├── quality/checks/         # ✅ YOUR QUALITY RULES (Edit these)
│   ├── source_bronze/
│   ├── bronze_silver/
│   └── silver_gold/
│
├── jobs/                   # ✅ YOUR JOB DEFINITIONS (Edit these)
│
├── templates/              # 📋 TEMPLATES (Copy these)
│   ├── conf/
│   ├── quality/checks/
│   ├── jobs/
│   └── notebooks/
│
├── tests/                  # ✅ FRAMEWORK TESTS (Complete)
│   ├── unit/
│   └── integration/
│
└── docs/                   # 📚 DOCUMENTATION
    ├── REUSABLE_FRAMEWORK.md
    ├── CLEAN_ARCHITECTURE.md
    └── CONFIG_DRIVEN_FRAMEWORK.md
```

## 🎯 What to Edit vs. What NOT to Edit

### 🔒 DO NOT EDIT (Framework Code)

```
❌ src/                    # Framework code - works for ALL projects
❌ notebooks/generic_*.py  # Generic notebooks - work via config
❌ tests/unit/pipelines/   # Framework tests - already complete
```

### ✅ DO EDIT (Project-Specific)

```
✅ conf/                   # Your pipeline configurations
✅ quality/checks/         # Your data quality rules
✅ jobs/                   # Your job definitions
✅ notebooks/              # Custom notebooks (if needed, with tests!)
```

## Testing

- Unit tests live under `tests/`.

### Your Tests (Only If You Create Custom Notebooks)

**Rule:** Custom notebooks MUST have test notebooks.

```bash
# If you create this:
notebooks/my_custom_pipeline.py

# You MUST create this:
notebooks/tests/test_my_custom_pipeline.py
```

**Verification:**
```bash
python scripts/verify_notebook_tests.py
```

**CI/CD will fail your PR if tests are missing!**

## IO Configuration Reference

- format: sink/source format (default: "delta")
- options: dict of spark options
- path or table: one required
- partitionBy: str | List[str]
- bucketBy: {"numBuckets": int, "columns": List[str], "sortBy": Optional[List[str]]}
- clusterBy: str | List[str]
- mode: append | overwrite | error | ignore
- external: bool (for tables with external locations)
- overwriteSchema: bool (with overwrite)
- merge: {"keys": ["id"], "whenMatchedUpdateAll": true, "whenNotMatchedInsertAll": true}

## Examples

### Batch with merge

```python
process_batch(
    spark,
    source={"path": "/data/landing/orders", "format": "json", "options": {"multiLine": True}},
    transform=lambda df: df.select("id", "amount", "ingest_ts"),
    target={
        "table": "silver.orders",
        "partitionBy": "ingest_date",
        "merge": {"keys": ["id"]}
    },
)
```

### Streaming with post-write checks

```python
query = process_streaming(
    spark,
    source={"table": "bronze.clicks"},
    transform=lambda df: df,
    target={"table": "silver.clicks"},
    checkpoint_location="/tmp/checkpoints/clicks",
    dq_post_write_checks="quality/checks/bronze_silver/clicks.yml",
)
```

## Deployment

### Local Development

```bash
# Install dependencies
uv sync --all-extras

# Run tests
pytest tests/unit/

# Verify notebook tests
python scripts/verify_notebook_tests.py
```

### Databricks Deployment

```bash
# Deploy bundle
databricks bundle deploy -t dev

# Run job
databricks bundle run my_pipeline -t dev
```

## CI/CD Validation

PRs are automatically validated for:

✅ **Test Coverage** - Custom notebooks have tests  
✅ **Config Validity** - JSON configs are valid  
✅ **src/ Purity** - No use-case specific code in framework  
✅ **Code Quality** - Minimum 70% test coverage  

## Documentation

| Document | Purpose |
|----------|---------|
| **[README.md](README.md)** | This file - Quick start |
| **[REUSABLE_FRAMEWORK.md](docs/REUSABLE_FRAMEWORK.md)** | How to use for new projects |
| **[CLEAN_ARCHITECTURE.md](docs/CLEAN_ARCHITECTURE.md)** | Architecture principles |
| **[CONFIG_DRIVEN_FRAMEWORK.md](docs/CONFIG_DRIVEN_FRAMEWORK.md)** | All transformations |
| **[DQX_INTEGRATION_GUIDE.md](docs/DQX_INTEGRATION_GUIDE.md)** | Data quality guide |
| **[templates/README.md](templates/README.md)** | Template usage guide |

## Benefits

- Simpler repository
- Enforced common patterns
- Clear IO and quality contracts

## 🔧 Extending the Framework

Need a transformation not in the library?

**Option 1:** Request it be added to framework (benefits everyone)  
**Option 2:** Create custom notebook with test (project-specific)

**Do NOT modify `src/` for project-specific needs!**

## ✨ Summary

**One Framework → Unlimited Projects**

```
🔒 src/ = Generic framework (never edit)
✅ conf/ = Your configs (edit these)
✅ quality/checks/ = Your rules (edit these)
🚀 Result = Your ETL solution
```

**Create unlimited ETL pipelines without ever editing framework code!**

## 📞 Support

- **Documentation:** See `docs/` directory
- **Templates:** See `templates/` directory
- **Issues:** Open GitHub issue
- **Questions:** See documentation first

---

**Version:** 0.2 (Minimal Toolkit)