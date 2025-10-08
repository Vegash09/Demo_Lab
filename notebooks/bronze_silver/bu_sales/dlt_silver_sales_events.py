import dlt
from pyspark.sql.functions import col
from pyspark.sql.types import StructType, StructField, StringType, TimestampType, IntegerType, DoubleType

from datalab_etl.common.session import get_spark


schema = StructType([
    StructField("id", StringType()),
    StructField("event_ts", TimestampType()),
    StructField("payload", StructType([
        StructField("device_id", IntegerType()),
        StructField("temp_c", DoubleType()),
        StructField("humidity", DoubleType())
    ]))
])

CATALOG = "0__silver"
SCHEMA  = "sap"
VOLUME  = "dlt_sink"
SRC_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/source/cleaned_events_json"


# DLT dataset definition: return a streaming DataFrame only (no writes)
@dlt.table(name="0__silver.sap.cleaned_events")
def cleaned_events():
    # spark is provided by the DLT engine, but we guard with a local session for static analysis
    try:
        spark  # type: ignore[name-defined]
    except NameError:  # pragma: no cover
        spark = get_spark(app_name="datalab-dlt-silver-sales-events")

    return (
        spark.readStream.format("cloudFiles")
          .option("cloudFiles.format", "json")
          .schema(schema)
          .load(SRC_PATH)
    )


