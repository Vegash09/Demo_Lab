"""customer_sales_etl pipeline entrypoint — the entire domain is config-driven.

Datasets, transforms and dqx quality rules live in the domain's config dir
(``examples/customer_sales/config/customer_sales/`` here; the bundle supplies
the deployed path as ``datalab.config_dir``); the framework validates them and
registers every LDP dataset. Add a table by editing YAML — see
docs/FRAMEWORK.md.
"""

from datalab.config import pipeline_conf
from datalab.framework import generate

generate(spark, pipeline_conf(spark, "datalab.config_dir"))  # noqa: F821 — spark injected by SDP
