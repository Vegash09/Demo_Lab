# Databricks notebook source
from pyspark.sql import functions as F

from datalab_etl import process_batch
from datalab_etl.common.session import get_spark
from datalab_etl.quality.dqx_runner import DqxRunner
import json

# spark = get_spark(app_name="datalab-bu-sales-bronze-to-silver")
spark = get_spark(databricks_profile="dev_diggi")

# dbutils.widgets.text("config_path", "", "Config Path")
# config_path = dbutils.widgets.get("config_path")
config_path = "/Users/Nivethan1/datalab/config/bronze_silver/bu_sales/bronze_to_silver.json"


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

with open(config_path) as f:
    cfg = json.load(f)

quality_cfg = cfg.get("quality", {}) or {}

dq = DqxRunner(spark, quality_cfg, enabled=bool(quality_cfg)) if quality_cfg else None

process_batch(
    spark,
    source=cfg["source"],
    transform=transform_to_silver,
    target=cfg["target"],
    dq_runner=dq,
    dq_in_transit_checks=quality_cfg.get("checks"),
    dq_post_write_checks=quality_cfg.get("checks"),
    dq_run_name="sales_bronze_to_silver",
)
# COMMAND ----------
