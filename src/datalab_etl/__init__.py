"""Datalab ETL framework for Databricks bronze-silver-gold orchestration."""

from datalab_etl.common.io import read_dataset, write_dataset, start_stream_with_sink, target_identifier
from datalab_etl.common.processing import process_batch, process_streaming
from datalab_etl.common.session import get_spark
from datalab_etl.common.notebook import (
    has_dbutils,
    get_widget_value,
    load_config,
    load_quality_config,
    setup_notebook_config,
)

__all__ = [
    "__version__",
    "read_dataset",
    "write_dataset",
    "start_stream_with_sink",
    "target_identifier",
    "process_batch",
    "process_streaming",
    "get_spark",
    "has_dbutils",
    "get_widget_value",
    "load_config",
    "load_quality_config",
    "setup_notebook_config",
]

__version__ = "0.1.0"
