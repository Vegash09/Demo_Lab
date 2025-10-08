"""Common processing helpers for layer-to-layer transitions.

These functions enforce a standard pattern for moving data between layers
(e.g., source -> bronze, bronze -> silver, silver -> gold) using the shared
IO utilities and optional DQX integration.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.streaming import StreamingQuery

from datalab_etl.common.io import read_dataset, target_identifier, write_dataset
from datalab_etl.quality.simple_dq import SimpleDQ


TransformFn = Callable[[DataFrame], DataFrame]


def process_batch(
    spark: SparkSession,
    *,
    source: Dict[str, Any],
    transform: TransformFn,
    target: Dict[str, Any],
    dq_config: Dict[str, Any] | None = None,
    dq_runner: Any | None = None,  # deprecated
    dq_in_transit_checks: List[Dict[str, Any]] | str | None = None,  # deprecated
    dq_post_write_checks: str | None = None,  # deprecated
    dq_run_name: str | None = None,  # deprecated
) -> DataFrame:
    """Run a single batch step from source to target using a transform function.

    Parameters
    ----------
    spark: SparkSession
        Active session
    source: dict
        Read configuration (see ``read_dataset``)
    transform: Callable[[DataFrame], DataFrame]
        User transformation from input to output schema
    target: dict
        Write configuration (see ``write_dataset``)
    dq_config: dict | None
        New preferred DQ config. When provided, the framework will:
          - load checks from ``checks_table`` or ``checks`` (path/list/dict)
          - apply checks in-transit and split valid/invalid
          - write quarantined rows to ``quarantine_table``/``quarantine_path`` if set
        Deprecated parameters (``dq_runner`` etc.) are still supported but
        ignored when ``dq_config`` is supplied.
    """

    # Read
    input_df = read_dataset(spark, source, streaming=False)

    # Transform
    transformed_df = transform(input_df)

    # In-transit DQ (new simple flow preferred)
    if dq_config:
        dq = SimpleDQ(spark, dq_config)
        checks = dq.resolve_checks()
        valid_df, invalid_df = dq.apply_and_split(transformed_df, checks)
        # Write quarantine if configured
        dq.write_quarantine(invalid_df)
        candidate_df = valid_df
    elif dq_runner and dq_in_transit_checks is not None:
        # Backward compatibility path
        candidate_df = dq_runner.check_in_transit(
            data=transformed_df,
            checks=dq_in_transit_checks,
            run_name=dq_run_name or "batch",
            target_identifier=target_identifier(target),
        )
    else:
        candidate_df = transformed_df

    # Write
    write_dataset(candidate_df, target)

    # Post-write DQ
    if not dq_config and dq_runner and dq_post_write_checks:
        run_name = dq_run_name or "batch"
        dq_runner.run_checks(
            run_name=run_name,
            checks=dq_post_write_checks,
            input_location=target_identifier(target),
            input_format=target.get("format", "delta"),
            is_streaming=False,
        )

    return candidate_df


def process_streaming(
    spark: SparkSession,
    *,
    source: Dict[str, Any],
    transform: TransformFn,
    target: Dict[str, Any],
    checkpoint_location: str,
    output_mode: str = "append",
    trigger: Dict[str, Any] | None = None,
    dq_config: Dict[str, Any] | None = None,
    dq_runner: Any | None = None,  # deprecated
    dq_in_transit_checks: List[Dict[str, Any]] | str | None = None,  # deprecated
    dq_post_write_checks: str | None = None,  # deprecated
    dq_run_name: str | None = None,  # deprecated
) -> StreamingQuery:
    """Run a streaming step using foreachBatch to apply standard write and DQ.

    Applies optional in-transit checks prior to writing each micro-batch and
    optional at-rest checks after each micro-batch is committed.
    """

    stream_df = read_dataset(spark, source, streaming=True)
    transformed_stream = transform(stream_df)

    def _process_batch(batch_df: DataFrame, batch_id: int) -> None:
        candidate_df = batch_df
        if dq_config:
            dq = SimpleDQ(spark, dq_config)
            checks = dq.resolve_checks()
            valid_df, invalid_df = dq.apply_and_split(candidate_df, checks)
            dq.write_quarantine(invalid_df)
            candidate_df = valid_df
        elif dq_runner and dq_in_transit_checks is not None:
            candidate_df = dq_runner.check_in_transit(
                data=candidate_df,
                checks=dq_in_transit_checks,
                run_name=dq_run_name or f"stream_{batch_id}",
                target_identifier=target_identifier(target),
            )

        write_dataset(candidate_df, target)

        if not dq_config and dq_runner and dq_post_write_checks:
            run_name = dq_run_name or f"stream_{batch_id}"
            dq_runner.run_checks(
                run_name=run_name,
                checks=dq_post_write_checks,
                input_location=target_identifier(target),
                input_format=target.get("format", "delta"),
                is_streaming=True,
            )

    writer = (
        transformed_stream.writeStream
        .foreachBatch(_process_batch)
        .outputMode(output_mode)
        .option("checkpointLocation", checkpoint_location)
    )

    if trigger:
        if trigger.get("availableNow"):
            writer = writer.trigger(availableNow=True)
        elif trigger.get("processingTime"):
            writer = writer.trigger(processingTime=trigger["processingTime"])

    return writer.start()
