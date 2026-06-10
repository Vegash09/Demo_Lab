"""DQX adapter: one engine per layer, local-safe methods only.

Inside dataset functions we use exclusively DataFrame-in/DataFrame-out dqx
methods (apply_checks_by_metadata, get_valid, get_invalid) — never the
``*_and_save_in_table`` variants (writes are forbidden in dataset functions).

ExtraParams ALWAYS pins static run_time/run_id overwrites: non-deterministic
result columns would silently break materialized-view incrementalization.
Per-row event time belongs in the data (``_ingest_ts``), not in dqx metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from datalab.framework.context import ResolveContext
from datalab.framework.models import DatasetSpec, LayerConfig
from datalab.framework.readers import read_references
from datalab.framework.registry import check_registry

STATIC_RUN_TIME = "1970-01-01T00:00:00"


def _build_engine(spark: SparkSession, extra_params: Any) -> Any:
    from databricks.labs.dqx.engine import DQEngine
    from databricks.sdk import WorkspaceClient

    try:
        return DQEngine(WorkspaceClient(), spark=spark, extra_params=extra_params)
    except Exception:
        # Documented local pattern (no workspace available/authenticated):
        # only local-safe DataFrame methods are ever called, so the client
        # behind the mock is never actually used.
        return DQEngine(
            MagicMock(spec=WorkspaceClient), spark=spark, extra_params=extra_params
        )


@dataclass(frozen=True)
class DQAdapter:
    engine: Any
    layer: LayerConfig
    ctx: ResolveContext
    errors_col: str
    warnings_col: str

    @classmethod
    def for_layer(cls, spark: SparkSession, layer: LayerConfig, ctx: ResolveContext) -> DQAdapter:
        from databricks.labs.dqx.config import ExtraParams

        cols = layer.dq.result_columns
        variables: dict[str, Any] = {
            key.rsplit(".", 1)[-1]: ctx.resolve(key) for key in layer.dq.variables_conf
        }
        extra = ExtraParams(
            result_column_names={"errors": cols.errors, "warnings": cols.warnings},
            run_time_overwrite=STATIC_RUN_TIME,
            run_id_overwrite=f"{layer.domain}_{layer.layer}_pipeline",
            variables=variables,
        )
        return cls(
            engine=_build_engine(spark, extra),
            layer=layer,
            ctx=ctx,
            errors_col=cols.errors,
            warnings_col=cols.warnings,
        )

    def apply(self, spark: SparkSession, df: DataFrame, ds: DatasetSpec) -> DataFrame:
        """Annotate ``df`` with _errors/_warnings result columns."""
        checks = ds.effective_checks()
        references = ds.quality.references if ds.quality else {}
        ref_dfs = read_references(spark, references, self.layer, self.ctx)
        return self.engine.apply_checks_by_metadata(
            df, checks, custom_check_functions=check_registry(), ref_dfs=ref_dfs
        )

    def valid(self, checked: DataFrame) -> DataFrame:
        """Rows that pass every error rule, result columns stripped."""
        return self.engine.get_valid(checked)

    def invalid(self, checked: DataFrame, *, include_warnings: bool) -> DataFrame:
        """Quarantine slice. include_warnings=False (default) keeps legacy
        parity: quarantine == exactly the rows dropped from the target."""
        bad = self.engine.get_invalid(checked)
        if not include_warnings:
            bad = bad.where(F.col(self.errors_col).isNotNull())
        return bad


def summarize_dq_results(quarantine: DataFrame, errors_col: str, warnings_col: str) -> DataFrame:
    """Per-rule violation counts from a quarantine table's dqx result arrays."""
    exploded = []
    for criticality, col in (("error", errors_col), ("warn", warnings_col)):
        if col in quarantine.columns:
            exploded.append(
                quarantine.select(F.explode_outer(col).alias("r"))
                .where(F.col("r").isNotNull())
                .select(
                    F.col("r.name").alias("check_name"),
                    F.lit(criticality).alias("criticality"),
                    F.col("r.function").alias("function"),
                )
            )
    if not exploded:
        raise ValueError(
            f"quarantine table has neither {errors_col!r} nor {warnings_col!r} columns"
        )
    union = exploded[0]
    for df in exploded[1:]:
        union = union.unionByName(df)
    return union.groupBy("check_name", "criticality", "function").agg(
        F.count("*").alias("violations")
    )
