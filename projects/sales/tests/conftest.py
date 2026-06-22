"""Local SparkSession for the sales example's tests.

Deliberately self-contained (a copy of the root tests/conftest.py fixture):
the projects/sales/ tree mirrors an adopter repo, so its tests carry their own
fixtures and run with nothing but the installed framework + this folder.
"""

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .appName("sales-example-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
