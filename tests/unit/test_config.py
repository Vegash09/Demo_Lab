import pytest

from datalab.config import fqn, pipeline_conf


def test_fqn():
    assert fqn("cat", "silver", "customers") == "cat.silver.customers"


def test_pipeline_conf_reads_spark_conf(spark):
    spark.conf.set("datalab.test_key", "value-1")
    assert pipeline_conf(spark, "datalab.test_key") == "value-1"


def test_pipeline_conf_default_and_missing(spark):
    assert pipeline_conf(spark, "datalab.does_not_exist", "fallback") == "fallback"
    with pytest.raises(ValueError, match="datalab.missing"):
        pipeline_conf(spark, "datalab.missing")
