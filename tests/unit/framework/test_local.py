"""Local execution profile (datalab.framework.local).

Guards that ``datalab.profile=local`` downgrades the Databricks graph to a
batch materialized-view graph the OSS spark-pipelines CLI can run: every target
becomes an MV, and the Databricks-only AUTO CDC flow is NOT emitted (it would
raise off-Databricks). This is the cheap, reliable regression guard; the CI
`spark-pipelines dry-run` step exercises the OSS CLI end to end.
"""

import yaml

from datalab.framework.devtools import capture_graph
from datalab.framework.local import write_local_spec

CONF = {
    "datalab.profile": "local",
    "datalab.catalog": "cat",
    "datalab.bronze_schema": "bronze",
    "datalab.silver_schema": "silver",
    "datalab.gold_schema": "gold",
}

# A silver streaming table with AUTO CDC (SCD1) + a column error rule (so a
# quarantine is auto-created) — the shape that needs Databricks-only symbols and
# therefore exercises the local downgrade.
CDC_TABLE_YML = """
name: customers
source: {kind: table, name: customers_raw, schema_conf: datalab.bronze_schema, as_stream: true}
columns:
  - name: id
    type: string
    quality:
      - criticality: error
        check: {function: is_not_null}
  - name: ts
    type: timestamp
quality:
  quarantine: {include_warnings: false}
target:
  kind: streaming_table
  cdc:
    keys: [id]
    sequence_by: ts
    scd_type: 1
"""


def test_local_profile_registers_materialized_views(spark, write_domain):
    for key, value in CONF.items():
        spark.conf.set(key, value)
    try:
        config_dir = write_domain({"silver/customers.yml": CDC_TABLE_YML})
        captured = capture_graph(spark, config_dir)
    finally:
        spark.conf.unset("datalab.profile")

    names = [name for _, name in captured]
    # The CDC streaming table is downgraded to a single batch materialized view,
    # registered under its SHORT name (OSS SDP qualifies it with the pipeline's
    # catalog/database so cross-dataset reads resolve).
    assert "customers" in names
    # The local profile must NOT emit AUTO CDC flows (the Databricks-only symbol
    # this downgrade exists to avoid)...
    assert not any(kind == "auto_cdc_flow" for kind, _ in captured)
    assert not any(str(name).endswith("__cdc_flow") for _, name in captured)
    # ...nor a quarantine table: dqx can't run inside an OSS SDP query function,
    # so quality is validated via run_dataset / make validate-connect instead.
    assert "customers_quarantine" not in names


def test_write_local_spec(write_domain, tmp_path):
    config_dir = write_domain({"silver/customers.yml": CDC_TABLE_YML})
    out = tmp_path / "spark-pipeline.yml"

    write_local_spec(
        config_dir=config_dir,
        transformations=tmp_path / "transformations",
        out=out,
        extra_conf={"datalab.sales_landing_path": "file:///tmp/landing"},
    )

    spec = yaml.safe_load(out.read_text())
    assert spec["name"] == "demo_local"
    # No top-level catalog/database: datasets resolve by short name in the graph.
    assert "catalog" not in spec
    assert "database" not in spec
    assert spec["libraries"][0]["glob"]["include"].endswith("/**")
    assert spec["storage"].startswith("file://")

    # Confs are spark.-prefixed so spark-submit keeps them (pipeline_conf reads
    # either form).
    conf = spec["configuration"]
    assert conf["spark.datalab.profile"] == "local"
    assert conf["spark.datalab.config_dir"] == str(config_dir.resolve())
    assert conf["spark.datalab.catalog"] == "spark_catalog"
    # all layers collapse onto the single local database
    assert conf["spark.datalab.bronze_schema"] == "default"
    assert conf["spark.datalab.silver_schema"] == "default"
    assert conf["spark.datalab.sales_landing_path"] == "file:///tmp/landing"
