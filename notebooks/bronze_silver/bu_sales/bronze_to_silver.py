# Databricks notebook source
from pyspark.sql import functions as F

from datalab_etl import process_batch
import json

# COMMAND ----------

try:  # Databricks provides ``spark`` automatically
    spark  # type: ignore[name-defined]
except NameError:  # pragma: no cover - local unit testing fallback
    from datalab_etl.common.session import get_spark
    if globals().get("spark") is None:
        spark = get_spark(force_local=True)

# COMMAND ----------

def _has_dbutils() -> bool:
    try:
        # DBUtils class may be importable locally, but the global 'dbutils' handle
        # exists only on Databricks. Require the global to be present and not None.
        from pyspark.dbutils import DBUtils  # type: ignore  # noqa: F401
        return bool(globals().get("dbutils") is not None)
    except Exception:
        return False

if _has_dbutils():
    dbutils.widgets.text("config_path", "", "Config Path")
    dbutils.widgets.text("dq_config_path", "", "DQ Config Path")
    config_path = dbutils.widgets.get("config_path")
    dq_config_path = dbutils.widgets.get("dq_config_path")
else:
    config_path = ""
    dq_config_path = ""

# COMMAND ----------

def transform_to_silver(df):
    # Pass through customer fields and ensure signup_date is a date for partitioning
    return (
        df.select(
            "customer_id",
            "customer_name",
            "age",
            "city",
            "signup_date",
            "email"
        )
        .withColumn("signup_date", F.to_date("signup_date"))
    )

# COMMAND ----------

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
else:
    base_quality = cfg.get("quality")
    if isinstance(base_quality, dict):
        quality_cfg = base_quality.copy()

# COMMAND ----------

def _run_main():
    process_batch(
        spark,
        source=cfg["source"],
        transform=transform_to_silver,
        target=cfg["target"],
        dq_config=quality_cfg or {
            "checks_table": "customer_sales.silver.quality_checks",
            "quarantine_table": "customer_sales._silver.customer_quarantine",
        },
    )

if _has_dbutils():
    _run_main()
# COMMAND ----------
