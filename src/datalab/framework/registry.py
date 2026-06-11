"""Named-function registries: transforms and custom dqx check functions.

YAML references functions by registry key (``customer_sales.clean_customers``).
The framework hardcodes NO domain module paths — each layer YAML declares the
modules that register its functions via ``imports:``
(e.g. ``imports: [customer_sales_etl.transforms.customers,
customer_sales_etl.checks]``), and the loader imports them before resolution.
Only the ``framework.*`` built-ins below ship with the framework itself.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from datalab.framework.errors import ConfigError

TRANSFORMS: dict[str, Callable[..., DataFrame]] = {}
CHECKS: dict[str, Callable[..., Column]] = {}
SNAPSHOT_SOURCES: dict[str, Callable] = {}


def transform(name: str) -> Callable[[Callable[..., DataFrame]], Callable[..., DataFrame]]:
    """Register a pure DataFrame transform under a YAML-referenceable name."""

    def decorator(fn: Callable[..., DataFrame]) -> Callable[..., DataFrame]:
        TRANSFORMS[name] = fn
        return fn

    return decorator


def check_function(fn: Callable[..., Column]) -> Callable[..., Column]:
    """Register a custom dqx check function under its own name."""
    CHECKS[fn.__name__] = fn
    return fn


def snapshot_source(name: str) -> Callable[[Callable], Callable]:
    """Register an historical-snapshot walker for ``cdc_from_snapshot``
    (source kind ``snapshot_function``). The SDP contract:
    ``fn(latest_processed_version | None) -> (DataFrame, version) | None`` —
    return successive snapshots in ascending version order, None to stop."""

    def decorator(fn: Callable) -> Callable:
        SNAPSHOT_SOURCES[name] = fn
        return fn

    return decorator


def import_modules(modules: list[str]) -> None:
    """Import the modules a layer YAML declares under ``imports:`` so their
    @transform/@check_function registrations land before resolution."""
    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            raise ConfigError(
                f"could not import {module!r} (declared under 'imports:'): {exc}. "
                "The module must be part of an installed package — for domain code, "
                "add it to [tool.hatch.build.targets.wheel] packages in pyproject.toml."
            ) from exc


def resolve_transform(name: str) -> Callable[..., DataFrame]:
    try:
        return TRANSFORMS[name]
    except KeyError:
        raise ConfigError(
            f"unknown transform {name!r} — registered transforms: "
            f"{sorted(TRANSFORMS) or '(none)'}. Register it with "
            "@datalab.framework.registry.transform(...) in a domain module and "
            "declare that module in the layer YAML's 'imports:' list."
        ) from None


def resolve_snapshot_source(name: str) -> Callable:
    try:
        return SNAPSHOT_SOURCES[name]
    except KeyError:
        raise ConfigError(
            f"unknown snapshot source {name!r} — registered: "
            f"{sorted(SNAPSHOT_SOURCES) or '(none)'}. Register it with "
            "@datalab.framework.registry.snapshot_source(...) in a domain module "
            "and declare that module in the layer YAML's 'imports:' list."
        ) from None


def check_registry() -> dict[str, Callable[..., Column]]:
    """Custom check functions, in the shape dqx's ``custom_check_functions`` takes."""
    return dict(CHECKS)


# ---------------------------------------------------------------------------
# Built-in transforms, usable from any YAML without writing python.
# ---------------------------------------------------------------------------
@transform("framework.add_lineage")
def add_lineage(df: DataFrame) -> DataFrame:
    return df.withColumn("_ingest_ts", F.current_timestamp()).withColumn(
        "_source_file", F.col("_metadata.file_path")
    )


@transform("framework.select")
def select_columns(df: DataFrame, columns: list[str]) -> DataFrame:
    return df.select(*columns)


@transform("framework.where")
def where_filter(df: DataFrame, condition: str) -> DataFrame:
    return df.where(condition)


@transform("framework.to_json_value")
def to_json_value(df: DataFrame, key: str | None = None) -> DataFrame:
    """Pack rows into the Kafka writer contract: a JSON ``value`` column of
    every (non-key) column, plus an optional string ``key`` column — the
    last step before a ``kafka_sink`` target."""
    payload = [c for c in df.columns if c != key]
    out = df.withColumn("value", F.to_json(F.struct(*payload)))
    if key is not None:
        out = out.withColumn("key", F.col(key).cast("string"))
        return out.select("key", "value")
    return out.select("value")
