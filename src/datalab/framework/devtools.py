"""Developer loop: run ONE dataset through the framework without deploying.

``run_dataset`` exercises the exact loader/models/readers/registry/dqx path
the pipeline uses — so "works in the notebook" and "passes pytest" are the
same code path. Streaming reads flip to batch (force_batch) so results
display; nothing is ever written.

For graph inspection without Databricks, ``capture_graph`` registers the
generated datasets into a capturing registry via the OSS
``pyspark.pipelines`` registration context.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

from datalab.framework.context import ResolveContext
from datalab.framework.dq import DQAdapter, summarize_dq_results
from datalab.framework.errors import ConfigError
from datalab.framework.loader import load_domain_configs
from datalab.framework.models import (
    DatasetSpec,
    SnapshotFunctionSource,
    SourceSpec,
    StreamingTableTarget,
)
from datalab.framework.readers import prepare, read_source
from datalab.framework.registry import resolve_snapshot_source


@dataclass(frozen=True)
class DatasetRunResult:
    spec: object
    input_df: DataFrame
    transformed_df: DataFrame
    checked_df: DataFrame | None
    valid_df: DataFrame
    quarantine_df: DataFrame | None
    metrics_df: DataFrame | None
    cdc_plan: str | None


def _pick_flow_source(ds: DatasetSpec, flow: str | None) -> SourceSpec:
    if flow is None:
        return ds.primary_source
    for fs in ds.sources:
        if fs.name == flow:
            return fs.source
    for b in ds.backfill:
        if b.name == flow:
            return b.source
    names = [fs.name for fs in ds.sources] + [b.name for b in ds.backfill]
    raise ConfigError(
        f"dataset {ds.name!r} has no flow {flow!r} — flows: {names or '(single source)'}"
    )


def run_dataset(
    spark: SparkSession,
    config_dir: str | Path,
    layer: str,
    dataset: str,
    *,
    params: Mapping[str, str] | None = None,
    inputs: Mapping[str, DataFrame] | None = None,
    flow: str | None = None,
) -> DatasetRunResult:
    """Run one dataset (by default its primary flow; pass ``flow=`` to pick a
    fan-in source or backfill entry by name) through the framework path."""
    configs = load_domain_configs(Path(config_dir), [layer])
    layer_config = configs[0]
    matches = [d for d in layer_config.datasets if d.name == dataset]
    if not matches:
        raise ConfigError(
            f"no dataset {dataset!r} in layer {layer!r} — datasets: "
            f"{[d.name for d in layer_config.datasets]}"
        )
    ds = matches[0]

    ctx = (
        ResolveContext.from_dict(spark, params, inputs=inputs, force_batch=True)
        if params is not None
        else ResolveContext(spark=spark, inputs=inputs or {}, force_batch=True)
    )

    source = _pick_flow_source(ds, flow)
    if isinstance(source, SnapshotFunctionSource):
        # Preview the FIRST snapshot the registered walker yields.
        result = resolve_snapshot_source(source.function)(None)
        if result is None:
            raise ConfigError(
                f"snapshot source {source.function!r} returned no first snapshot "
                "(fn(None) -> None) — nothing to preview"
            )
        input_df = result[0]
    else:
        input_df = read_source(spark, source, layer_config, ctx)
    transformed = prepare(input_df, ds)

    checked = valid = quarantine = metrics = None
    if ds.has_checks:
        dq = DQAdapter.for_layer(spark, layer_config, ctx)
        checked = dq.apply(spark, transformed, ds)
        valid = dq.valid(checked)
        q = ds.quarantine_spec()
        if q is not None:
            quarantine = dq.invalid(checked, include_warnings=q.include_warnings)
            if ds.quality and ds.quality.metrics.enabled and quarantine is not None:
                metrics = summarize_dq_results(quarantine, dq.errors_col, dq.warnings_col)
    cdc_plan = None
    if isinstance(ds.target, StreamingTableTarget) and ds.target.cdc:
        cdc = ds.target.cdc
        cdc_plan = (
            f"AUTO CDC (engine-owned, verify with a dev refresh): upsert into "
            f"{dataset} by keys={list(cdc.keys)} ordered by {cdc.sequence_by!r}, "
            f"SCD type {cdc.scd_type}"
        )
    elif isinstance(ds.target, StreamingTableTarget) and ds.target.cdc_from_snapshot:
        snap = ds.target.cdc_from_snapshot
        cdc_plan = (
            f"AUTO CDC FROM SNAPSHOT (engine-owned, verify with a dev refresh): "
            f"diff successive snapshots into {dataset} by keys={list(snap.keys)}, "
            f"SCD type {snap.scd_type}; keys absent from the newest snapshot are deleted"
        )

    return DatasetRunResult(
        spec=ds,
        input_df=input_df,
        transformed_df=transformed,
        checked_df=checked,
        valid_df=valid if valid is not None else transformed,
        quarantine_df=quarantine,
        metrics_df=metrics,
        cdc_plan=cdc_plan,
    )


def plan(config_dir: str | Path, layers: list[str] | None = None) -> str:
    """The validated, resolved plan — no Spark needed."""
    lines: list[str] = []
    for cfg in load_domain_configs(Path(config_dir), layers):
        lines.append(f"layer {cfg.layer} (domain {cfg.domain})")
        for ds in cfg.datasets:
            src = ds.primary_source
            src_desc = (
                getattr(src, "name", None)
                or getattr(src, "path_conf", None)
                or getattr(src, "function", None)
                or getattr(src, "topic", None)
                or getattr(src, "subscribe_pattern", "?")
            )
            if ds.sources:
                src_desc = f"fan-in[{', '.join(fs.name for fs in ds.sources)}]"
            mapping = f"{len(ds.columns)} mapped column(s)" if ds.columns else None
            steps = " -> ".join(
                filter(None, [mapping, *(step.function for step in ds.transform)])
            ) or "(passthrough)"
            checks = ds.effective_checks()
            errors = sum(1 for m in checks if m.get("criticality", "error") == "error")
            warns = sum(1 for m in checks if m.get("criticality") == "warn")
            lines.append(
                f"  {ds.name}: {src.kind}:{src_desc} -> {steps} -> {ds.target.kind}"
                + (f" (+{len(ds.backfill)} backfill once-flow(s))" if ds.backfill else "")
                + (f" [dq: {errors} error / {warns} warn rule(s)" if checks else "")
                + (f", quarantine={ds.quarantine_name()}" if ds.quarantine_name() else "")
                + (f", metrics={ds.metrics_name()}" if ds.metrics_name() else "")
                + ("]" if checks else "")
            )
    return "\n".join(lines)


def capture_graph(spark: SparkSession, config_dir: str | Path) -> list[tuple[str, str]]:
    """Register the generated graph into a capturing registry (OSS hook) and
    return ``(element_type, name)`` pairs — local graph inspection only."""
    from pyspark.pipelines.graph_element_registry import (
        GraphElementRegistry,
        graph_element_registration_context,
    )

    captured: list[tuple[str, str]] = []

    class CapturingRegistry(GraphElementRegistry):
        def register_output(self, output) -> None:  # noqa: ANN001
            captured.append((type(output).__name__, output.name))

        def register_flow(self, flow) -> None:  # noqa: ANN001
            captured.append((type(flow).__name__, flow.name))

        def register_sql(self, sql_text: str, file_path) -> None:  # noqa: ANN001
            captured.append(("sql", str(file_path)))

    from datalab.framework import compat
    from datalab.framework.generator import generate

    compat.set_capture_handler(lambda kind, name: captured.append((kind, name)))
    try:
        with graph_element_registration_context(CapturingRegistry()):
            generate(spark, config_dir)
    finally:
        compat.set_capture_handler(None)
    return captured
