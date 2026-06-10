"""Pydantic models for the per-layer YAML configs.

Serverless env v4 preinstalls pydantic 2.10.6 — nothing here may use 2.11+
features. All models are frozen and reject unknown keys so a typo'd YAML key
fails loudly with a dotted path instead of being silently ignored.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# UC object / dataset names; deliberately stricter than what UC allows.
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
# Pipeline-configuration keys (resolved via datalab.config.pipeline_conf) —
# locations are ALWAYS conf keys, never literal catalogs/schemas/paths.
ConfKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][\w.]*$")]


class ConfigBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


# --------------------------------------------------------------------------
# Sources (discriminated on `kind`)
# --------------------------------------------------------------------------
class CloudFilesSource(ConfigBase):
    kind: Literal["cloud_files"]
    path_conf: ConfKey
    format: Literal["json", "csv", "parquet", "avro"] = "json"
    options: dict[str, str] = {}
    # NOT named `schema` — that shadows BaseModel.schema.
    schema_hints: str | None = None
    add_lineage: bool = True


class TableSource(ConfigBase):
    kind: Literal["table"]
    name: Identifier
    catalog_conf: ConfKey | None = None  # None -> layer defaults
    schema_conf: ConfKey | None = None  # None -> layer defaults
    as_stream: bool = False


class ViewSource(ConfigBase):
    """A temporary view generated earlier in the same pipeline."""

    kind: Literal["view"]
    name: Identifier
    as_stream: bool = True


SourceSpec = Annotated[
    CloudFilesSource | TableSource | ViewSource, Field(discriminator="kind")
]


# --------------------------------------------------------------------------
# Targets (discriminated on `kind`)
# --------------------------------------------------------------------------
class CdcSpec(ConfigBase):
    keys: list[Identifier] = Field(min_length=1)
    sequence_by: str
    scd_type: Literal[1, 2] = 1
    apply_as_deletes: str | None = None
    except_columns: list[str] = []
    ignore_null_updates: bool = False
    track_history_except_columns: list[str] = []

    @model_validator(mode="after")
    def _keys_not_excluded(self) -> CdcSpec:
        clash = set(self.keys) & set(self.except_columns)
        if clash:
            raise ValueError(f"cdc.keys {sorted(clash)} cannot also be in cdc.except_columns")
        if self.sequence_by in self.except_columns:
            raise ValueError(f"cdc.sequence_by {self.sequence_by!r} cannot be in cdc.except_columns")
        return self


class StreamingTableTarget(ConfigBase):
    kind: Literal["streaming_table"]
    cdc: CdcSpec | None = None
    partition_cols: list[str] = []
    cluster_by: list[str] = []
    table_properties: dict[str, str] = {}
    table_schema: str | None = Field(None, alias="schema")


class MaterializedViewTarget(ConfigBase):
    kind: Literal["materialized_view"]
    partition_cols: list[str] = []
    cluster_by: list[str] = []
    table_properties: dict[str, str] = {}


class TemporaryViewTarget(ConfigBase):
    """Pipeline-scoped ('dynamic') view — no table is materialized."""

    kind: Literal["temporary_view"]


class DeltaSinkTarget(ConfigBase):
    """Streaming append to a delta table/path OUTSIDE pipeline management
    (dp.create_sink + dp.append_flow). Prefer materialized_view for ordinary
    batch tables — this is for external destinations only."""

    kind: Literal["delta_sink"]
    table_conf: ConfKey | None = None
    path_conf: ConfKey | None = None
    options: dict[str, str] = {}

    @model_validator(mode="after")
    def _exactly_one_destination(self) -> DeltaSinkTarget:
        if bool(self.table_conf) == bool(self.path_conf):
            raise ValueError("delta_sink needs exactly one of table_conf or path_conf")
        return self


TargetSpec = Annotated[
    StreamingTableTarget | MaterializedViewTarget | TemporaryViewTarget | DeltaSinkTarget,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# Transforms + data quality (databrickslabs/dqx metadata, kept verbatim)
# --------------------------------------------------------------------------
class TransformStep(ConfigBase):
    function: str  # registry key, e.g. 'sales.clean_customers'
    args: dict[str, Any] = {}


class DQCheck(ConfigBase):
    function: str
    # Deliberately open — dqx owns the per-function argument contracts; deep
    # validation is delegated to the static DQEngine.validate_checks pass.
    arguments: dict[str, Any] = {}
    for_each_column: list[str] | None = None


class DQRule(ConfigBase):
    criticality: Literal["error", "warn"] = "error"
    name: str | None = None
    filter: str | None = None
    user_metadata: dict[str, str] | None = None
    check: DQCheck

    def to_dqx(self) -> dict[str, Any]:
        """The exact dqx metadata mapping — zero translation from YAML."""
        return self.model_dump(exclude_none=True)


class QuarantineSpec(ConfigBase):
    name: Identifier | None = None  # default: <dataset>_quarantine
    # False == legacy parity: quarantine holds exactly the dropped rows.
    include_warnings: bool = False
    table_properties: dict[str, str] = {}


class MetricsSpec(ConfigBase):
    enabled: bool = False
    name: Identifier | None = None  # default: <dataset>_dq_metrics


class ReferenceSource(ConfigBase):
    """Batch-read reference table exposed to dqx checks via ref_dfs."""

    name: Identifier
    catalog_conf: ConfKey | None = None
    schema_conf: ConfKey | None = None


class QualitySpec(ConfigBase):
    checks: list[DQRule] = Field(min_length=1)
    quarantine: QuarantineSpec | None = None
    metrics: MetricsSpec = MetricsSpec()
    references: dict[Identifier, ReferenceSource] = {}
    # Dataset-level dqx rules (is_unique, foreign_key, ...) validate per
    # micro-batch on streaming targets; blocked unless explicitly accepted.
    allow_streaming_dataset_checks: bool = False


# --------------------------------------------------------------------------
# Dataset + layer
# --------------------------------------------------------------------------
class DatasetSpec(ConfigBase):
    name: Identifier
    comment: str | None = None
    source: SourceSpec
    transform: list[TransformStep] = []
    quality: QualitySpec | None = None
    target: TargetSpec

    @field_validator("transform", mode="before")
    @classmethod
    def _coerce_single_step(cls, v: Any) -> Any:
        return [v] if isinstance(v, dict) else v

    @property
    def is_streaming(self) -> bool:
        if isinstance(self.source, CloudFilesSource):
            return True
        return bool(self.source.as_stream)

    def quarantine_name(self) -> str | None:
        if not (self.quality and self.quality.quarantine):
            return None
        return self.quality.quarantine.name or f"{self.name}_quarantine"

    def metrics_name(self) -> str | None:
        if not (self.quality and self.quality.metrics.enabled):
            return None
        return self.quality.metrics.name or f"{self.name}_dq_metrics"

    @model_validator(mode="after")
    def _cross_rules(self) -> DatasetSpec:
        t, name = self.target, self.name
        if isinstance(t, StreamingTableTarget):
            if t.cdc and not self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: target.cdc needs a streaming source — "
                    "set source.as_stream: true or use a cloud_files source"
                )
            if not self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: a streaming_table target needs a streaming "
                    "source; for batch sources use target.kind: materialized_view"
                )
        if isinstance(t, MaterializedViewTarget):
            if isinstance(self.source, CloudFilesSource):
                raise ValueError(
                    f"dataset {name!r}: cloud_files sources are streaming; a "
                    "materialized_view target needs a batch source"
                )
            if self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: materialized_view targets need batch sources — "
                    "drop source.as_stream"
                )
        if isinstance(t, DeltaSinkTarget) and not self.is_streaming:
            raise ValueError(
                f"dataset {name!r}: delta_sink appends from a stream; the source must be streaming"
            )
        if isinstance(t, TemporaryViewTarget) and self.quality:
            if self.quality.quarantine or self.quality.metrics.enabled:
                raise ValueError(
                    f"dataset {name!r}: temporary_view targets carry quality results inline "
                    "(_errors/_warnings); quarantine/metrics are not allowed"
                )
        if self.quality and self.quality.quarantine:
            if not any(r.criticality == "error" for r in self.quality.checks):
                raise ValueError(
                    f"dataset {name!r}: quarantine without any criticality=error check "
                    "would always be empty — add an error rule or drop quarantine"
                )
        if self.quality and self.quality.metrics.enabled:
            q = self.quality.quarantine
            if q is None or not q.include_warnings:
                raise ValueError(
                    f"dataset {name!r}: metrics aggregate the quarantine table and need "
                    "quarantine.include_warnings: true so warn evidence exists to count"
                )
        return self


class LayerDefaults(ConfigBase):
    catalog_conf: ConfKey = "datalab.catalog"
    schema_conf: ConfKey
    table_properties: dict[str, str] = {}


class ResultColumns(ConfigBase):
    errors: str = "_errors"
    warnings: str = "_warnings"


class DQDefaults(ConfigBase):
    result_columns: ResultColumns = ResultColumns()
    # Pipeline-conf keys exposed to dqx '{{ var }}' substitution by leaf name.
    variables_conf: list[ConfKey] = []


class LayerConfig(ConfigBase):
    schema_version: Literal[1] = 1
    domain: Identifier
    layer: Literal["bronze", "silver", "gold"]
    # Domain python modules whose import registers this layer's @transform
    # functions and custom dqx checks (e.g. sales_etl.transforms.sales).
    # Keeps the framework free of hardcoded domain module paths.
    imports: list[str] = []
    defaults: LayerDefaults
    dq: DQDefaults = DQDefaults()
    datasets: list[DatasetSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_names(self) -> LayerConfig:
        seen: dict[str, str] = {}
        for ds in self.datasets:
            for label, generated in (
                ("dataset", ds.name),
                ("quarantine", ds.quarantine_name()),
                ("metrics", ds.metrics_name()),
            ):
                if generated is None:
                    continue
                if generated in seen:
                    raise ValueError(
                        f"{label} name {generated!r} collides with {seen[generated]} "
                        f"in layer {self.layer!r}"
                    )
                seen[generated] = f"{label} of dataset {ds.name!r}"
        return self
