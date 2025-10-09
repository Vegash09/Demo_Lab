import pytest


@pytest.mark.dbconnect_only
def test_dbconnect_spark_session_counts(dbconnect_spark_session):
    spark = dbconnect_spark_session
    assert spark.range(1).count() == 1

