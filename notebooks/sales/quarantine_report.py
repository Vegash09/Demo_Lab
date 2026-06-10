# Databricks notebook source
# MAGIC %md
# MAGIC # Sales quarantine triage report
# MAGIC
# MAGIC Notebook lane: human-gated, on-demand only (the job has **no trigger**).
# MAGIC Run with `databricks bundle run sales_quarantine_report -t dev`, read the
# MAGIC per-rule breakdown and the sample rows, then decide on repairs. Repaired
# MAGIC data re-enters through the landing volume so it passes the pipeline's
# MAGIC quality gates — this notebook never writes SDP-owned tables.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("silver_schema", "")

# COMMAND ----------

from pyspark.sql import functions as F

from datalab.config import fqn
from datalab.params import notebook_params
from datalab.transforms.sales import QUARANTINE_RULES, WARN_RULES, quarantine_breakdown

params = notebook_params(dbutils, ["catalog", "silver_schema"])

QUARANTINE_TABLE = fqn(params["catalog"], params["silver_schema"], "customers_quarantine")
# Owned by THIS notebook (single-writer invariant): dated report snapshots.
REPORT_TABLE = fqn(params["catalog"], params["silver_schema"], "customers_quarantine_report")

# COMMAND ----------

# MAGIC %md ## Violations per rule

# COMMAND ----------

quarantined = spark.read.table(QUARANTINE_TABLE)
breakdown = quarantine_breakdown(quarantined, QUARANTINE_RULES | WARN_RULES)
display(breakdown)

# COMMAND ----------

# MAGIC %md ## Most recent quarantined rows

# COMMAND ----------

display(quarantined.orderBy(F.col("_ingest_ts").desc()).limit(50))

# COMMAND ----------

# MAGIC %md ## Snapshot the breakdown for trend triage

# COMMAND ----------

(
    breakdown.withColumn("report_ts", F.current_timestamp())
    .write.mode("append")
    .saveAsTable(REPORT_TABLE)
)
