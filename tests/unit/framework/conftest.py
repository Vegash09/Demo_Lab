"""Shared fixtures for the FRAMEWORK suite — deliberately example-free.

These tests must pass with ``src/datalab`` alone (the framework lifts into
other projects without the examples/ tree). Synthetic domains therefore use
``imports: []`` plus the ``testkit.*`` transforms registered below, never a
real domain package. End-to-end coverage against the shipped sales example
lives in ``examples/sales/tests/``.
"""

import pytest
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from datalab.framework.registry import transform

DOMAIN_YML = """
schema_version: 1
domain: demo
imports: []
catalog_conf: datalab.catalog
layers:
  bronze: {schema_conf: datalab.bronze_schema}
  silver: {schema_conf: datalab.silver_schema}
  gold: {schema_conf: datalab.gold_schema}
"""


# Registered at conftest import — available to every synthetic config without
# any `imports:` module (the registry is process-global, exactly like a real
# domain module import would leave it).
@transform("testkit.lower_email")
def _lower_email(df: DataFrame) -> DataFrame:
    return df.withColumn("email", F.lower(F.trim("email")))


@pytest.fixture()
def write_domain(tmp_path):
    """write_domain({'silver/customers.yml': '...'}) -> domain config dir."""

    def _write(tables: dict[str, str], domain_yml: str = DOMAIN_YML):
        (tmp_path / "domain.yml").write_text(domain_yml)
        for rel, text in tables.items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return tmp_path

    return _write
