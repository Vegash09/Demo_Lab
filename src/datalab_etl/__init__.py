"""Datalab ETL framework for Databricks bronze-silver-gold orchestration."""

from datalab_etl.common.io import read_dataset, write_dataset, start_stream_with_sink, target_identifier
from datalab_etl.common.processing import process_batch, process_streaming

__all__ = [
    "__version__",
    "read_dataset",
    "write_dataset",
    "start_stream_with_sink",
    "target_identifier",
    "process_batch",
    "process_streaming",
]

__version__ = "0.1.0"
