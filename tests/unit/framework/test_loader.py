"""Loader behavior: every failure is a ConfigError naming file + fix."""

import pytest

from datalab.framework.errors import ConfigError
from datalab.framework.loader import load_domain_configs

CUSTOMERS_YML = """
schema_version: 1
name: customers
source: {kind: table, name: customers_raw, layer: bronze, as_stream: true}
columns:
  - name: customer_id
    type: string
    quality:
      - criticality: error
        check: {function: is_not_null}
  - name: email
    type: string
transform:
  - function: sales.normalize_email
quality:
  quarantine: {}
target:
  kind: streaming_table
  cdc: {keys: [customer_id], sequence_by: customer_id}
"""


def test_valid_domain_loads(write_domain):
    cfgs = load_domain_configs(write_domain({"silver/customers.yml": CUSTOMERS_YML}), ["silver"])
    ds = cfgs[0].datasets[0]
    assert ds.quarantine_name() == "customers_quarantine"
    # source.layer resolved to the domain's schema conf key
    assert ds.source.schema_conf == "datalab.bronze_schema"
    # column rule got the target column + derived name injected
    assert ds.effective_checks()[0]["check"]["arguments"]["column"] == "customer_id"
    assert ds.effective_checks()[0]["name"] == "customer_id_is_not_null"


def test_missing_domain_yml(tmp_path):
    with pytest.raises(ConfigError, match="domain.yml"):
        load_domain_configs(tmp_path)


def test_file_name_must_match_table_name(write_domain):
    config_dir = write_domain({"silver/wrong_name.yml": CUSTOMERS_YML})
    with pytest.raises(ConfigError, match="file name == table name"):
        load_domain_configs(config_dir, ["silver"])


def test_unknown_source_layer(write_domain):
    bad = CUSTOMERS_YML.replace("layer: bronze", "layer: gold")
    domain_without_gold = """
schema_version: 1
domain: sales
imports: [sales_etl.transforms.sales]
layers:
  bronze: {schema_conf: datalab.bronze_schema}
  silver: {schema_conf: datalab.silver_schema}
"""
    config_dir = write_domain({"silver/customers.yml": bad}, domain_without_gold)
    with pytest.raises(ConfigError, match="layers"):
        load_domain_configs(config_dir, ["silver"])


def test_typoed_key_reports_dotted_path(write_domain):
    bad = CUSTOMERS_YML.replace("sequence_by", "sequence_byy")
    config_dir = write_domain({"silver/customers.yml": bad})
    with pytest.raises(ConfigError, match=r"target"):
        load_domain_configs(config_dir, ["silver"])


def test_unknown_transform_lists_registered_names(write_domain):
    bad = CUSTOMERS_YML.replace("sales.normalize_email", "sales.does_not_exist")
    config_dir = write_domain({"silver/customers.yml": bad})
    with pytest.raises(ConfigError, match="unknown transform .*sales.does_not_exist"):
        load_domain_configs(config_dir, ["silver"])


def test_invalid_dqx_check_fails_at_load(write_domain):
    bad = CUSTOMERS_YML.replace("is_not_null", "no_such_dqx_function")
    config_dir = write_domain({"silver/customers.yml": bad})
    with pytest.raises(ConfigError, match="invalid dqx checks"):
        load_domain_configs(config_dir, ["silver"])


def test_dataset_level_check_blocked_on_streaming(write_domain):
    bad = CUSTOMERS_YML.replace(
        "quality:\n  quarantine: {}",
        "quality:\n  quarantine: {}\n  checks:\n"
        "    - criticality: error\n"
        "      check: {function: is_unique, arguments: {columns: [customer_id]}}",
    )
    config_dir = write_domain({"silver/customers.yml": bad})
    with pytest.raises(ConfigError, match="micro-batch"):
        load_domain_configs(config_dir, ["silver"])


def test_dataset_level_check_opt_out(write_domain):
    allowed = CUSTOMERS_YML.replace(
        "quality:\n  quarantine: {}",
        "quality:\n  quarantine: {}\n  allow_streaming_dataset_checks: true\n  checks:\n"
        "    - criticality: error\n"
        "      check: {function: is_unique, arguments: {columns: [customer_id]}}",
    )
    config_dir = write_domain({"silver/customers.yml": allowed})
    cfgs = load_domain_configs(config_dir, ["silver"])
    assert cfgs[0].datasets[0].quality.allow_streaming_dataset_checks


def test_ref_df_key_mismatch(write_domain):
    bad = CUSTOMERS_YML.replace(
        "quality:\n  quarantine: {}",
        "quality:\n  quarantine: {}\n  allow_streaming_dataset_checks: true\n  checks:\n"
        "    - criticality: error\n"
        "      check:\n"
        "        function: foreign_key\n"
        "        arguments: {columns: [customer_id], ref_columns: [id], ref_df_name: dim_x}",
    )
    config_dir = write_domain({"silver/customers.yml": bad})
    with pytest.raises(ConfigError, match="ref_df_name"):
        load_domain_configs(config_dir, ["silver"])


def test_unimportable_imports_module_is_config_error(write_domain):
    domain = """
schema_version: 1
domain: sales
imports: [no_such_pkg.transforms]
layers:
  silver: {schema_conf: datalab.silver_schema}
"""
    config_dir = write_domain({"silver/customers.yml": CUSTOMERS_YML}, domain)
    with pytest.raises(ConfigError, match="no_such_pkg"):
        load_domain_configs(config_dir, ["silver"])


def test_missing_dir_names_config_key():
    with pytest.raises(ConfigError, match="datalab.config_dir"):
        load_domain_configs("/nonexistent/config/dir")
