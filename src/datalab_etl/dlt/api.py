"""Helpers for building DLT (Lakeflow Declarative Pipelines) datasets.

Follow DLT guidance: dataset-defining functions should only return a DataFrame
and must not perform writes or side effects.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from pyspark.sql import DataFrame, SparkSession

from datalab_etl.common.io import read_dataset


TransformFn = Callable[[DataFrame], DataFrame]


def dlt_stream_transform(spark: SparkSession, *, source: Dict[str, Any], transform: TransformFn) -> DataFrame:
    """Read a streaming source from config and apply the provided transform.

    This function is safe to call inside DLT dataset definitions as it returns a
    DataFrame and does not perform any writes.
    """
    stream_df = read_dataset(spark, source, streaming=True)
    return transform(stream_df)


