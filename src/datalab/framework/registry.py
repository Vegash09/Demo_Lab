"""Named-function registries: transforms and custom dqx check functions.

YAML references functions by registry key (``sales.clean_customers``); the
registries make that lookup deterministic regardless of import order via
:func:`discover`, which imports every module under ``datalab.transforms`` and
``datalab.checks``.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from datalab.framework.errors import ConfigError

TRANSFORMS: dict[str, Callable[..., DataFrame]] = {}
CHECKS: dict[str, Callable[..., Column]] = {}


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


def _import_all(package_name: str) -> None:
    try:
        package = importlib.import_module(package_name)
    except ModuleNotFoundError:
        return
    for module in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package_name}.{module.name}")


_discovered = False


def discover() -> None:
    """Import every transforms/checks module so registration is deterministic."""
    global _discovered
    if _discovered:
        return
    _import_all("datalab.transforms")
    _import_all("datalab.checks")
    _discovered = True


def resolve_transform(name: str) -> Callable[..., DataFrame]:
    discover()
    try:
        return TRANSFORMS[name]
    except KeyError:
        raise ConfigError(
            f"unknown transform {name!r} — registered transforms: "
            f"{sorted(TRANSFORMS) or '(none)'}. Register it with "
            "@datalab.framework.registry.transform(...) in datalab/transforms/."
        ) from None


def check_registry() -> dict[str, Callable[..., Column]]:
    """Custom check functions, in the shape dqx's ``custom_check_functions`` takes."""
    discover()
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
