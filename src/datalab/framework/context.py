"""Resolution context: pipeline-conf lookups, FQNs, and devtools substitution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from datalab.config import fqn, pipeline_conf

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

    from datalab.framework.models import (
        DeltaSinkTarget,
        LayerConfig,
        ReferenceSource,
        TableSource,
    )


@dataclass(frozen=True)
class ResolveContext:
    """How config keys become concrete values for this run.

    In the pipeline, values come from Spark conf (bundle ``configuration:``).
    In devtools/notebooks, ``from_dict`` supplies them directly, ``inputs``
    substitutes sample DataFrames by FQN, and ``force_batch`` flips streaming
    reads to batch so results can be displayed.
    """

    spark: SparkSession
    params: Mapping[str, str] | None = None
    inputs: Mapping[str, DataFrame] = field(default_factory=dict)
    force_batch: bool = False

    @classmethod
    def from_spark(cls, spark: SparkSession) -> ResolveContext:
        return cls(spark=spark)

    @classmethod
    def from_dict(
        cls,
        spark: SparkSession,
        params: Mapping[str, str],
        *,
        inputs: Mapping[str, DataFrame] | None = None,
        force_batch: bool = False,
    ) -> ResolveContext:
        return cls(spark=spark, params=params, inputs=inputs or {}, force_batch=force_batch)

    def resolve(self, conf_key: str) -> str:
        if self.params is not None:
            try:
                return self.params[conf_key]
            except KeyError:
                raise ValueError(
                    f"missing parameter {conf_key!r} — pass it in run_dataset(params=...)"
                ) from None
        return pipeline_conf(self.spark, conf_key)

    def source_fqn(self, src: TableSource | ReferenceSource, layer: LayerConfig) -> str:
        catalog = self.resolve(src.catalog_conf or layer.defaults.catalog_conf)
        schema = self.resolve(src.schema_conf or layer.defaults.schema_conf)
        return fqn(catalog, schema, src.name)

    def target_fqn(self, name: str, layer: LayerConfig) -> str:
        catalog = self.resolve(layer.defaults.catalog_conf)
        schema = self.resolve(layer.defaults.schema_conf)
        return fqn(catalog, schema, name)

    def sink_destination(self, target: DeltaSinkTarget) -> dict[str, str]:
        if target.table_conf:
            return {"tableName": self.resolve(target.table_conf)}
        return {"path": self.resolve(target.path_conf or "")}
