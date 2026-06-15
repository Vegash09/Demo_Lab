"""The metaprogramming loop: validated configs → registered LDP datasets.

Eager-but-thin: YAML/pydantic/dqx validation happens at pipeline-source import
(fail fast, before any data moves); all Spark work stays inside the lazy
query functions the writers register.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession

from datalab.config import pipeline_conf
from datalab.framework.context import ResolveContext
from datalab.framework.dq import DQAdapter
from datalab.framework.errors import FrameworkRuntimeError
from datalab.framework.loader import load_domain_configs
from datalab.framework.writers import register_dataset

# datalab.profile selects the execution target. "databricks" (default) emits the
# full Lakeflow SDP graph (streaming tables, AUTO CDC, sinks). "local" emits a
# batch materialized-view approximation that the OSS spark-pipelines CLI can run
# on a workstation — see datalab.framework.local and docs/FRAMEWORK.md.
PROFILES = ("databricks", "local")


def generate(
    spark: SparkSession, config_dir: str | Path, *, layers: list[str] | None = None
) -> None:
    profile = pipeline_conf(spark, "datalab.profile", "databricks")
    if profile == "local":
        # Imported lazily: the local registrar is only needed off-Databricks and
        # keeps this module's import light.
        from datalab.framework.local import generate_local

        generate_local(spark, config_dir, layers=layers)
        return
    if profile != "databricks":
        raise FrameworkRuntimeError(
            f"unknown datalab.profile {profile!r} — expected one of {PROFILES}"
        )

    ctx = ResolveContext.from_spark(spark)
    for layer_config in load_domain_configs(Path(config_dir), layers):
        needs_dq = any(ds.has_checks for ds in layer_config.datasets)
        dq = DQAdapter.for_layer(spark, layer_config, ctx) if needs_dq else None
        for ds in layer_config.datasets:
            register_dataset(spark, ds, layer_config, ctx, dq if ds.has_checks else None)
