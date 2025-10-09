import os
from pathlib import Path
import shutil
import pytest

try:  # Load env from repo root and Databricks env if present (optional)
    from dotenv import load_dotenv  # type: ignore
    _root = None
    try:
        _root = Path(__file__).resolve()
        while _root != _root.parent and not (_root / "pyproject.toml").exists():
            _root = _root.parent

        # Load repo-root .env first (lowest precedence)
        if (_root / ".env").exists():
            load_dotenv((_root / ".env").as_posix(), override=False)
        else:
            load_dotenv(override=False)

        # Then load VS Code Databricks env if available (does not override existing)
        dbx_env = _root / ".databricks/.databricks.env"
        if dbx_env.exists():
            load_dotenv(dbx_env.as_posix(), override=False)
    except Exception:
        # Best-effort only
        pass
except Exception:
    pass


def pytest_addoption(parser):
    parser.addoption(
        "--databricks-profile",
        action="store",
        default=None,
        help="Databricks CLI profile to use for dbconnect integration tests",
    )


@pytest.fixture(scope="session")
def dbconnect_spark_session(pytestconfig):
    """Databricks Connect SparkSession for integration tests.

    Requires databricks-connect and either env host/token or configured profile.
    Skips the test if not available.
    """
    try:
        from databricks.connect import DatabricksSession  # type: ignore
    except Exception:
        pytest.skip("databricks-connect is not installed; skipping dbconnect tests")
        return

    # Optionally set profile from pytest arg if provided
    profile_opt = pytestconfig.getoption("--databricks-profile")
    if profile_opt:
        os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile_opt)
        os.environ.setdefault("DATABRICKS_PROFILE", profile_opt)

    # Attempt to create a session and pass through cluster/serverless selection if provided via env
    try:
        builder = DatabricksSession.builder

        # Apply auth/target if available via env (best-effort; no-ops if methods absent)
        host = os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_URL")
        token = os.getenv("DATABRICKS_TOKEN")
        profile_env = os.getenv("DATABRICKS_CONFIG_PROFILE") or os.getenv("DATABRICKS_PROFILE")
        cluster_id = os.getenv("DATABRICKS_CLUSTER_ID") or os.getenv("CLUSTER_ID")
        use_serverless = os.getenv("DATABRICKS_USE_SERVERLESS") or os.getenv("USE_SERVERLESS")

        if profile_env and hasattr(builder, "profile"):
            builder = builder.profile(profile_env)
        if host and hasattr(builder, "host"):
            builder = builder.host(host)
        if token and hasattr(builder, "token"):
            builder = builder.token(token)

        # Prefer explicit cluster id when provided; otherwise allow opting into serverless
        if cluster_id:
            # Try API methods first, then fall back to config key used by Connect
            if hasattr(builder, "clusterId"):
                builder = builder.clusterId(cluster_id)  # type: ignore[attr-defined]
            elif hasattr(builder, "cluster_id"):
                builder = builder.cluster_id(cluster_id)  # type: ignore[attr-defined]
            else:
                builder = builder.config("spark.databricks.service.clusterId", cluster_id)
        elif use_serverless and use_serverless not in {"0", "false", "False", ""}:
            if hasattr(builder, "serverless"):
                builder = builder.serverless(True)  # type: ignore[attr-defined]
            elif hasattr(builder, "useServerless"):
                builder = builder.useServerless(True)  # type: ignore[attr-defined]
            else:
                builder = builder.config("spark.databricks.service.serverless", "true")

        spark = builder.getOrCreate()
    except Exception as exc:
        pytest.skip(
            "Databricks Connect not configured or unavailable; "
            "set DATABRICKS_HOST/TOKEN or DATABRICKS_PROFILE, or pass --databricks-profile. "
            f"Error: {exc}"
        )
        return
    try:
        yield spark
    finally:
        try:
            spark.stop()
        except Exception:
            pass


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


def _delete_existing_spark_warehouse():
    """Delete local spark-warehouse folder if it exists (cleanup)."""
    try:
        root = find_project_root(Path(__file__), "pyproject.toml")
    except Exception:
        root = Path(__file__).resolve().parents[3]
    warehouse = root / "spark-warehouse"
    if warehouse.exists():
        shutil.rmtree(warehouse, ignore_errors=True)


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
    # Ensure marker is known even if pyproject isn't read
    config.addinivalue_line(
        "markers",
        "dbconnect_only: run only when Databricks Connect is configured",
    )
    # If CLI provided a profile, propagate to env variables for subprocesses
    try:
        profile_opt = config.getoption("--databricks-profile")
    except Exception:
        profile_opt = None
    if profile_opt:
        os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile_opt)
        os.environ.setdefault("DATABRICKS_PROFILE", profile_opt)


@pytest.hookimpl(optionalhook=True)
def pytest_collection_modifyitems(config, items):
    """Auto-skip dbconnect_only tests if Connect isn't configured."""
    have_connect = False
    try:
        from databricks.connect import DatabricksSession  # type: ignore  # noqa: F401
        have_connect = True
    except Exception:
        have_connect = False

    # We no longer rely solely on env checks; if import is missing, skip marked tests
    if not have_connect:
        skip_marker = pytest.mark.skip(reason="Databricks Connect not configured")
        for item in items:
            if any(mark.name == "dbconnect_only" for mark in item.iter_markers()):
                item.add_marker(skip_marker)
