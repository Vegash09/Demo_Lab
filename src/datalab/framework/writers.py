"""Writer adapters: register one dataset's full LDP graph from its spec.

Per dataset the generator emits one input-view chain PER FLOW (the dlt-meta
pattern — one read fans out to every sink, which is what lets DQX compose
with AUTO CDC):

    <name>__input                     source + transforms        (per flow)
    <name>__valid     (if quality)    dqx applied INLINE, error rows dropped,
                                      result cols stripped (per flow)
    target writer                     streaming table / CDC / snapshot CDC /
                                      MV / view / delta+kafka sink
    <quarantine>      (if configured) dqx applied INLINE, rows the target
                                      rejected (all flows)
    <name>__checked   (annotate-only) dqx-annotated frame, only for a
                                      temporary_view target carrying quality

dqx result columns (_errors/_warnings) must be produced and consumed in the
SAME DataFrame scope: re-reading a checked view by name
(spark.read[Stream].table) drops them on Databricks SDP, so the valid /
quarantine split is built by applying dqx INLINE on __input — never across a
temporary-view boundary.
    <metrics> MV      (if enabled)    per-rule violation counts

Flow naming (SDP uses the FLOW NAME as the streaming-checkpoint identity —
renaming a flow abandons its checkpoint):

    single `source:`                  <name>__input / <name>__cdc_flow /
                                      <name>__sink_flow — the legacy names,
                                      so existing deployments keep state
    fan-in `sources:` entry <s>       <name>__<s>__input / __flow / __cdc_flow
    `backfill:` entry <b>             <name>__<b>__backfill (once=True)

CONVENTION (load-bearing): every generated closure binds loop state through
DEFAULT ARGUMENTS — never free variables — or each dataset would silently
read the last loop iteration's spec (the classic late-binding bug). Reviewers
must reject any free closure over loop variables in this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from datalab.framework import compat
from datalab.framework.context import ResolveContext
from datalab.framework.dq import DQAdapter, summarize_dq_results
from datalab.framework.models import (
    DatasetSpec,
    DeltaSinkTarget,
    KafkaSinkTarget,
    LayerConfig,
    MaterializedViewTarget,
    SnapshotFunctionSource,
    SourceSpec,
    StreamingTableTarget,
    TemporaryViewTarget,
    _is_streaming_source,
)
from datalab.framework.readers import prepare, read_source
from datalab.framework.registry import resolve_snapshot_source


@dataclass(frozen=True)
class _Flow:
    suffix: str | None  # None == legacy single-source naming
    source: SourceSpec
    once: bool  # True for backfill flows
    comment: str | None = None

    def prefix(self, dataset: str) -> str:
        return dataset if self.suffix is None else f"{dataset}__{self.suffix}"

    def streaming(self) -> bool:
        return _is_streaming_source(self.source)


def _flows(ds: DatasetSpec) -> list[_Flow]:
    continuous = [
        _Flow(suffix=suffix, source=source, once=False)
        for suffix, source in ds.streaming_flows()
    ]
    backfills = [
        _Flow(suffix=b.name, source=b.source, once=True, comment=b.comment)
        for b in ds.backfill
    ]
    return continuous + backfills


def _read_view(spark: SparkSession, view: str, *, streaming: bool) -> DataFrame:
    return spark.readStream.table(view) if streaming else spark.read.table(view)


def register_dataset(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    dq: DQAdapter | None,
) -> None:
    target = ds.target

    # Snapshot CDC pattern B: the engine consumes the registered function's
    # frames directly — there is no view chain (and no dq, enforced by the
    # models). Columns/transforms still apply, wrapped around the function.
    if (
        isinstance(target, StreamingTableTarget)
        and target.cdc_from_snapshot
        and isinstance(ds.source, SnapshotFunctionSource)
    ):
        _register_snapshot_target(spark, ds, layer, ctx, source=None)
        return

    annotate_only = isinstance(target, TemporaryViewTarget)
    flows = _flows(ds)

    flow_views: list[tuple[_Flow, str]] = []  # (flow, terminal view to write from)
    for flow in flows:
        prefix = flow.prefix(ds.name)
        input_view = f"{prefix}__input"
        streaming = flow.streaming()

        def _input(spark=spark, ds=ds, layer=layer, ctx=ctx, src=flow.source) -> DataFrame:
            return prepare(read_source(spark, src, layer, ctx), ds)

        dp.temporary_view(_input, name=input_view)

        upstream = input_view
        if ds.has_checks:
            assert dq is not None
            if annotate_only:
                # temporary_view target carrying quality: the dqx-annotated
                # frame (with _errors/_warnings) IS the published output.
                checked_view = f"{prefix}__checked"

                def _checked(
                    spark=spark, ds=ds, dq=dq, src=input_view, streaming=streaming
                ) -> DataFrame:
                    return dq.apply(spark, _read_view(spark, src, streaming=streaming), ds)

                dp.temporary_view(_checked, name=checked_view)
                upstream = checked_view
            else:
                # Apply dqx INLINE and split in the same scope. The dqx result
                # columns must not cross a temporary-view boundary: re-reading a
                # checked view by name drops _errors/_warnings on Databricks SDP,
                # failing the split with UNRESOLVED_COLUMN `_errors`.
                valid_view = f"{prefix}__valid"

                def _valid(
                    spark=spark, ds=ds, dq=dq, src=input_view, streaming=streaming
                ) -> DataFrame:
                    checked = dq.apply(spark, _read_view(spark, src, streaming=streaming), ds)
                    return dq.valid(checked)

                dp.temporary_view(_valid, name=valid_view)
                upstream = valid_view

        flow_views.append((flow, upstream))

    _register_target(spark, ds, layer, ctx, flow_views)
    if ds.has_checks and not annotate_only:
        _register_quarantine(spark, ds, layer, ctx, dq, flow_views)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
def _register_target(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    flow_views: list[tuple[_Flow, str]],
) -> None:
    target = ds.target

    if isinstance(target, TemporaryViewTarget):
        upstream = flow_views[0][1]
        streaming = flow_views[0][0].streaming()

        def _view(spark=spark, src=upstream, streaming=streaming) -> DataFrame:
            return _read_view(spark, src, streaming=streaming)

        dp.temporary_view(_view, name=ds.name, comment=ds.comment)
        return

    if isinstance(target, StreamingTableTarget):
        _register_streaming_table(spark, ds, layer, ctx, flow_views)
        return

    if isinstance(target, MaterializedViewTarget):
        upstream = flow_views[0][1]

        def _batch(spark=spark, src=upstream) -> DataFrame:
            return spark.read.table(src)

        kwargs: dict = {}
        if target.table_schema:
            kwargs["schema"] = target.table_schema
        if target.cluster_by_auto:
            kwargs["cluster_by_auto"] = True
        if target.refresh_policy:
            kwargs["refresh_policy"] = target.refresh_policy
        compat.materialized_view(
            _batch,
            name=ctx.target_fqn(ds.name, layer),
            comment=ds.comment,
            table_properties={**layer.defaults.table_properties, **target.table_properties},
            partition_cols=target.partition_cols or None,
            cluster_by=target.cluster_by or None,
            **kwargs,
        )
        return

    if isinstance(target, (DeltaSinkTarget, KafkaSinkTarget)):
        sink = f"{ds.name}__sink"
        if isinstance(target, DeltaSinkTarget):
            options = {**ctx.sink_destination(target), **target.options}
            compat.create_sink(name=sink, format="delta", options=options)
        else:
            options = {
                "kafka.bootstrap.servers": ctx.resolve(target.bootstrap_servers_conf),
                **({"topic": target.topic} if target.topic else {}),
                **target.options,
            }
            compat.create_sink(name=sink, format="kafka", options=options)

        for flow, upstream in flow_views:
            flow_name = (
                f"{ds.name}__sink_flow"
                if flow.suffix is None
                else f"{ds.name}__{flow.suffix}__sink_flow"
            )

            def _to_sink(spark=spark, src=upstream) -> DataFrame:
                return spark.readStream.table(src)

            compat.append_flow(target=sink, name=flow_name)(_to_sink)
        return

    raise TypeError(f"unhandled target kind: {target!r}")  # pragma: no cover


def _register_streaming_table(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    flow_views: list[tuple[_Flow, str]],
) -> None:
    target = ds.target
    assert isinstance(target, StreamingTableTarget)
    table = ctx.target_fqn(ds.name, layer)
    properties = {**layer.defaults.table_properties, **target.table_properties}
    table_kwargs: dict = dict(
        comment=ds.comment,
        table_properties=properties,
        partition_cols=target.partition_cols or None,
        cluster_by=target.cluster_by or None,
        schema=target.table_schema,
    )
    if target.cluster_by_auto:
        table_kwargs["cluster_by_auto"] = True

    if target.cdc_from_snapshot:
        _register_snapshot_target(spark, ds, layer, ctx, source=flow_views[0][1])
        return

    if target.cdc:
        compat.create_streaming_table(name=table, **table_kwargs)
        cdc = target.cdc
        sequence_by = (
            cdc.sequence_by
            if isinstance(cdc.sequence_by, str)
            # multi-column ordering: struct() orders by the first field,
            # breaking ties with the later ones (SDP contract)
            else F.struct(*cdc.sequence_columns)
        )
        for flow, upstream in flow_views:
            flow_name = (
                f"{ds.name}__cdc_flow"
                if flow.suffix is None
                else f"{ds.name}__{flow.suffix}__cdc_flow"
            )
            kwargs: dict = dict(
                name=flow_name,
                target=table,
                source=upstream,
                keys=list(cdc.keys),
                sequence_by=sequence_by,
                stored_as_scd_type=cdc.scd_type,
                apply_as_deletes=F.expr(cdc.apply_as_deletes) if cdc.apply_as_deletes else None,
                apply_as_truncates=(
                    F.expr(cdc.apply_as_truncates) if cdc.apply_as_truncates else None
                ),
                column_list=cdc.column_list or None,
                except_column_list=cdc.except_columns or None,
                ignore_null_updates=cdc.ignore_null_updates,
                track_history_column_list=cdc.track_history_columns or None,
                track_history_except_column_list=cdc.track_history_except_columns or None,
            )
            if flow.once:
                kwargs["once"] = True
            compat.create_auto_cdc_flow(**kwargs)
        return

    # Plain streaming table. The single-source/no-backfill form keeps the
    # legacy one-step @dp.table (default flow named after the table, existing
    # checkpoints preserved); any fan-in/backfill needs the explicit
    # target + per-flow append flows. Converting between the two forms
    # renames flows == new checkpoints — pair it with a full refresh.
    only = flow_views[0]
    if len(flow_views) == 1 and only[0].suffix is None and not only[0].once:

        def _stream(spark=spark, src=only[1]) -> DataFrame:
            return spark.readStream.table(src)

        compat.table(_stream, name=table, **table_kwargs)
        return

    compat.create_streaming_table(name=table, **table_kwargs)
    for flow, upstream in flow_views:
        flow_name = (
            f"{ds.name}__flow"
            if flow.suffix is None
            else f"{ds.name}__{flow.suffix}__{'backfill' if flow.once else 'flow'}"
        )
        streaming = flow.streaming()

        def _from_view(spark=spark, src=upstream, streaming=streaming) -> DataFrame:
            return _read_view(spark, src, streaming=streaming)

        flow_kwargs: dict = dict(target=table, name=flow_name)
        if flow.once:
            flow_kwargs["once"] = True
        if flow.comment:
            flow_kwargs["comment"] = flow.comment
        compat.append_flow(**flow_kwargs)(_from_view)


def _register_snapshot_target(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    *,
    source: str | None,
) -> None:
    """AUTO CDC FROM SNAPSHOT. ``source`` is the prepared view name
    (pattern A: periodic snapshots, re-read each update) or None for the
    registered-function form (pattern B: historical snapshot sets)."""
    target = ds.target
    assert isinstance(target, StreamingTableTarget) and target.cdc_from_snapshot
    snap = target.cdc_from_snapshot
    table = ctx.target_fqn(ds.name, layer)
    table_kwargs: dict = dict(
        comment=ds.comment,
        table_properties={**layer.defaults.table_properties, **target.table_properties},
        partition_cols=target.partition_cols or None,
        cluster_by=target.cluster_by or None,
        schema=target.table_schema,
    )
    if target.cluster_by_auto:
        table_kwargs["cluster_by_auto"] = True
    compat.create_streaming_table(name=table, **table_kwargs)

    if source is None:
        assert isinstance(ds.source, SnapshotFunctionSource)
        walker = resolve_snapshot_source(ds.source.function)

        def _wrapped(version, walker=walker, ds=ds):
            result = walker(version)
            if result is None:
                return None
            frame, next_version = result
            return prepare(frame, ds), next_version

        flow_source = _wrapped
    else:
        flow_source = source

    compat.create_auto_cdc_from_snapshot_flow(
        name=f"{ds.name}__snapshot_cdc_flow",
        target=table,
        source=flow_source,
        keys=list(snap.keys),
        stored_as_scd_type=snap.scd_type,
        track_history_column_list=snap.track_history_columns or None,
        track_history_except_column_list=snap.track_history_except_columns or None,
    )


# ---------------------------------------------------------------------------
# Quarantine + metrics
# ---------------------------------------------------------------------------
def _register_quarantine(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    dq: DQAdapter | None,
    flow_views: list[tuple[_Flow, str]],
) -> None:
    assert dq is not None
    q = ds.quarantine_spec()
    if q is None:
        return
    q_name = ds.quarantine_name() or ""
    q_fqn = ctx.target_fqn(q_name, layer)
    properties = {
        **layer.defaults.table_properties,
        "datalab.dq": "quarantine",
        **q.table_properties,
    }
    comment = f"Rows of {ds.name!r} that violated quality rules, kept for triage."

    if not ds.is_streaming:
        input_view = f"{flow_views[0][0].prefix(ds.name)}__input"

        def _quarantine_mv(
            spark=spark, ds=ds, dq=dq, src=input_view, include_warnings=q.include_warnings
        ) -> DataFrame:
            checked = dq.apply(spark, _read_view(spark, src, streaming=False), ds)
            return dq.invalid(checked, include_warnings=include_warnings)

        dp.materialized_view(
            _quarantine_mv, name=q_fqn, comment=comment, table_properties=properties
        )
        _register_metrics(spark, ds, layer, ctx, dq, q_fqn)
        return

    only = flow_views[0]
    if len(flow_views) == 1 and only[0].suffix is None and not only[0].once:
        input_view = f"{ds.name}__input"

        def _quarantine(
            spark=spark,
            ds=ds,
            dq=dq,
            src=input_view,
            streaming=True,
            include_warnings=q.include_warnings,
        ) -> DataFrame:
            checked = dq.apply(spark, _read_view(spark, src, streaming=streaming), ds)
            return dq.invalid(checked, include_warnings=include_warnings)

        compat.table(_quarantine, name=q_fqn, comment=comment, table_properties=properties)
        _register_metrics(spark, ds, layer, ctx, dq, q_fqn)
        return

    # Multi-flow / backfill: the quarantine mirrors the target's flow fan-in
    # so EVERY flow's rejected rows land in the same triage table.
    compat.create_streaming_table(name=q_fqn, comment=comment, table_properties=properties)
    for flow, _ in flow_views:
        input_view = f"{flow.prefix(ds.name)}__input"
        streaming = flow.streaming()
        flow_name = f"{q_name}__{flow.suffix or 'primary'}" + ("__backfill" if flow.once else "__flow")

        def _invalid(
            spark=spark,
            ds=ds,
            dq=dq,
            src=input_view,
            streaming=streaming,
            include_warnings=q.include_warnings,
        ) -> DataFrame:
            checked = dq.apply(spark, _read_view(spark, src, streaming=streaming), ds)
            return dq.invalid(checked, include_warnings=include_warnings)

        flow_kwargs: dict = dict(target=q_fqn, name=flow_name)
        if flow.once:
            flow_kwargs["once"] = True
        compat.append_flow(**flow_kwargs)(_invalid)
    _register_metrics(spark, ds, layer, ctx, dq, q_fqn)


def _register_metrics(
    spark: SparkSession,
    ds: DatasetSpec,
    layer: LayerConfig,
    ctx: ResolveContext,
    dq: DQAdapter,
    quarantine_fqn: str,
) -> None:
    if not (ds.quality and ds.quality.metrics.enabled):
        return
    m_name = ds.metrics_name() or ""

    def _metrics(spark=spark, dq=dq, src=quarantine_fqn) -> DataFrame:
        return summarize_dq_results(spark.read.table(src), dq.errors_col, dq.warnings_col)

    dp.materialized_view(
        _metrics,
        name=ctx.target_fqn(m_name, layer),
        comment=f"Per-rule DQ violation counts for {ds.name!r}.",
        table_properties={**layer.defaults.table_properties, "datalab.dq": "metrics"},
    )
