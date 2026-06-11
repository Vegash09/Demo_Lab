# Databricks notebook source
# MAGIC %md
# MAGIC # Customer-sales quarantine triage report
# MAGIC
# MAGIC Notebook lane: human-gated, on-demand only (the job has **no trigger**).
# MAGIC Run with `databricks bundle run customer_sales_quarantine_report -t dev`, read the
# MAGIC per-rule breakdown and the dqx evidence, then decide on repairs. Repaired
# MAGIC data re-enters through the landing volume so it passes the pipeline's
# MAGIC quality gates — this notebook never writes SDP-owned tables.
# MAGIC
# MAGIC The quarantine table carries databrickslabs/dqx result columns
# MAGIC (`_errors` / `_warnings` struct arrays) written by the framework.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("silver_schema", "")

# COMMAND ----------

from pyspark.sql import functions as F

from datalab.config import fqn
from datalab.framework.dq import summarize_dq_results
from datalab.params import notebook_params

params = notebook_params(dbutils, ["catalog", "silver_schema"])

QUARANTINE_TABLE = fqn(params["catalog"], params["silver_schema"], "customers_quarantine")
# Owned by THIS notebook (single-writer invariant): dated report snapshots.
REPORT_TABLE = fqn(params["catalog"], params["silver_schema"], "customers_quarantine_report")

# COMMAND ----------

# MAGIC %md ## Violations per rule

# COMMAND ----------

quarantined = spark.read.table(QUARANTINE_TABLE)
breakdown = summarize_dq_results(quarantined, "_errors", "_warnings")
display(breakdown)

# COMMAND ----------

# MAGIC %md ## Most recent quarantined rows, with the failing rule evidence

# COMMAND ----------

display(
    quarantined.orderBy(F.col("_ingest_ts").desc())
    .limit(50)
    .select("*", F.explode_outer("_errors").alias("_error"))
    .select(
        "customer_id",
        "customer_name",
        "email",
        "_ingest_ts",
        F.col("_error.name").alias("failed_rule"),
        F.col("_error.message").alias("evidence"),
    )
)

# COMMAND ----------

# MAGIC %md ## Snapshot the breakdown for trend triage

# COMMAND ----------

(
    breakdown.withColumn("report_ts", F.current_timestamp())
    .write.mode("append")
    .saveAsTable(REPORT_TABLE)
)
