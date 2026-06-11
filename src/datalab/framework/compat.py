"""Guards for Databricks-only LDP symbols.

OSS pyspark 4.1 ships ``pyspark.pipelines`` but not every Databricks SDP
capability: the AUTO CDC functions are absent entirely, and shared functions
lack Databricks-only parameters (``once``/``comment`` on append_flow,
``cluster_by_auto``, MV ``refresh_policy``). Framework modules must import
cleanly under local Spark for unit tests; every Databricks-only symbol or
parameter goes through here so the failure is actionable instead of an
AttributeError/TypeError. During graph capture (devtools.capture_graph) the
unsupported parameters are dropped — capture only inspects the graph shape;
the Databricks runtime receives them all."""

from __future__ import annotations

import inspect
from typing import Any

from pyspark import pipelines as dp

from datalab.framework.errors import FrameworkRuntimeError

HAS_AUTO_CDC = hasattr(dp, "create_auto_cdc_flow")
HAS_SNAPSHOT_CDC = hasattr(dp, "create_auto_cdc_from_snapshot_flow")
HAS_SINKS = hasattr(dp, "create_sink") and hasattr(dp, "append_flow")

# Graph-capture hook (devtools.capture_graph): lets local graph inspection
# record Databricks-only registrations instead of failing on them.
_capture_handler: Any = None


def set_capture_handler(handler: Any) -> None:
    global _capture_handler
    _capture_handler = handler


def _runtime_kwargs(fn: Any, kwargs: dict[str, Any], *, label: str) -> dict[str, Any]:
    """Keep only the kwargs this runtime's ``pyspark.pipelines`` accepts.

    Outside capture mode, dropping a parameter would silently change
    semantics (e.g. ``once``), so it raises instead."""
    params = inspect.signature(fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    supported = {k: v for k, v in kwargs.items() if k in params}
    dropped = sorted(set(kwargs) - set(supported))
    if dropped and _capture_handler is None:
        raise FrameworkRuntimeError(
            f"{label}: parameter(s) {dropped} are not supported by this runtime's "
            "pyspark.pipelines (Databricks-only). Deploy to verify them; locally "
            "use datalab.framework.capture_graph / run_dataset."
        )
    return supported


def table(query_function: Any, **kwargs: Any) -> Any:
    return dp.table(
        query_function, **_runtime_kwargs(dp.table, kwargs, label=f"table {kwargs.get('name')!r}")
    )


def materialized_view(query_function: Any, **kwargs: Any) -> Any:
    return dp.materialized_view(
        query_function,
        **_runtime_kwargs(
            dp.materialized_view, kwargs, label=f"materialized view {kwargs.get('name')!r}"
        ),
    )


def create_streaming_table(**kwargs: Any) -> None:
    dp.create_streaming_table(
        **_runtime_kwargs(
            dp.create_streaming_table, kwargs, label=f"streaming table {kwargs.get('name')!r}"
        )
    )


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


def create_auto_cdc_from_snapshot_flow(**kwargs: Any) -> None:
    if not HAS_SNAPSHOT_CDC:
        if _capture_handler is not None:
            _capture_handler("auto_cdc_from_snapshot_flow", kwargs.get("name"))
            return
        raise FrameworkRuntimeError(
            f"dataset flow {kwargs.get('name')!r} needs "
            "dp.create_auto_cdc_from_snapshot_flow (Databricks SDP runtime only). "
            "Locally, use datalab.framework.run_dataset to verify the prepared "
            "snapshot frame; the diff/SCD merge is verified with a dev refresh."
        )
    dp.create_auto_cdc_from_snapshot_flow(**kwargs)


def create_sink(**kwargs: Any) -> None:
    if not HAS_SINKS:
        raise FrameworkRuntimeError(
            f"sink {kwargs.get('name')!r} needs dp.create_sink (Databricks SDP runtime "
            "only). Locally, use datalab.framework.run_dataset instead."
        )
    dp.create_sink(**kwargs)


def append_flow(**kwargs: Any) -> Any:
    if not hasattr(dp, "append_flow"):
        raise FrameworkRuntimeError(
            f"flow {kwargs.get('name')!r} needs dp.append_flow (Databricks SDP runtime "
            "only). Locally, use datalab.framework.run_dataset instead."
        )
    return dp.append_flow(
        **_runtime_kwargs(dp.append_flow, kwargs, label=f"flow {kwargs.get('name')!r}")
    )
