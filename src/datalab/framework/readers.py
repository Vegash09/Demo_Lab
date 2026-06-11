"""Reader adapters: SourceSpec → DataFrame, honoring context substitution."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from datalab.framework.context import ResolveContext
from datalab.framework.errors import ConfigError
from datalab.framework.models import (
    CloudFilesSource,
    ColumnSpec,
    DatasetSpec,
    FileSource,
    KafkaSource,
    LayerConfig,
    ReferenceSource,
    SnapshotFunctionSource,
    SourceSpec,
    TableSource,
    TransformStep,
    ViewSource,
)
from datalab.framework.registry import resolve_transform


def read_source(
    spark: SparkSession, src: SourceSpec, layer: LayerConfig, ctx: ResolveContext
) -> DataFrame:
    if isinstance(src, CloudFilesSource):
        path = ctx.resolve(src.path_conf)
        if path in ctx.inputs:
            df = ctx.inputs[path]
        elif ctx.force_batch:
            reader = spark.read.format(src.format).options(**src.options)
            if src.reader_schema:
                reader = reader.schema(src.reader_schema)
            df = reader.load(path)
        else:
            reader = (
                spark.readStream.format("cloudFiles")
                .option("cloudFiles.format", src.format)
                .options(**src.options)
            )
            if src.schema_hints:
                reader = reader.option("cloudFiles.schemaHints", src.schema_hints)
            if src.reader_schema:
                reader = reader.schema(src.reader_schema)
            df = reader.load(path)
        if src.add_lineage:
            df = resolve_transform("framework.add_lineage")(df)
        return df

    if isinstance(src, FileSource):
        path = ctx.resolve(src.path_conf)
        if path in ctx.inputs:
            return ctx.inputs[path]
        reader = spark.read.format(src.format).options(**src.options)
        if src.reader_schema:
            reader = reader.schema(src.reader_schema)
        return reader.load(path)

    if isinstance(src, TableSource):
        table = ctx.source_fqn(src, layer)
        if table in ctx.inputs:
            return ctx.inputs[table]
        if src.as_stream and not ctx.force_batch:
            return spark.readStream.options(**src.options).table(table)
        return spark.read.options(**src.options).table(table)

    if isinstance(src, ViewSource):
        if src.name in ctx.inputs:
            return ctx.inputs[src.name]
        if src.as_stream and not ctx.force_batch:
            return spark.readStream.table(src.name)
        return spark.read.table(src.name)

    if isinstance(src, KafkaSource):
        key = f"kafka:{src.topic or src.subscribe_pattern}"
        if key in ctx.inputs:
            return ctx.inputs[key]
        reader = spark.readStream if not ctx.force_batch else spark.read
        configured = (
            reader.format("kafka")
            .option("kafka.bootstrap.servers", ctx.resolve(src.bootstrap_servers_conf))
            .options(**src.options)
        )
        if src.topic:
            configured = configured.option("subscribe", src.topic)
        else:
            configured = configured.option("subscribePattern", src.subscribe_pattern)
        return configured.load()

    if isinstance(src, SnapshotFunctionSource):
        raise ConfigError(
            f"snapshot_function source {src.function!r} has no readable stream/batch "
            "frame — it is consumed by the cdc_from_snapshot flow directly. Use "
            "run_dataset to preview its first snapshot."
        )

    raise TypeError(f"unhandled source kind: {src!r}")  # pragma: no cover


def read_references(
    spark: SparkSession,
    references: dict[str, ReferenceSource],
    layer: LayerConfig,
    ctx: ResolveContext,
) -> dict[str, DataFrame] | None:
    """Batch-read reference tables for dqx ``ref_dfs``."""
    if not references:
        return None
    out: dict[str, DataFrame] = {}
    for key, ref in references.items():
        table = ctx.source_fqn(ref, layer)
        out[key] = ctx.inputs[table] if table in ctx.inputs else spark.read.table(table)
    return out


def project_columns(df: DataFrame, columns: list[ColumnSpec]) -> DataFrame:
    """The source→target column mapping from the artifact's ``columns:``.

    Renames, reorders, and casts — casts are ANSI-safe (``try_cast``) so a
    malformed value becomes NULL for the dqx rules to flag instead of failing
    the stream."""
    if not columns:
        return df
    projected = []
    for col in columns:
        expr = F.col(col.source_name)
        if col.type:
            expr = expr.try_cast(col.type)
        projected.append(expr.alias(col.name))
    return df.select(*projected)


def apply_transforms(df: DataFrame, steps: list[TransformStep]) -> DataFrame:
    for step in steps:
        df = resolve_transform(step.function)(df, **step.args)
    return df


def prepare(df: DataFrame, ds: DatasetSpec) -> DataFrame:
    """Column mapping first (target names/types), then the transform steps
    (which therefore operate on TARGET column names)."""
    return apply_transforms(project_columns(df, ds.columns), ds.transform)
