"""The metaprogramming loop: validated configs → registered LDP datasets.

Eager-but-thin: YAML/pydantic/dqx validation happens at pipeline-source import
(fail fast, before any data moves); all Spark work stays inside the lazy
query functions the writers register.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession

from datalab.framework.context import ResolveContext
from datalab.framework.dq import DQAdapter
from datalab.framework.loader import load_domain_configs
from datalab.framework.writers import register_dataset


def generate(
    spark: SparkSession, config_dir: str | Path, *, layers: list[str] | None = None
) -> None:
    ctx = ResolveContext.from_spark(spark)
    for layer_config in load_domain_configs(Path(config_dir), layers):
        needs_dq = any(ds.has_checks for ds in layer_config.datasets)
        dq = DQAdapter.for_layer(spark, layer_config, ctx) if needs_dq else None
        for ds in layer_config.datasets:
            register_dataset(spark, ds, layer_config, ctx, dq if ds.has_checks else None)
