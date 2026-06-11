"""flowspec — config-driven Lakeflow Declarative Pipelines framework.

Developers describe datasets in per-layer YAML files (``config/<domain>/``)
validated by Pydantic models; the generator registers the LDP datasets through
reader/writer adapters, with data quality fully delegated to
databrickslabs/dqx. See ``docs/FRAMEWORK.md`` for the authoring guide.
"""

from datalab.framework.devtools import DatasetRunResult, capture_graph, plan, run_dataset
from datalab.framework.errors import ConfigError, FrameworkRuntimeError
from datalab.framework.generator import generate
from datalab.framework.loader import load_domain, load_domain_configs

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
