import pytest


@pytest.mark.dbconnect_only
def test_placeholder_dlt_dbconnect(dbconnect_spark_session):
    # DLT runs inside the DLT engine; this placeholder ensures environment is configured.
    # If Databricks Connect isn't properly configured, the fixture will skip this test.
    assert dbconnect_spark_session is not None
