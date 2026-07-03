"""Contract tests for the python-file lane entry point (export_customer_summary).

The edge job's logic is deliberately thin — parameter parsing via
datalab.params.cli_params and a fail-fast guard on the export volume — but that
guard IS the lane's contract: a missing per-environment UC volume must abort
before Spark can create a dev-shaped directory tree in the wrong workspace.
These tests pin it without a live workspace (the guard runs before any
SparkSession is created).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "jobs" / "customer_sales"))

from export_customer_summary import main  # noqa: E402


def test_missing_export_volume_fails_fast_before_spark():
    with pytest.raises(FileNotFoundError, match="does not exist in this"):
        main(
            [
                "--catalog", "cat",
                "--gold-schema", "gold",
                "--export-path", "/Volumes/cat/exports/definitely-missing/",
            ]
        )


def test_missing_required_parameter_is_an_error():
    # cli_params names every missing flag and how to wire it in the job resource
    with pytest.raises(ValueError, match="gold_schema.*export_path"):
        main(["--catalog", "cat"])
