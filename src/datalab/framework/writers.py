"""Writer adapters: register one dataset's full LDP graph from its spec.

Per dataset the generator emits an input-view chain (the dlt-meta pattern —
one read fans out to every sink, which is what lets DQX compose with AUTO CDC):

    <name>__input                     source + transforms
    <name>__checked   (if quality)    + dqx _errors/_warnings
    <name>__valid     (if quality)    error rows dropped, result cols stripped
    target writer                     streaming table / CDC / MV / view / sink
    <quarantine>      (if configured) rows the target rejected
    <metrics> MV      (if enabled)    per-rule violation counts

CONVENTION (load-bearing): every generated closure binds loop state through
DEFAULT ARGUMENTS — never free variables — or each dataset would silently
read the last loop iteration's spec (the classic late-binding bug). Reviewers
must reject any free closure over loop variables in this file.
"""

from __future__ import annotations

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from datalab.framework import compat
from datalab.framework.context import ResolveContext
from datalab.framework.dq import DQAdapter, summarize_dq_results
from datalab.framework.models import (
    DatasetSpec,
    DeltaSinkTarget,
    LayerConfig,
    MaterializedViewTarget,
    StreamingTableTarget,
    TemporaryViewTarget,
)
from datalab.framework.readers import apply_transforms, read_source


def _read_view(spark: SparkSession, view: str, *, streaming: bool) -> DataFrame:
    return spark.readStream.table(view) if streaming else spark.read.table(view)


def register_dataset(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    dq: DQAdapter | None,
) -> None:
    streaming = ds.is_streaming
    annotate_only = isinstance(ds.target, TemporaryViewTarget)
    input_view = f"{ds.name}__input"

    def _input(spark=spark, ds=ds, layer=layer, ctx=ctx) -> DataFrame:
        return apply_transforms(read_source(spark, ds.source, layer, ctx), ds.transform)

    dp.temporary_view(_input, name=input_view)

    upstream = input_view
    if ds.quality:
        assert dq is not None
        checked_view = f"{ds.name}__checked"

        def _checked(spark=spark, ds=ds, dq=dq, src=input_view, streaming=streaming) -> DataFrame:
            return dq.apply(spark, _read_view(spark, src, streaming=streaming), ds)

        dp.temporary_view(_checked, name=checked_view)
        upstream = checked_view

        if not annotate_only:
            valid_view = f"{ds.name}__valid"

            def _valid(spark=spark, dq=dq, src=checked_view, streaming=streaming) -> DataFrame:
                return dq.valid(_read_view(spark, src, streaming=streaming))

            dp.temporary_view(_valid, name=valid_view)
            upstream = valid_view

    _register_target(spark, ds, layer, ctx, upstream, streaming)
    if ds.quality and not annotate_only:
        _register_quarantine(spark, ds, layer, ctx, dq, f"{ds.name}__checked", streaming)


def _register_target(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    upstream: str,
    streaming: bool,
) -> None:
    target = ds.target
    if isinstance(target, TemporaryViewTarget):

        def _view(spark=spark, src=upstream, streaming=streaming) -> DataFrame:
            return _read_view(spark, src, streaming=streaming)

        dp.temporary_view(_view, name=ds.name, comment=ds.comment)
        return

    if isinstance(target, StreamingTableTarget):
        table = ctx.target_fqn(ds.name, layer)
        properties = {**layer.defaults.table_properties, **target.table_properties}
        if target.cdc:
            dp.create_streaming_table(
                name=table,
                comment=ds.comment,
                table_properties=properties,
                partition_cols=target.partition_cols or None,
                cluster_by=target.cluster_by or None,
                schema=target.table_schema,
            )
            cdc = target.cdc
            compat.create_auto_cdc_flow(
                name=f"{ds.name}__cdc_flow",
                target=table,
                source=upstream,
                keys=list(cdc.keys),
                sequence_by=cdc.sequence_by,
                stored_as_scd_type=cdc.scd_type,
                apply_as_deletes=F.expr(cdc.apply_as_deletes) if cdc.apply_as_deletes else None,
                except_column_list=cdc.except_columns or None,
                ignore_null_updates=cdc.ignore_null_updates,
                track_history_except_column_list=cdc.track_history_except_columns or None,
            )
            return

        def _stream(spark=spark, src=upstream) -> DataFrame:
            return spark.readStream.table(src)

        dp.table(
            _stream,
            name=table,
            comment=ds.comment,
            table_properties=properties,
            partition_cols=target.partition_cols or None,
            cluster_by=target.cluster_by or None,
            schema=target.table_schema,
        )
        return

    if isinstance(target, MaterializedViewTarget):

        def _batch(spark=spark, src=upstream) -> DataFrame:
            return spark.read.table(src)

        dp.materialized_view(
            _batch,
            name=ctx.target_fqn(ds.name, layer),
            comment=ds.comment,
            table_properties={**layer.defaults.table_properties, **target.table_properties},
            partition_cols=target.partition_cols or None,
            cluster_by=target.cluster_by or None,
        )
        return

    if isinstance(target, DeltaSinkTarget):
        sink = f"{ds.name}__sink"
        compat.create_sink(
            name=sink, format="delta", options={**ctx.sink_destination(target), **target.options}
        )

        def _to_sink(spark=spark, src=upstream) -> DataFrame:
            return spark.readStream.table(src)

        compat.append_flow(target=sink, name=f"{ds.name}__sink_flow")(_to_sink)
        return

    raise TypeError(f"unhandled target kind: {target!r}")  # pragma: no cover


def _register_quarantine(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    dq: DQAdapter | None,
    checked_view: str,
    streaming: bool,
) -> None:
    assert dq is not None and ds.quality is not None
    if ds.quality.quarantine:
        q = ds.quality.quarantine
        q_name = ds.quarantine_name() or ""
        q_fqn = ctx.target_fqn(q_name, layer)
        properties = {
            **layer.defaults.table_properties,
            "datalab.dq": "quarantine",
            **q.table_properties,
        }

        def _quarantine(
            spark=spark,
            dq=dq,
            src=checked_view,
            streaming=streaming,
            include_warnings=q.include_warnings,
        ) -> DataFrame:
            return dq.invalid(
                _read_view(spark, src, streaming=streaming), include_warnings=include_warnings
            )

        comment = f"Rows of {ds.name!r} that violated quality rules, kept for triage."
        if streaming:
            dp.table(_quarantine, name=q_fqn, comment=comment, table_properties=properties)
        else:
            dp.materialized_view(
                _quarantine, name=q_fqn, comment=comment, table_properties=properties
            )

        if ds.quality.metrics.enabled:
            m_name = ds.metrics_name() or ""

            def _metrics(spark=spark, dq=dq, src=q_fqn) -> DataFrame:
                return summarize_dq_results(spark.read.table(src), dq.errors_col, dq.warnings_col)

            dp.materialized_view(
                _metrics,
                name=ctx.target_fqn(m_name, layer),
                comment=f"Per-rule DQ violation counts for {ds.name!r}.",
                table_properties={**layer.defaults.table_properties, "datalab.dq": "metrics"},
            )
