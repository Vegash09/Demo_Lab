# Databricks notebook source
from pyspark.sql import functions as F

from datalab_etl import process_batch, get_spark, get_widget_value, load_config, has_dbutils

# COMMAND ----------

# Get SparkSession (Databricks Connect for local, runtime session in Databricks)
try:
    spark  # type: ignore[name-defined]  # Check if Databricks provides spark
except NameError:
    # Local development: use Databricks Connect
    spark = get_spark(databricks_profile="dev_diggi")

# COMMAND ----------

config_path = get_widget_value(
    name="config_path",
    default="/Users/Nivethan1/datalab/config/bronze_silver/bu_sales/bronze_to_silver.json",
    label="Config Path"
)

# COMMAND ----------

cfg = load_config(config_path)
dq_cfg = cfg.get("quality", {})

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

if has_dbutils() or cfg:
    process_batch(
        spark,
        source=cfg.get("source", {}),
        transform=transform_to_silver,
        target=cfg.get("target", {}),
        dq_config=dq_cfg
    )

# COMMAND ----------
