"""Tests for the non-SDP parameter helpers (no Spark needed)."""

import pytest

from datalab.params import cli_params, notebook_params


class _FakeWidgets:
    def __init__(self, values):
        self._values = values

    def get(self, name):
        if name not in self._values:
            raise RuntimeError(f"no widget named {name}")
        return self._values[name]


class _FakeDbutils:
    def __init__(self, values):
        self.widgets = _FakeWidgets(values)


def test_notebook_params_resolves_values():
    dbutils = _FakeDbutils({"catalog": "cat", "silver_schema": "silver"})
    assert notebook_params(dbutils, ["catalog", "silver_schema"]) == {
        "catalog": "cat",
        "silver_schema": "silver",
    }


def test_notebook_params_missing_widget_fails_fast():
    dbutils = _FakeDbutils({"catalog": "cat"})
    with pytest.raises(ValueError, match="base_parameters"):
        notebook_params(dbutils, ["catalog", "silver_schema"])


def test_notebook_params_empty_value_counts_as_missing():
    dbutils = _FakeDbutils({"catalog": ""})
    with pytest.raises(ValueError, match="catalog"):
        notebook_params(dbutils, ["catalog"])


def test_cli_params_parses_kebab_case_flags():
    argv = ["--catalog", "cat", "--gold-schema", "gold", "--export-path", "/Volumes/x"]
    assert cli_params(argv, ["catalog", "gold_schema", "export_path"]) == {
        "catalog": "cat",
        "gold_schema": "gold",
        "export_path": "/Volumes/x",
    }


def test_cli_params_missing_flag_fails_fast():
    with pytest.raises(ValueError, match="export_path"):
        cli_params(["--catalog", "cat"], ["catalog", "export_path"])
