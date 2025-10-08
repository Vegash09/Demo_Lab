"""Helpers for creating Spark sessions for local development and Databricks jobs."""
from __future__ import annotations

import logging
import os
from typing import Mapping

from pyspark.sql import SparkSession

LOGGER = logging.getLogger(__name__)


def is_databricks_runtime() -> bool:
    """Check if running in Databricks environment.
    
    Returns
    -------
    bool
        True if running in Databricks, False otherwise.
    """
    # Check for Databricks-specific environment variables
    return (
        os.getenv("DATABRICKS_RUNTIME_VERSION") is not None
        or os.path.exists("/databricks")
        or "databricks" in os.getenv("SPARK_HOME", "").lower()
    )


def is_databricks_connect_available() -> bool:
    """Return True if databricks-connect package can be imported."""
    try:  # Import only to check availability; do not keep global reference
        import importlib  # noqa: F401
        from databricks import connect  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def is_databricks_connect_configured(profile: str | None = None) -> bool:
    """Heuristics to determine if Databricks Connect should be used locally.

    We consider it configured if either a profile is set or both host and token
    environment variables are present.
    """
    profile = profile or os.getenv("DATABRICKS_CONFIG_PROFILE") or os.getenv("DATABRICKS_PROFILE")
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")
    return bool(profile or (host and token))


def _get_databricks_connect_session(
    app_name: str,
    extra_conf: Mapping[str, str] | None,
    *,
    profile: str | None = None,
) -> SparkSession:
    """Create a DatabricksSession via databricks-connect when available/configured.

    Notes
    -----
    - Delta support is provided by the remote cluster; local Delta configs are not applied here.
    - ``extra_conf`` is forwarded to the builder via ``config``.
    """
    from databricks.connect import DatabricksSession  # type: ignore

    builder = DatabricksSession.builder

    env_profile = os.getenv("DATABRICKS_CONFIG_PROFILE") or os.getenv("DATABRICKS_PROFILE")
    host = os.getenv("DATABRICKS_HOST")
    token = os.getenv("DATABRICKS_TOKEN")

    # Prefer the explicit profile parameter; fallback to environment profile
    effective_profile = profile or env_profile
    if effective_profile:
        builder = builder.profile(effective_profile)
    if host:
        builder = builder.host(host)
    if token:
        builder = builder.token(token)

    builder = builder.config("spark.app.name", app_name)

    if extra_conf:
        for key, value in extra_conf.items():
            builder = builder.config(key, value)

    return builder.getOrCreate()


def get_spark(
    app_name: str = "DatalabETL",
    enable_delta: bool = True,
    extra_conf: Mapping[str, str] | None = None,
    force_local: bool = False,
    prefer_databricks_connect: bool = True,
    databricks_profile: str | None = None,
) -> SparkSession:
    """Return a configured :class:`~pyspark.sql.SparkSession`.

    Automatically detects if running in Databricks and returns the active session,
    or creates a new local session for development/testing.

    Parameters
    ----------
    app_name:
        Name applied to the Spark application (only for local sessions).
    enable_delta:
        When ``True`` the session is configured for Delta Lake support. This is a no-op on
        Databricks runtimes where Delta is enabled by default, but makes local development easier.
    extra_conf:
        Optional Spark configuration pairs to apply.
    force_local:
        Force creation of a local session even in Databricks environment (for testing).

    Returns
    -------
    SparkSession
        Active Spark session (Databricks) or new local session.
    """
    # Check if running in Databricks environment
    in_databricks = is_databricks_runtime() and not force_local
    
    if in_databricks:
        LOGGER.info("Detected Databricks runtime - using active SparkSession")
        spark = SparkSession.getActiveSession()
        
        if spark is None:
            # Fallback: this should rarely happen in Databricks
            LOGGER.warning("No active session in Databricks - creating new session")
            spark = SparkSession.builder.getOrCreate()
        
        return spark
    
    # Databricks Connect (local → remote cluster)
    if (
        prefer_databricks_connect
        and not in_databricks
        and not force_local
        and is_databricks_connect_available()
        and is_databricks_connect_configured(databricks_profile)
    ):
        LOGGER.info("Using Databricks Connect - creating remote DatabricksSession")
        try:
            return _get_databricks_connect_session(app_name, extra_conf, profile=databricks_profile)
        except Exception as exc:  # pragma: no cover - environment dependent
            LOGGER.warning("Failed to create Databricks Connect session, falling back to local: %s", exc)

    # Local development session
    LOGGER.info("Creating local SparkSession for development")
    builder = SparkSession.builder.appName(app_name)

    if enable_delta:
        builder = (
            builder.config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        )

    # Local-friendly defaults
    builder = (
        builder.config("spark.sql.shuffle.partitions", "4")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.adaptive.enabled", "true")
    )

    if extra_conf:
        for key, value in extra_conf.items():
            builder = builder.config(key, value)

    spark = builder.getOrCreate()

    # Reduce noise in local unit/integration tests (skip for Spark Connect)
    try:  # sparkContext is not available on Spark Connect sessions
        sc = getattr(spark, "sparkContext", None)
        if sc is not None:
            sc.setLogLevel("WARN")
    except Exception:  # pragma: no cover - environment dependent
        LOGGER.debug("Skipped setting log level; Spark Connect session has no sparkContext")

    return spark
