"""Integration wrapper for the Databricks Labs DQX library.

This module provides a comprehensive wrapper around DQX functionality including:
- Data profiling and quality rule generation
- In-transit quality checks (during data processing)
- At-rest quality checks (on existing tables)
- Quality results and quarantine management

Reference: https://databrickslabs.github.io/dqx/docs/guide/
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime, timezone

from pyspark.sql import DataFrame, SparkSession

try:  # The library is optional in local unit tests but required in production deployments.
    from databricks.labs.dqx.config import InputConfig, OutputConfig, RunConfig
    from databricks.labs.dqx.engine import DQEngine
    from databricks.labs.dqx.quality_checker.quality_checker_runner import QualityCheckerRunner
    from databricks.sdk import WorkspaceClient
    
    # Profiler and rule generator may have different module paths in different DQX versions
    try:
        from databricks.labs.dqx.profiler.profiler import DQXProfiler
        from databricks.labs.dqx.profiler.rule_generator import DQGenerator
    except (ImportError, ModuleNotFoundError):
        try:
            from databricks.labs.dqx.profiler import DQXProfiler, DQGenerator  # type: ignore
        except (ImportError, ModuleNotFoundError):
            DQXProfiler = DQGenerator = None  # type: ignore
            
except Exception:  # pragma: no cover - makes local unit tests independent from these heavy deps
    InputConfig = OutputConfig = RunConfig = object  # type: ignore
    DQEngine = QualityCheckerRunner = WorkspaceClient = None  # type: ignore
    DQXProfiler = DQGenerator = None  # type: ignore


LOGGER = logging.getLogger(__name__)


class DqxRunner:
    """Comprehensive facade for DQX data quality operations.
    
    Supports:
    - Profiling data and generating quality rule candidates
    - Applying quality checks (in-transit and at-rest)
    - Managing quality results and quarantine data
    
    Reference: https://databrickslabs.github.io/dqx/docs/guide/
    """

    def __init__(
        self,
        spark: SparkSession,
        quality_config: Dict[str, Any],
        *,
        enabled: bool = True,
        workspace_client: WorkspaceClient | None = None,
        dq_engine: DQEngine | None = None,
        runner: QualityCheckerRunner | None = None,
        profiler: DQXProfiler | None = None,
        rule_generator: DQGenerator | None = None,
    ) -> None:
        self.spark = spark
        self._quality_config = quality_config
        self._checks_base_path = quality_config.get("checks_base_path")
        self._results_location = quality_config.get("results_table") or quality_config.get("results_path")
        self._quarantine_location = quality_config.get("quarantine_table") or quality_config.get("quarantine_path")
        self._audit_location = quality_config.get("audit_table") or quality_config.get("audit_path")
        self._output_format = quality_config.get("output_format", "delta")
        self._enabled = enabled
        self._runner: QualityCheckerRunner | None = None
        self._engine: DQEngine | None = None
        self._profiler: DQXProfiler | None = None
        self._rule_generator: DQGenerator | None = None

        if not enabled:
            LOGGER.info("DQX runner initialised in disabled mode.")
            return

        if WorkspaceClient is None:
            LOGGER.warning("databricks-labs-dqx is not available; disabling quality checks.")
            self._enabled = False
            return

        try:
            ws_client = workspace_client or WorkspaceClient()
            self._engine = dq_engine or DQEngine(ws_client, spark)
            self._runner = runner or QualityCheckerRunner(spark, self._engine)
            self._profiler = profiler or (DQXProfiler(spark) if DQXProfiler else None)
            self._rule_generator = rule_generator or (DQGenerator() if DQGenerator else None)
        except Exception as exc:  # pragma: no cover - depends on external auth
            LOGGER.warning("Failed to initialise DQX, continuing with checks disabled: %s", exc)
            self._enabled = False

    def run_checks(
        self,
        *,
        run_name: str,
        checks: List[Dict[str, Any]] | str,
        input_location: str,
        input_format: str = "delta",
        is_streaming: bool = False,
    ) -> None:
        """Execute DQX data-quality checks if the runner is enabled.

        Parameters
        ----------
        run_name: str
            Name for the DQ run
        checks: list | str
            Either a path to checks (YAML) or an inline list of rule dictionaries
        input_location: str
            Table name or path of the data to validate
        input_format: str
            Format of the input (default: delta)
        is_streaming: bool
            Whether the input is streaming
        """

        if not self._enabled or not self._runner:
            LOGGER.debug("DQX disabled - skipping checks for run '%s'.", run_name)
            return

        # Resolve checks location; if inline list provided, persist via engine
        if isinstance(checks, str):
            resolved_checks = self._resolve_checks_location(checks)
        else:
            if not self._engine:
                LOGGER.warning("DQX engine unavailable; cannot persist inline checks. Skipping checks.")
                return
            # Persist inline rules to a temporary path under repo tmp
            repo_root = Path(__file__).resolve().parents[3]
            inline_dir = repo_root / "tmp" / "quality" / "_inline"
            inline_dir.mkdir(parents=True, exist_ok=True)
            checks_path = (inline_dir / f"{run_name}.yaml").as_posix()
            self._engine.save_checks(checks, checks_path, format="yaml")
            resolved_checks = checks_path

        if not resolved_checks:
            raise ValueError("Unable to resolve DQX checks location.")

        run_config = RunConfig(
            name=run_name,
            input_config=InputConfig(location=input_location, format=input_format, is_streaming=is_streaming),
            output_config=self._output_config(self._results_location),
            quarantine_config=self._output_config(self._quarantine_location),
            checks_location=resolved_checks,
        )

        LOGGER.info("Running DQX checks '%s' on '%s'.", run_name, input_location)
        self._runner.run([run_config])

    def _output_config(self, location: str | None) -> OutputConfig | None:
        if not location:
            return None
        return OutputConfig(location=location, format=self._output_format, mode="append")

    def profile_and_generate_checks(
        self,
        *,
        data: DataFrame,
        output_path: str,
        sampling_fraction: float = 1.0,
        include_nullability: bool = True,
        include_uniqueness: bool = True,
        include_completeness: bool = True,
    ) -> List[Dict[str, Any]]:
        """Profile data and generate quality rule candidates.
        
        This implements the profiling capability from DQX for auto-generating
        quality checks based on data characteristics.
        
        Reference: https://databrickslabs.github.io/dqx/docs/guide/profiling-and-generation/
        
        Parameters
        ----------
        data:
            DataFrame to profile
        output_path:
            Path to save generated quality checks (YAML format)
        sampling_fraction:
            Fraction of data to sample for profiling (0.0 to 1.0)
        include_nullability:
            Generate null/not-null checks
        include_uniqueness:
            Generate uniqueness/duplicate checks
        include_completeness:
            Generate completeness checks
            
        Returns
        -------
        List[Dict[str, Any]]
            Generated quality rules as list of dictionaries
        """
        if not self._enabled or not self._profiler or not self._rule_generator:
            LOGGER.warning("DQX profiling disabled - skipping profile generation")
            return []
        
        try:
            LOGGER.info("Profiling data and generating quality checks...")
            
            # Profile the data
            profile_results = self._profiler.profile(data, sampling_fraction=sampling_fraction)
            
            # Generate quality rules from profile
            rules = self._rule_generator.generate(
                profile_results,
                include_nullability=include_nullability,
                include_uniqueness=include_uniqueness,
                include_completeness=include_completeness,
            )
            
            # Save rules to storage if engine is available
            if self._engine:
                resolved_path = self._resolve_checks_location(output_path)
                self._engine.save_checks(rules, resolved_path, format="yaml")
                LOGGER.info("Generated %d quality rules saved to %s", len(rules), resolved_path)
            
            return rules
            
        except Exception as exc:
            LOGGER.error("Failed to profile data and generate checks: %s", exc)
            return []
    
    def check_in_transit(
        self,
        *,
        data: DataFrame,
        checks: List[Dict[str, Any]] | str,
        quarantine_invalid: bool = True,
        run_name: str | None = None,
        target_identifier: str | None = None,
    ) -> DataFrame:
        """Apply in-transit quality checks to a DataFrame during processing.
        
        This implements in-transit checking where quality is validated on the fly
        while data is being processed, before it is written to storage.
        
        Reference: https://databrickslabs.github.io/dqx/docs/guide/applying-checks/#in-transit-checks
        
        Parameters
        ----------
        data:
            DataFrame to validate
        checks:
            Quality checks as list of rule dictionaries or path to checks file
        quarantine_invalid:
            If True, separate invalid rows into quarantine dataset
            
        Returns
        -------
        DataFrame
            Valid data (quarantined rows removed if quarantine_invalid=True)
        """
        if not self._enabled or not self._engine:
            LOGGER.debug("DQX disabled - skipping in-transit checks")
            return data
        
        try:
            # Load checks if path provided
            if isinstance(checks, str):
                resolved_checks = self._resolve_checks_location(checks)
                checks_list = self._engine.load_checks(resolved_checks)
            else:
                checks_list = checks
            
            # Apply checks
            result = self._engine.apply_checks(data, checks_list)
            
            # Handle quarantine
            if quarantine_invalid and self._quarantine_location:
                invalid_data = result.filter("_dq_status != 'valid'")
                if invalid_data.count() > 0:
                    quarantine_config = self._output_config(self._quarantine_location)
                    if quarantine_config:
                        invalid_data.write.format(self._output_format).mode("append").save(
                            quarantine_config.location
                        )
                        LOGGER.info("Quarantined %d invalid rows", invalid_data.count())
                # Write audit summary if configured
                if self._audit_location:
                    try:
                        self._write_audit_summary(
                            run_name=run_name or "in_transit",
                            target=target_identifier or "",
                            checks=checks_list,
                            total_count=result.count(),
                            invalid_count=invalid_data.count(),
                        )
                    except Exception as audit_exc:
                        LOGGER.warning("Failed to write audit summary: %s", audit_exc)
                
                # Return only valid data
                return result.filter("_dq_status = 'valid'").drop("_dq_status", "_dq_rules")
            
            return result
            
        except Exception as exc:
            LOGGER.error("Failed to apply in-transit quality checks: %s", exc)
            return data

    def _resolve_checks_location(self, location: str) -> str:
        path = Path(location)
        if path.is_absolute() or location.startswith("dbfs:") or location.startswith("/Workspace"):
            return path.as_posix()

        if self._checks_base_path:
            return (Path(self._checks_base_path) / location).as_posix()

        repo_root = Path(__file__).resolve().parents[3]
        return (repo_root / location).as_posix()

    def _write_audit_summary(
        self,
        *,
        run_name: str,
        target: str,
        checks: List[Dict[str, Any]],
        total_count: int,
        invalid_count: int,
    ) -> None:
        """Append a high-level audit record to the configured audit table/path.

        The audit captures run_name, target, check columns and types, timestamp,
        and counts of total vs invalid rows.
        """
        if not self._audit_location:
            return

        # Build summary row
        when_ts = datetime.now(timezone.utc)
        columns = [str(c.get("column")) for c in checks if isinstance(c, dict) and c.get("column")]
        kinds = [str(c.get("type")) for c in checks if isinstance(c, dict) and c.get("type")]

        row = [
            run_name,
            target,
            ",".join(sorted(set(columns))) if columns else None,
            ",".join(sorted(set(kinds))) if kinds else None,
            total_count,
            invalid_count,
            when_ts.isoformat(),
        ]

        schema = "run_name string, target string, columns string, checks string, total_count long, invalid_count long, when_utc string"
        df = self.spark.createDataFrame([tuple(row)], schema=schema)

        out = self._output_config(self._audit_location)
        if out is None:
            return
        df.write.format(self._output_format).mode("append").save(out.location)
