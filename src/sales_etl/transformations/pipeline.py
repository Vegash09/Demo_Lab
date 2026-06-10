"""sales_etl pipeline entrypoint — the entire domain is config-driven.

Datasets, transforms and dqx quality rules live in ``config/sales/*.yml``
(path supplied by the bundle as ``datalab.config_dir``); the framework
validates them and registers every LDP dataset. Add a table by editing YAML —
see docs/FRAMEWORK.md.
"""

from datalab.config import pipeline_conf
from datalab.framework import generate

generate(spark, pipeline_conf(spark, "datalab.config_dir"))  # noqa: F821 — spark injected by SDP
