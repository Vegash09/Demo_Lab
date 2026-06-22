"""customer_sales_etl pipeline entrypoint — the entire domain is config-driven.

Datasets, transforms and dqx quality rules live in the domain's config dir
(``projects/customer_sales/config/customer_sales/`` here; the bundle supplies
the deployed path as ``datalab.config_dir``); the framework validates them and
registers every LDP dataset. Add a table by editing YAML — see
docs/FRAMEWORK.md.
"""

from pyspark.sql import SparkSession

from datalab.config import pipeline_conf
from datalab.framework import generate

# The active session is the SDP-runtime session on Databricks and the session the
# OSS `spark-pipelines` CLI creates locally — one entrypoint, every profile
# (datalab.profile selects the Databricks vs local graph; see docs/FRAMEWORK.md).
spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
generate(spark, pipeline_conf(spark, "datalab.config_dir"))
