"""Lakeflow Connect MySQL adopter contract tests.

The PR intentionally does not deploy a live MySQL gateway/ingestion pipeline yet:
there is no real UC Connection or source grant in this template repo. The safe
contract is:

* framework-style source config exists without placeholders;
* rendered examples are kept under resources/examples/ and therefore are not
  included by databricks.yml's projects/*/resources/*.yml glob;
* the bronze table config is an example only until the raw table exists;
* UC bootstrap provisions the extra raw/gateway schemas for customer_sales.
"""

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
RESOURCES_DIR = PROJECT_ROOT / "resources"
EXAMPLE_RESOURCES_DIR = RESOURCES_DIR / "examples"
CONFIG_DIR = PROJECT_ROOT / "config" / "customer_sales"
MYSQL_SOURCE = CONFIG_DIR / "ingestion" / "mysql" / "customer_sales_mysql.yml"
BRONZE_EXAMPLE = CONFIG_DIR / "bronze" / "examples" / "customers_mysql_raw.yml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _text(paths: list[Path]) -> str:
    return "\n".join(path.read_text() for path in paths)


def test_mysql_resources_are_examples_not_live_deploy_inputs():
    """No placeholder gateway/ingestion pipeline should be deployed on merge."""
    assert not (RESOURCES_DIR / "customer_sales_mysql_gateway.pipeline.yml").exists()
    assert not (RESOURCES_DIR / "customer_sales_mysql_ingest.pipeline.yml").exists()
    assert not (RESOURCES_DIR / "customer_sales_mysql_ingest_schedule.job.yml").exists()
    assert not (CONFIG_DIR / "bronze" / "customers_mysql_raw.yml").exists()

    # databricks.yml includes projects/*/resources/*.yml only; the examples
    # subdir is intentionally outside that live bundle glob.
    active_resource_names = {path.name for path in RESOURCES_DIR.glob("*.yml")}
    assert "customer_sales_mysql_gateway.pipeline.yml" not in active_resource_names
    assert "customer_sales_mysql_ingest.pipeline.yml" not in active_resource_names
    assert "customer_sales_mysql_ingest_schedule.job.yml" not in active_resource_names


def test_source_config_is_framework_style_and_has_no_placeholders():
    source = _load_yaml(MYSQL_SOURCE)

    assert source["kind"] == "lakeflow_connect_ingestion_source"
    assert source["connector"] == "mysql"
    assert source["gateway"]["connection_name"] == "customer_sales_mysql_connection"
    assert source["gateway"]["schema_conf"] == "datalab.mysql_gateway_schema"
    assert source["ingestion_pipeline"]["schema_conf"] == "datalab.mysql_raw_schema"
    assert source["ingestion_pipeline"]["pause_status"] == "PAUSED"
    assert source["tables"][0]["destination"]["table"] == "customers_cdc_raw"

    files = [
        MYSQL_SOURCE,
        CONFIG_DIR / "ingestion" / "mysql" / "_template.yml",
        EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_gateway.pipeline.yml",
        EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_ingest.pipeline.yml",
        EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_ingest_schedule.job.yml",
        BRONZE_EXAMPLE,
    ]
    assert "REPLACE_ME" not in _text(files)


def test_example_resources_match_source_config():
    source = _load_yaml(MYSQL_SOURCE)
    gateway_doc = _load_yaml(EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_gateway.pipeline.yml")
    ingest_doc = _load_yaml(EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_ingest.pipeline.yml")
    schedule_doc = _load_yaml(EXAMPLE_RESOURCES_DIR / "customer_sales_mysql_ingest_schedule.job.yml")
    bronze = _load_yaml(BRONZE_EXAMPLE)

    gateway = gateway_doc["resources"]["pipelines"][source["gateway"]["name"]]
    ingest = ingest_doc["resources"]["pipelines"][source["ingestion_pipeline"]["name"]]
    table = ingest["ingestion_definition"]["objects"][0]["table"]
    source_table = source["tables"][0]

    assert gateway["continuous"] is True
    assert "pipeline_type" not in gateway
    assert gateway["gateway_definition"]["connection_name"] == source["gateway"]["connection_name"]
    assert gateway["target"] == "${var.mysql_gateway_schema}"

    assert ingest["continuous"] is False
    for forbidden in ("catalog", "target", "schema", "libraries"):
        assert forbidden not in ingest
    assert (
        ingest["ingestion_definition"]["ingestion_gateway_id"]
        == "${resources.pipelines.customer_sales_mysql_gateway.id}"
    )
    assert table["source_schema"] == source_table["source"]["schema"]
    assert table["source_table"] == source_table["source"]["table"]
    assert table["destination_schema"] == "${var.mysql_raw_schema}"
    assert table["destination_table"] == source_table["destination"]["table"]

    assert bronze["source"]["name"] == table["destination_table"]
    assert bronze["source"]["schema_conf"] == source["ingestion_pipeline"]["schema_conf"]
    assert bronze["source"]["options"]["skipChangeCommits"] == "true"
    assert schedule_doc["resources"]["jobs"]["customer_sales_mysql_ingest_schedule"]["schedule"][
        "pause_status"
    ] == "PAUSED"


def test_mysql_raw_schema_conf_is_declared_on_the_etl_pipeline():
    """If the bronze example is promoted, pipeline_conf can resolve its schema."""
    etl_pipeline_path = RESOURCES_DIR / "customer_sales_etl.pipeline.yml"
    etl = _load_yaml(etl_pipeline_path)
    etl_conf = etl["resources"]["pipelines"]["customer_sales_etl"]["configuration"]
    bronze = _load_yaml(BRONZE_EXAMPLE)
    schema_conf_key = bronze["source"]["schema_conf"].split(".", 1)[-1]
    conf_key = f"datalab.{schema_conf_key}"

    assert conf_key in etl_conf
    assert etl_conf[conf_key] == "${var.mysql_raw_schema}"


def test_bootstrap_provisions_mysql_raw_and_gateway_schemas():
    from scripts.bootstrap_uc import bootstrap_sql

    sql = "\n".join(bootstrap_sql("dev"))
    assert "CREATE SCHEMA IF NOT EXISTS `customer_sales`.`mysql_raw`" in sql
    assert "CREATE SCHEMA IF NOT EXISTS `customer_sales`.`mysql_gateway_meta`" in sql
    assert "GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `customer_sales`.`mysql_raw`" in sql
    assert (
        "GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `customer_sales`.`mysql_gateway_meta`"
        in sql
    )
