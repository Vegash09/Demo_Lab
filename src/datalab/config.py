"""Helpers for reading pipeline parameters.

Pipelines are parameterized through the ``configuration`` mapping of the
pipeline resource (see ``resources/*.pipeline.yml``), which surfaces values as
Spark conf entries at runtime. Transformations read them with
:func:`pipeline_conf` so a missing key fails fast with a pointer to the fix.
"""

from __future__ import annotations

from pyspark.sql import SparkSession


def pipeline_conf(spark: SparkSession, key: str, default: str | None = None) -> str:
    """Return a pipeline configuration value (Spark conf), or fail helpfully.

    Parameters are declared in the bundle, e.g.::

        # <your domain>.pipeline.yml (see examples/sales/resources/)
        configuration:
          datalab.catalog: ${var.catalog}
    """
    value = spark.conf.get(key, default)
    if value is None:
        raise ValueError(
            f"Missing pipeline configuration {key!r}. Declare it under the "
            "'configuration' mapping of the pipeline resource in resources/."
        )
    return value


def fqn(catalog: str, schema: str, table: str) -> str:
    """Three-level Unity Catalog identifier for a table."""
    return f"{catalog}.{schema}.{table}"
