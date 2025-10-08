"""Reusable helpers for reading and writing Spark data sources declared in pipeline configuration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.streaming import StreamingQuery
from datalab_etl.common.session import (
    is_databricks_runtime,
    is_databricks_connect_available,
    is_databricks_connect_configured,
)


def _ensure_path(path_value: str) -> str:
    path = Path(path_value)
    return path.expanduser().as_posix() if path_value.startswith("~") else path_value


def read_dataset(spark: SparkSession, source_cfg: Dict[str, Any], *, streaming: bool = False) -> DataFrame:
    """Load a dataset from a path or table based on ``source_cfg``.

    Supported keys in ``source_cfg``:
    - format: data source format (default: "delta")
    - options: dict of read options
    - path: filesystem path (for external data)
    - table: catalog table name (managed or external table)
    """

    fmt = source_cfg.get("format", "delta")
    options = source_cfg.get("options", {})
    path = source_cfg.get("path")
    table = source_cfg.get("table")

    if not path and not table:
        raise ValueError("Source configuration requires either 'path' or 'table'.")

    if streaming:
        reader = spark.readStream.format(fmt).options(**options)
        if table:
            return spark.readStream.table(table)
        return reader.load(_ensure_path(path))

    reader = spark.read.format(fmt).options(**options)
    if table:
        return spark.table(table)
    return reader.load(_ensure_path(path))


def write_dataset(df: DataFrame, target_cfg: Dict[str, Any]) -> None:
    """Persist a batch :class:`DataFrame` according to the target configuration.

    Supported keys in ``target_cfg``:
    - format: sink format (default: "delta")
    - mode: "append" | "overwrite" | "upsert" (default: "append")
    - options: dict of write options
    - table: catalog table name
    - path: filesystem path for files or for external table location
    - external: bool, when writing to a table, treat ``path`` as external location
    - partitionBy: str | List[str]
    - clusterBy: str | List[str] (best-effort clustering via repartition + sortWithinPartitions)
    - merge: dict when mode == "upsert". Supports:
        - keys: List[str] (join keys) or condition: str (SQL merge condition using aliases t/s)
        - whenMatchedUpdateAll: bool (default True)
        - whenNotMatchedInsertAll: bool (default True)
        - delete_when: str (SQL condition for whenMatchedDelete)
        - cdf: { operationColumn: str = "_change_type", deleteValues: List[str] = ["delete"] }
    """

    fmt = target_cfg.get("format", "delta")
    mode = target_cfg.get("mode", "append")
    options = target_cfg.get("options", {})
    path = target_cfg.get("path")
    table = target_cfg.get("table")
    external = bool(target_cfg.get("external", False))

    # Apply distribution hints prior to writing (only partitionBy and clusterBy)
    df = _apply_distribution_hints(
        df,
        partition_cols=_as_list(target_cfg.get("partitionBy")),
        cluster_cols=_as_list(target_cfg.get("clusterBy")),
    )

    # Enforce supported modes
    normalized_mode = str(mode).lower()
    if normalized_mode not in {"append", "overwrite", "upsert"}:
        raise ValueError("Unsupported write mode. Use one of: append, overwrite, upsert.")

    # Compute local path fallback for non-Databricks/Connect dev
    use_path_fallback, fallback_path = _maybe_local_path_fallback(table, path)

    # If we are in upsert mode, prepare effective cfg (with fallback path if needed)
    effective_cfg = dict(target_cfg)
    if use_path_fallback and table and not path:
        effective_cfg["path"] = _fallback_table_path(table, fallback_path)

    # Handle Delta upsert (merge) mode
    if normalized_mode == "upsert":
        _delta_merge_upsert(df, effective_cfg)
        return

    writer = df.write.format(fmt).mode(mode).options(**options)

    # Partitioning
    partition_cols = _as_list(target_cfg.get("partitionBy"))
    if partition_cols:
        writer = writer.partitionBy(*partition_cols)

    if table and not use_path_fallback:
        # External table support by providing path option
        if external and path:
            writer = writer.option("path", _ensure_path(path))
        writer.saveAsTable(table)
        return

    # Path-based writes (explicit path or local fallback)
    if path:
        writer.save(_ensure_path(path))
        return
    if table and use_path_fallback:
        writer.save(_fallback_table_path(table, fallback_path))
        return

    raise ValueError("Target configuration requires either 'path' or 'table'.")


def start_stream_with_sink(df: DataFrame, target_cfg: Dict[str, Any], checkpoint_location: str,
                           output_mode: str, trigger: Dict[str, Any] | None = None) -> StreamingQuery:
    """Start a streaming query that writes each micro-batch using batch semantics."""

    writer = (
        df.writeStream
        .foreachBatch(_batch_writer(target_cfg))
        .outputMode(output_mode)
        .option("checkpointLocation", _ensure_path(checkpoint_location))
    )

    if trigger:
        if trigger.get("availableNow"):
            writer = writer.trigger(availableNow=True)
        elif trigger.get("processingTime"):
            writer = writer.trigger(processingTime=trigger["processingTime"])

    return writer.start()


def _batch_writer(target_cfg: Dict[str, Any]):
    fmt = target_cfg.get("format", "delta")
    mode = target_cfg.get("mode", "append")
    options = target_cfg.get("options", {})
    path = target_cfg.get("path")
    table = target_cfg.get("table")

    if not path and not table:
        raise ValueError("Target configuration requires either 'path' or 'table'.")

    def _write(batch_df, _batch_id):
        # Apply same distribution hints and merge semantics for micro-batches
        effective_cfg = dict(target_cfg)
        mode = str(effective_cfg.get("mode", "append")).lower()
        if mode == "upsert" or effective_cfg.get("merge"):
            _delta_merge_upsert(batch_df, effective_cfg)
            return

        writer = batch_df.write.format(fmt).mode(mode).options(**options)

        partition_cols = _as_list(effective_cfg.get("partitionBy"))
        if partition_cols:
            writer = writer.partitionBy(*partition_cols)

        if table:
            if effective_cfg.get("external") and path:
                writer = writer.option("path", _ensure_path(path))
            writer.saveAsTable(table)
        else:
            writer.save(_ensure_path(path))

    return _write


def target_identifier(target_cfg: Dict[str, Any]) -> str:
    """Return the identifier (table or path) used when referencing the sink in downstream tooling."""

    table = target_cfg.get("table")
    path = target_cfg.get("path")
    if table:
        # If running locally without Connect, resolve to fallback path for downstream tools
        use_path_fallback, base = _maybe_local_path_fallback(table, path)
        if use_path_fallback and not path:
            return _fallback_table_path(table, base)
        return table
    if path:
        return _ensure_path(target_cfg["path"])
    raise ValueError("Target configuration requires either 'path' or 'table'.")


def _apply_distribution_hints(
    df: DataFrame,
    *,
    partition_cols: List[str] | None,
    cluster_cols: List[str] | None,
) -> DataFrame:
    """Apply non-persistent distribution hints (repartition/sort) prior to writing.

    - partition_cols: used for repartitioning to match desired partitioning.
    - cluster_cols: best-effort clustering using repartition and in-partition ordering.
    """
    result = df

    # Repartition to align with partitioning scheme if provided
    if partition_cols:
        result = result.repartition(*[result[c] for c in partition_cols])

    # Best-effort clustering: repartition by cluster columns and sort within partitions
    if cluster_cols:
        result = result.repartition(*[result[c] for c in cluster_cols]).sortWithinPartitions(*cluster_cols)

    return result


def _as_list(value: Any | None) -> List[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(v) for v in value]
    return None


def _delta_merge_upsert(df: DataFrame, target_cfg: Dict[str, Any]) -> None:
    """Perform a Delta merge (upsert) based on keys/condition provided in target_cfg['merge']."""
    merge_cfg = target_cfg.get("merge") or {}
    keys = _as_list(merge_cfg.get("keys")) or []
    condition = merge_cfg.get("condition")
    update_all = bool(merge_cfg.get("whenMatchedUpdateAll", True))
    insert_all = bool(merge_cfg.get("whenNotMatchedInsertAll", True))

    # Determine target identifier
    table = target_cfg.get("table")
    path = target_cfg.get("path")
    spark = df.sparkSession
    options = target_cfg.get("options", {})

    try:
        from delta.tables import DeltaTable  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Delta Lake is required for merge operations. Install delta-spark or run on Databricks.") from exc

    if not table and not path:
        raise ValueError("Delta merge requires 'table' or 'path' in target configuration.")

    # Build merge target
    fmt = str(target_cfg.get("format", "delta"))
    if table and not (not is_databricks_runtime() and not is_databricks_connect_configured()):
        # Real catalog table on Databricks or when Connect is configured
        try:
            target = DeltaTable.forName(spark, table)
        except Exception:
            empty_df = df.limit(0)
            writer = empty_df.write.format(fmt)
            partition_cols = _as_list(target_cfg.get("partitionBy"))
            if partition_cols:
                writer = writer.partitionBy(*partition_cols)
            if options:
                writer = writer.options(**options)
            writer.mode("overwrite").saveAsTable(table)
            target = DeltaTable.forName(spark, table)
    else:
        # Local path-based target
        resolved_path = _ensure_path(path) if path else _fallback_table_path(table or "table", _local_warehouse_base())
        # Ensure Delta table exists at path (create empty table if missing)
        try:
            exists = False
            try:
                from delta.tables import DeltaTable as _DT  # type: ignore
                exists = _DT.isDeltaTable(spark, resolved_path)  # type: ignore[attr-defined]
            except Exception:
                exists = False
            if not exists:
                df.limit(0).write.format(fmt).mode("overwrite").save(resolved_path)
        except Exception:
            # Best-effort create; continue to forPath which may still fail if misconfigured
            pass
        target = DeltaTable.forPath(spark, resolved_path)

    # Construct merge condition
    if not condition:
        if not keys:
            raise ValueError("Delta merge requires either 'merge.condition' or 'merge.keys'.")
        condition = " AND ".join([f"t.{k} = s.{k}" for k in keys])

    merge_builder = target.alias("t").merge(df.alias("s"), condition)

    # Optional delete strategy (e.g., when CDF indicates deletes)
    delete_condition = _resolve_delete_condition(df, merge_cfg)
    if delete_condition:
        merge_builder = merge_builder.whenMatchedDelete(condition=delete_condition)

    if update_all:
        merge_builder = merge_builder.whenMatchedUpdateAll()
    if insert_all:
        merge_builder = merge_builder.whenNotMatchedInsertAll()

    merge_builder.execute()


def _maybe_local_path_fallback(table: str | None, path: str | None) -> tuple[bool, str]:
    """Return (use_fallback, base_dir) for local development when a table sink is configured.

    Fallback is used when NOT on Databricks runtime and NOT configured for Databricks Connect.
    """
    if path:
        return False, ""
    if not table:
        return False, ""
    try:
        if is_databricks_runtime():
            return False, ""
        if is_databricks_connect_available() and is_databricks_connect_configured():
            return False, ""
    except Exception:
        pass
    return True, _local_warehouse_base()


def _local_warehouse_base() -> str:
    base = os.getenv("DATALAB_LOCAL_WAREHOUSE")
    if base:
        return base
    return (Path.cwd() / "tmp" / "local_warehouse").as_posix()


def _fallback_table_path(table: str, base_dir: str) -> str:
    sanitized = table.replace("`", "").replace(".", "/")
    return (Path(base_dir) / sanitized).as_posix()


def _resolve_delete_condition(df: DataFrame, merge_cfg: Dict[str, Any]) -> str | None:
    """Return a SQL condition for whenMatchedDelete based on merge config.

    Supports either an explicit SQL string via "delete_when", or a CDF-based
    config under "cdf": { operationColumn: str, deleteValues: [..] }.
    If merge_cfg["delete"] is True and a common CDF column exists, defaults to
    deleting when lower(s._change_type) in ('delete').
    """
    # Explicit condition
    if isinstance(merge_cfg.get("delete_when"), str):
        return merge_cfg["delete_when"]

    # CDF config
    cdf = merge_cfg.get("cdf")
    if isinstance(cdf, dict):
        op_col = str(cdf.get("operationColumn", "_change_type"))
        delete_values = [str(v).lower() for v in (cdf.get("deleteValues") or ["delete"])]
        if op_col in df.columns:
            in_list = ", ".join([f"'{v}'" for v in delete_values])
            return f"lower(s.`{op_col}`) IN ({in_list})"

    # Heuristic when delete=True and a common op column exists
    if merge_cfg.get("delete") is True:
        for candidate in ("_change_type", "op", "operation"):  # common CDC/CDF columns
            if candidate in df.columns:
                return f"lower(s.`{candidate}`) IN ('delete')"

    return None
