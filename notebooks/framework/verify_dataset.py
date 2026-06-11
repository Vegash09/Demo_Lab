# Databricks notebook source
# MAGIC %md
# MAGIC # Verify a framework dataset — no deploy needed
# MAGIC
# MAGIC Runs ONE dataset from `config/<domain>/` through the exact framework
# MAGIC path the pipeline uses (loader → transforms → dqx → valid/quarantine),
# MAGIC entirely in this notebook session. Edit YAML → re-run → see results.
# MAGIC
# MAGIC `use_sample_data: yes` feeds the bundled sample feed (rows violating
# MAGIC each check); `no` reads the live dev bronze table instead.

# COMMAND ----------

dbutils.widgets.text("config_dir", "")
dbutils.widgets.text("layer", "silver")
dbutils.widgets.text("dataset", "customers")
dbutils.widgets.dropdown("use_sample_data", "yes", ["yes", "no"])

# COMMAND ----------

import os

from pyspark.sql import functions as F

from datalab.framework import plan, run_dataset
from datalab.params import notebook_params

params = notebook_params(dbutils, ["config_dir", "layer", "dataset"])
CONFIG_DIR = params["config_dir"]
LAYER, DATASET = params["layer"], params["dataset"]
USE_SAMPLE = dbutils.widgets.get("use_sample_data") == "yes"

# COMMAND ----------

# MAGIC %md ## Validated plan (identical output to `make validate-configs` / CI)

# COMMAND ----------

print(plan(CONFIG_DIR))

# COMMAND ----------

# MAGIC %md ## Run the dataset

# COMMAND ----------

inputs = {}
if USE_SAMPLE:
    # The sample feed ships NEXT TO this notebook (workspace-files CWD ==
    # the notebook's directory), so the path survives repo restructures.
    sample_path = os.path.join(os.getcwd(), "sample_data", "customers_raw.json")
    sample = (
        spark.read.json(os.path.abspath(sample_path))
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.lit("sample_data/customers_raw.json"))
    )
    # Substitute the silver input by FQN: catalog/schemas come from the
    # cluster's pipeline conf in a deployed notebook, or set params= below.
    from datalab.config import fqn, pipeline_conf

    bronze_fqn = fqn(
        pipeline_conf(spark, "datalab.catalog"),
        pipeline_conf(spark, "datalab.bronze_schema"),
        "customers_raw",
    )
    inputs[bronze_fqn] = sample

res = run_dataset(spark, CONFIG_DIR, LAYER, DATASET, inputs=inputs)
if res.cdc_plan:
    print(res.cdc_plan)

# COMMAND ----------

# MAGIC %md ## Valid rows (what reaches the target)

# COMMAND ----------

display(res.valid_df)

# COMMAND ----------

# MAGIC %md ## Quarantine (dropped rows, with the dqx evidence)

# COMMAND ----------

if res.quarantine_df is not None:
    display(
        res.quarantine_df.select(
            "*", F.explode_outer("_errors").alias("_error")
        ).select("customer_id", "customer_name", "_error.name", "_error.message")
    )
else:
    print("no quarantine configured for this dataset")

# COMMAND ----------

# MAGIC %md ## Warnings that flowed through to the target

# COMMAND ----------

if res.checked_df is not None:
    display(
        res.checked_df.where(F.col("_warnings").isNotNull()).select(
            "customer_id", "customer_name", F.explode("_warnings").alias("w")
        ).select("customer_id", "customer_name", "w.name", "w.message")
    )
