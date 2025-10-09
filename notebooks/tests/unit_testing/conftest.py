import os
from pathlib import Path
import shutil
import pytest


def _local_spark_session():
    """Very simple Spark creator for tests.

    - If Databricks Connect is available AND configured (host/token or profile),
      return a remote DatabricksSession.
    - Otherwise, create a plain local SparkSession (master local[*]).
    """
    # Force local mode only (disable Spark Connect completely)
    for var in (
        "SPARK_REMOTE",
        "SPARK_CONNECT_MODE_ENABLED",
        "PYSPARK_ENABLE_CONNECT",
        "DEFAULT_CONNECT_URL",
    ):
        os.environ.pop(var, None)

    from pyspark.sql import SparkSession

    base_builder = (
        SparkSession.builder
        .appName("notebook-tests")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.shuffle.partitions", "4")
    )

    # Always use a plain local session; no Spark Connect fallback
    return base_builder.master("local[*]").getOrCreate()


@pytest.fixture(scope="session")
def spark_session():
    """Shared local SparkSession for unit tests (fast & simple)."""
    # Clean any leftover local warehouse to avoid permission issues
    delete_existing_spark_warehouse()
    try:
        spark = _local_spark_session()
    except Exception as exc:
        msg = str(exc)
        if "Only remote Spark sessions" in msg:
            pytest.skip(
                "Local SparkSession disabled by databricks-connect. "
                "Use a virtualenv without databricks-connect for unit tests, "
                "or run integration tests with the dbconnect fixture."
            )
        pytest.skip(f"Skipping Spark-dependent tests: unable to start Spark ({exc})")
        return
    try:
        yield spark
    finally:
        try:
            spark.stop()
        except Exception:
            pass
        delete_existing_spark_warehouse()


@pytest.fixture(scope="session")
def spark(spark_session):
    """Backward-compat alias to spark_session."""
    return spark_session


@pytest.fixture(scope="session")
def dbconnect_spark_session():
    """Databricks Connect SparkSession for integration tests.

    Requires databricks-connect and either env host/token or configured profile.
    Skips the test if not available.
    """
    try:
        from databricks.connect import DatabricksSession  # type: ignore
    except Exception:
        pytest.skip("databricks-connect is not installed; skipping dbconnect tests")
        return

    configured = bool(
        (os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN"))
        or os.getenv("DATABRICKS_CONFIG_PROFILE")
        or os.getenv("DATABRICKS_PROFILE")
    )
    if not configured:
        pytest.skip("Databricks Connect not configured; set host/token or profile")
        return

    try:
        spark = DatabricksSession.builder.getOrCreate()
    except Exception as exc:
        pytest.skip(f"Unable to create DatabricksSession via Connect: {exc}")
        return
    try:
        yield spark
    finally:
        try:
            spark.stop()
        except Exception:
            pass


def delete_existing_spark_warehouse():
    """Delete local spark-warehouse folder if it exists."""
    try:
        root = find_project_root(Path(__file__), "pyproject.toml")
    except Exception:
        root = Path(__file__).resolve().parents[3]
    warehouse = root / "spark-warehouse"
    if warehouse.exists():
        shutil.rmtree(warehouse, ignore_errors=True)


@pytest.fixture(scope="session")
def config_dir() -> Path:
    """Return repo config directory path (…/config)."""
    root = find_project_root(Path(__file__), "pyproject.toml")
    return root / "config"


def find_project_root(current_path: Path, marker: str) -> Path:
    """Find the repository root by searching upwards for a marker file."""
    path = current_path.resolve()
    while path != path.parent:
        if (path / marker).exists():
            return path
        path = path.parent
    raise FileNotFoundError(f"Marker '{marker}' not found from {current_path}")


# Reduce noisy third-party deprecation warnings from PySpark internals
def pytest_configure(config):  # noqa: D401 - pytest hook
    import warnings
    warnings.filterwarnings(
        "ignore",
        message=r".*distutils Version classes are deprecated.*",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*LooseVersion.*",
        category=DeprecationWarning,
    )

    # Add a custom marker for dbconnect-only tests to avoid unknown marker warnings
    config.addinivalue_line("markers", "dbconnect_only: run only when Databricks Connect is configured")


@pytest.hookimpl(optionalhook=True)
def pytest_collection_modifyitems(config, items):
    """Auto-skip dbconnect_only tests if Connect isn't configured."""
    have_connect = False
    try:
        from databricks.connect import DatabricksSession  # type: ignore  # noqa: F401
        have_connect = True
    except Exception:
        have_connect = False

    configured = bool(
        (os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN"))
        or os.getenv("DATABRICKS_CONFIG_PROFILE")
        or os.getenv("DATABRICKS_PROFILE")
    )

    if not (have_connect and configured):
        skip_marker = pytest.mark.skip(reason="Databricks Connect not configured")
        for item in items:
            if any(mark.name == "dbconnect_only" for mark in item.iter_markers()):
                item.add_marker(skip_marker)
