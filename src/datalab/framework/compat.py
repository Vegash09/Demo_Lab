"""Guards for Databricks-only LDP symbols.

OSS pyspark 4.1 ships ``pyspark.pipelines`` but not every Databricks SDP
capability (AUTO CDC, sinks). Framework modules must import cleanly under
local Spark for unit tests; anything Databricks-only goes through here so the
failure is actionable instead of an AttributeError."""

from __future__ import annotations

from typing import Any

from pyspark import pipelines as dp

from datalab.framework.errors import FrameworkRuntimeError

HAS_AUTO_CDC = hasattr(dp, "create_auto_cdc_flow")
HAS_SINKS = hasattr(dp, "create_sink") and hasattr(dp, "append_flow")

# Graph-capture hook (devtools.capture_graph): lets local graph inspection
# record Databricks-only registrations instead of failing on them.
_capture_handler: Any = None


def set_capture_handler(handler: Any) -> None:
    global _capture_handler
    _capture_handler = handler


def create_auto_cdc_flow(**kwargs: Any) -> None:
    if not HAS_AUTO_CDC:
        if _capture_handler is not None:
            _capture_handler("auto_cdc_flow", kwargs.get("name"))
            return
        raise FrameworkRuntimeError(
            f"dataset flow {kwargs.get('name')!r} needs dp.create_auto_cdc_flow, which "
            "only exists on the Databricks SDP runtime. Locally, use "
            "datalab.framework.run_dataset to verify the pre-CDC valid/quarantine "
            "frames; the SCD merge itself is verified with a dev refresh (make run)."
        )
    dp.create_auto_cdc_flow(**kwargs)


def create_sink(**kwargs: Any) -> None:
    if not HAS_SINKS:
        raise FrameworkRuntimeError(
            f"sink {kwargs.get('name')!r} needs dp.create_sink (Databricks SDP runtime "
            "only). Locally, use datalab.framework.run_dataset instead."
        )
    dp.create_sink(**kwargs)


def append_flow(**kwargs: Any) -> Any:
    if not HAS_SINKS:
        raise FrameworkRuntimeError(
            f"flow {kwargs.get('name')!r} needs dp.append_flow (Databricks SDP runtime "
            "only). Locally, use datalab.framework.run_dataset instead."
        )
    return dp.append_flow(**kwargs)
