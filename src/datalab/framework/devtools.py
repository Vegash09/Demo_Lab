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
from datalab.framework.models import StreamingTableTarget
from datalab.framework.readers import apply_transforms, read_source


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


def run_dataset(
    spark: SparkSession,
    config_dir: str | Path,
    layer: str,
    dataset: str,
    *,
    params: Mapping[str, str] | None = None,
    inputs: Mapping[str, DataFrame] | None = None,
) -> DatasetRunResult:
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

    input_df = read_source(spark, ds.source, layer_config, ctx)
    transformed = apply_transforms(input_df, ds.transform)

    checked = valid = quarantine = metrics = None
    if ds.quality:
        dq = DQAdapter.for_layer(spark, layer_config, ctx)
        checked = dq.apply(spark, transformed, ds)
        valid = dq.valid(checked)
        if ds.quality.quarantine:
            quarantine = dq.invalid(
                checked, include_warnings=ds.quality.quarantine.include_warnings
            )
            if ds.quality.metrics.enabled and quarantine is not None:
                metrics = summarize_dq_results(quarantine, dq.errors_col, dq.warnings_col)
    cdc_plan = None
    if isinstance(ds.target, StreamingTableTarget) and ds.target.cdc:
        cdc = ds.target.cdc
        cdc_plan = (
            f"AUTO CDC (engine-owned, verify with a dev refresh): upsert into "
            f"{dataset} by keys={list(cdc.keys)} ordered by {cdc.sequence_by!r}, "
            f"SCD type {cdc.scd_type}"
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
            src = ds.source
            src_desc = getattr(src, "name", None) or getattr(src, "path_conf", "?")
            steps = " -> ".join(step.function for step in ds.transform) or "(no transforms)"
            errors = warns = 0
            if ds.quality:
                errors = sum(1 for r in ds.quality.checks if r.criticality == "error")
                warns = sum(1 for r in ds.quality.checks if r.criticality == "warn")
            lines.append(
                f"  {ds.name}: {src.kind}:{src_desc} -> {steps} -> {ds.target.kind}"
                + (f" [dq: {errors} error / {warns} warn rule(s)" if ds.quality else "")
                + (f", quarantine={ds.quarantine_name()}" if ds.quarantine_name() else "")
                + (f", metrics={ds.metrics_name()}" if ds.metrics_name() else "")
                + ("]" if ds.quality else "")
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
