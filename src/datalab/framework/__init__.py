"""flowspec — config-driven Lakeflow Declarative Pipelines framework.

Developers describe datasets in per-layer YAML files (``config/<domain>/``)
validated by Pydantic models; the generator registers the LDP datasets through
reader/writer adapters, with data quality fully delegated to
databrickslabs/dqx. See ``docs/FRAMEWORK.md`` for the authoring guide.
"""

from typing import TYPE_CHECKING

from datalab.framework.devtools import DatasetRunResult, capture_graph, plan, run_dataset
from datalab.framework.errors import ConfigError, FrameworkRuntimeError
from datalab.framework.loader import load_domain, load_domain_configs

if TYPE_CHECKING:
    from datalab.framework.generator import generate

__all__ = [
    "ConfigError",
    "DatasetRunResult",
    "FrameworkRuntimeError",
    "capture_graph",
    "generate",
    "load_domain",
    "load_domain_configs",
    "plan",
    "run_dataset",
]


def __getattr__(name: str):  # noqa: ANN202 — module-level PEP 562 hook
    # `generate` is imported lazily so that importing the framework (e.g. for
    # run_dataset under Databricks Connect, where pyspark may lack
    # pyspark.pipelines) does not eagerly pull the generator → writers → compat
    # chain that imports `from pyspark import pipelines as dp`.
    if name == "generate":
        from datalab.framework.generator import generate

        return generate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
