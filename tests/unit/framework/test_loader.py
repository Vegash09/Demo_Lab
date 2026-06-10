"""Loader behavior: every failure is a ConfigError naming file + fix."""

import pytest

from datalab.framework.errors import ConfigError
from datalab.framework.loader import load_domain_configs, load_layer_config

VALID_SILVER = """
schema_version: 1
domain: sales
layer: silver
defaults:
  schema_conf: datalab.silver_schema
datasets:
  - name: customers
    source: {kind: table, name: customers_raw, as_stream: true}
    transform:
      - function: sales.clean_customers
    quality:
      checks:
        - name: valid_id
          criticality: error
          check: {function: is_not_null, arguments: {column: customer_id}}
      quarantine: {}
    target:
      kind: streaming_table
      cdc: {keys: [customer_id], sequence_by: _ingest_ts}
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_valid_layer_loads(tmp_path):
    cfg = load_layer_config(_write(tmp_path, "silver.yml", VALID_SILVER))
    assert cfg.datasets[0].quarantine_name() == "customers_quarantine"


def test_invalid_yaml_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_layer_config(_write(tmp_path, "silver.yml", "datasets: [unclosed"))


def test_typoed_key_reports_dotted_path(tmp_path):
    bad = VALID_SILVER.replace("sequence_by", "sequence_byy")
    with pytest.raises(ConfigError, match=r"datasets\.0\.target"):
        load_layer_config(_write(tmp_path, "silver.yml", bad))


def test_unknown_transform_lists_registered_names(tmp_path):
    bad = VALID_SILVER.replace("sales.clean_customers", "sales.does_not_exist")
    _write(tmp_path, "silver.yml", bad)
    with pytest.raises(ConfigError, match="unknown transform .*sales.does_not_exist"):
        load_domain_configs(tmp_path, ["silver"])


def test_invalid_dqx_check_fails_at_load(tmp_path):
    bad = VALID_SILVER.replace("is_not_null", "no_such_dqx_function")
    _write(tmp_path, "silver.yml", bad)
    with pytest.raises(ConfigError, match="invalid dqx checks"):
        load_domain_configs(tmp_path, ["silver"])


def test_dataset_level_check_blocked_on_streaming(tmp_path):
    bad = VALID_SILVER.replace(
        "check: {function: is_not_null, arguments: {column: customer_id}}",
        "check: {function: is_unique, arguments: {columns: [customer_id]}}",
    )
    _write(tmp_path, "silver.yml", bad)
    with pytest.raises(ConfigError, match="micro-batch"):
        load_domain_configs(tmp_path, ["silver"])


def test_dataset_level_check_opt_out(tmp_path):
    allowed = VALID_SILVER.replace(
        "check: {function: is_not_null, arguments: {column: customer_id}}",
        "check: {function: is_unique, arguments: {columns: [customer_id]}}",
    ).replace("quarantine: {}", "quarantine: {}\n      allow_streaming_dataset_checks: true")
    _write(tmp_path, "silver.yml", allowed)
    cfgs = load_domain_configs(tmp_path, ["silver"])
    assert cfgs[0].datasets[0].quality.allow_streaming_dataset_checks


def test_ref_df_key_mismatch(tmp_path):
    bad = VALID_SILVER.replace(
        "check: {function: is_not_null, arguments: {column: customer_id}}",
        "check: {function: foreign_key, arguments: {columns: [customer_id], ref_columns: [id], ref_df_name: dim_x}}",
    ).replace("quarantine: {}", "quarantine: {}\n      allow_streaming_dataset_checks: true")
    _write(tmp_path, "silver.yml", bad)
    with pytest.raises(ConfigError, match="ref_df_name"):
        load_domain_configs(tmp_path, ["silver"])


def test_layer_file_mismatch(tmp_path):
    _write(tmp_path, "gold.yml", VALID_SILVER)
    with pytest.raises(ConfigError, match="declares layer"):
        load_domain_configs(tmp_path, ["gold"])


def test_missing_dir_names_config_key():
    with pytest.raises(ConfigError, match="datalab.config_dir"):
        load_domain_configs("/nonexistent/config/dir")
