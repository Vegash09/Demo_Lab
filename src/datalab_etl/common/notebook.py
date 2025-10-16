"""Helper utilities for Databricks notebooks."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def has_dbutils() -> bool:
    """Check if running in Databricks with dbutils available.
    
    Returns
    -------
    bool
        True if dbutils is available, False otherwise.
    """
    try:
        # Import is fine locally, but global dbutils handle only exists in Databricks
        from pyspark.dbutils import DBUtils  # type: ignore  # noqa: F401
        import __main__
        return bool(getattr(__main__, "dbutils", None) is not None)
    except Exception:
        return False


def get_widget_value(name: str, default: str = "", label: str | None = None) -> str:
    """Get or create a Databricks widget and return its value.
    
    If running in Databricks, creates a text widget and returns its value.
    If running locally, returns the default value.
    
    Parameters
    ----------
    name : str
        Widget name
    default : str, optional
        Default value (used both as widget default and local fallback)
    label : str, optional
        Widget label (defaults to name if not provided)
        
    Returns
    -------
    str
        Widget value in Databricks, or default value locally
        
    Examples
    --------
    >>> config_path = get_widget_value("config_path", "", "Config Path")
    """
    if has_dbutils():
        import __main__
        dbutils = getattr(__main__, "dbutils")
        widget_label = label or name
        dbutils.widgets.text(name, default, widget_label)
        return dbutils.widgets.get(name)
    return default


def load_config(config_path: str) -> dict[str, Any]:
    """Load JSON configuration file.
    
    Parameters
    ----------
    config_path : str
        Path to JSON config file
        
    Returns
    -------
    dict
        Loaded configuration, or empty dict if path is empty or file doesn't exist
        
    Examples
    --------
    >>> cfg = load_config("/path/to/config.json")
    >>> source = cfg.get("source", {})
    """
    if not config_path:
        return {}
    
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        LOGGER.warning(f"Config file not found: {config_path}")
        return {}
    except json.JSONDecodeError as e:
        LOGGER.error(f"Invalid JSON in config file {config_path}: {e}")
        return {}


def load_quality_config(
    dq_config_path: str = "",
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load data quality configuration from file or base config.
    
    Priority:
    1. If dq_config_path is provided, load from that file
    2. Otherwise, try to extract from base_config["quality"]
    3. Return empty dict if neither is available
    
    Parameters
    ----------
    dq_config_path : str, optional
        Path to DQ config file (JSON)
    base_config : dict, optional
        Base pipeline config that may contain "quality" key
        
    Returns
    -------
    dict
        Quality configuration with normalized structure
        
    Examples
    --------
    >>> # From dedicated DQ file
    >>> dq_cfg = load_quality_config(dq_config_path="/path/to/dq.json")
    
    >>> # From main config
    >>> cfg = load_config("/path/to/pipeline.json")
    >>> dq_cfg = load_quality_config(base_config=cfg)
    """
    # Try loading from dedicated DQ config file
    if dq_config_path:
        loaded = load_config(dq_config_path)
        if loaded:
            # Normalize: if it's a list, wrap in {"checks": [...]}
            if isinstance(loaded, list):
                return {"checks": loaded}
            return loaded
    
    # Fallback to base config's quality section
    if base_config:
        quality = base_config.get("quality")
        if isinstance(quality, dict):
            return quality.copy()
    
    return {}


def setup_notebook_config(
    config_widget_name: str = "config_path",
    dq_widget_name: str = "dq_config_path",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Setup notebook configuration with widgets and loading.
    
    This is a convenience function that:
    1. Creates Databricks widgets (or uses defaults locally)
    2. Loads main config file
    3. Loads quality config file
    4. Returns both configs ready to use
    
    Parameters
    ----------
    config_widget_name : str, optional
        Name of the config path widget
    dq_widget_name : str, optional
        Name of the DQ config path widget
        
    Returns
    -------
    tuple[dict, dict]
        (main_config, quality_config)
        
    Examples
    --------
    >>> # Simple one-liner to get both configs
    >>> cfg, dq_cfg = setup_notebook_config()
    >>> 
    >>> # Use in process_batch
    >>> process_batch(
    ...     spark,
    ...     source=cfg["source"],
    ...     transform=my_transform,
    ...     target=cfg["target"],
    ...     dq_config=dq_cfg,
    ... )
    """
    # Get widget values (creates widgets in Databricks, returns "" locally)
    config_path = get_widget_value(config_widget_name, "", "Config Path")
    dq_config_path = get_widget_value(dq_widget_name, "", "DQ Config Path")
    
    # Load configurations
    main_config = load_config(config_path)
    quality_config = load_quality_config(dq_config_path, main_config)
    
    return main_config, quality_config

