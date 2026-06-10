"""Bronze: incremental Auto Loader ingest of the raw customer feed.

Raw JSON files land in a Unity Catalog volume (``datalab.sales_landing_path``)
and are ingested exactly-once into the bronze streaming table with lineage
columns. No business transformation happens here — bronze preserves the source.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

from datalab.config import fqn, pipeline_conf

CATALOG = pipeline_conf(spark, "datalab.catalog")  # noqa: F821
BRONZE_SCHEMA = pipeline_conf(spark, "datalab.bronze_schema")  # noqa: F821
LANDING_PATH = pipeline_conf(spark, "datalab.sales_landing_path")  # noqa: F821


@dp.table(
    name=fqn(CATALOG, BRONZE_SCHEMA, "customers_raw"),
    comment="Raw customer feed ingested incrementally from the landing volume (Auto Loader).",
    table_properties={"datalab.layer": "bronze"},
)
def customers_raw():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .load(LANDING_PATH)
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
    )
