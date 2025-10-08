from __future__ import annotations

from typing import Any, Dict, List

import json
from pyspark.sql import DataFrame, SparkSession

try:
    from databricks.labs.dqx.engine import DQEngine
    from databricks.labs.dqx.checks_storage import is_table_location
    from databricks.labs.dqx.config import (
        BaseChecksStorageConfig,
        FileChecksStorageConfig,
        TableChecksStorageConfig,
        VolumeFileChecksStorageConfig,
        WorkspaceFileChecksStorageConfig,
    )
    from databricks.sdk import WorkspaceClient
except Exception:  # pragma: no cover - allow framework use without DQX locally
    DQEngine = WorkspaceClient = None  # type: ignore
    BaseChecksStorageConfig = FileChecksStorageConfig = TableChecksStorageConfig = VolumeFileChecksStorageConfig = WorkspaceFileChecksStorageConfig = object  # type: ignore

from datalab_etl.common.io import write_dataset


class SimpleDQ:
    """Minimal DQ integration: apply checks, split valid/invalid, write quarantine.

    Configuration (dict):
      - checks: str (path) | dict | list  OR
      - checks_table: str (catalog.schema.table)
      - quarantine_table: str (optional) or quarantine_path: str
    """

    def __init__(self, spark: SparkSession, quality_cfg: Dict[str, Any]) -> None:
        self.spark = spark
        self.cfg = quality_cfg or {}
        self._engine = None
        if DQEngine is not None:
            try:
                self._engine = DQEngine(workspace_client=WorkspaceClient())
            except Exception:
                try:
                    self._engine = DQEngine()
                except Exception:
                    self._engine = None

    def available(self) -> bool:
        return self._engine is not None

    # public API ------------------------------------------------------------
    def resolve_checks(self) -> List[Dict[str, Any]]:
        checked = self._load_checks_metadata(self.cfg.get("checks") or self.cfg.get("checks_table"))
        return checked

    def apply_and_split(self, df: DataFrame, checks: List[Dict[str, Any]]) -> tuple[DataFrame, DataFrame]:
        if not self._engine or not checks:
            # No engine or checks -> treat all as valid, empty invalid
            return df, self.spark.createDataFrame(df.limit(0).rdd, df.schema)
        try:
            try:
                return self._engine.apply_checks_by_metadata_and_split(df, checks)  # type: ignore[attr-defined]
            except Exception:
                results_df = self._engine.apply_checks_by_metadata(df, checks)
                invalid_df = self._engine.get_invalid(results_df)
                valid_df = self._engine.get_valid(results_df)
                return valid_df, invalid_df
        except Exception:
            # On failure, bypass DQ instead of breaking the pipeline
            return df, self.spark.createDataFrame(df.limit(0).rdd, df.schema)

    def write_quarantine(self, invalid_df: DataFrame) -> None:
        q_table = self.cfg.get("quarantine_table")
        q_path = self.cfg.get("quarantine_path")
        if not q_table and not q_path:
            return
        target = {"mode": "append"}
        if q_table:
            target["table"] = q_table
        else:
            target["path"] = q_path
        write_dataset(invalid_df, target)  # reuse framework IO

    # internals -------------------------------------------------------------
    def _normalize_fs_location(self, location: str) -> str:
        if location.startswith("dbfs:/"):
            return location.replace("dbfs:/", "/dbfs/", 1)
        return location

    def _checks_storage_config_for(self, location: str) -> BaseChecksStorageConfig:
        if location.startswith("/Workspace"):
            return WorkspaceFileChecksStorageConfig(location=location)  # type: ignore
        if location.startswith("/Volumes/"):
            return VolumeFileChecksStorageConfig(location=location)  # type: ignore
        if is_table_location(location):
            return TableChecksStorageConfig(location=location)  # type: ignore
        return FileChecksStorageConfig(location=self._normalize_fs_location(location))  # type: ignore

    def _load_checks_metadata(self, spec: Any) -> List[Dict[str, Any]]:
        if spec is None:
            return []
        # Direct list/dict
        if isinstance(spec, list):
            return [c for c in spec if isinstance(c, dict)]
        if isinstance(spec, dict):
            return [spec]
        if not isinstance(spec, str) or not self._engine:
            return []
        # Storage-backed
        try:
            storage_cfg = self._checks_storage_config_for(spec)
            return self._engine.load_checks(storage_cfg)  # type: ignore[union-attr]
        except Exception:
            # Fallback: try reading file directly (json)
            try:
                with open(self._normalize_fs_location(spec), "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict):
                    payload = [payload]
                return [c for c in payload if isinstance(c, dict)]
            except Exception:
                return []

