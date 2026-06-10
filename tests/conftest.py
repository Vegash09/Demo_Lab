"""Shared fixtures: a local SparkSession for fast unit tests.

These tests exercise the pure functions in ``src/datalab`` only — they never
touch a workspace. Integration happens through a dev refresh of the deployed
pipeline (``make run``), not through this suite.
"""

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .appName("datalab-unit-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
