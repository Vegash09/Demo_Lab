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
    # Where the source table lives. `layer` references the domain's layer →
    # schema mapping (domain.yml); the conf overrides are for tables outside
    # this domain. All are pipeline-conf KEYS — never literal names.
    layer: Literal["bronze", "silver", "gold"] | None = None
    catalog_conf: ConfKey | None = None  # None -> layer defaults
    schema_conf: ConfKey | None = None  # None -> layer defaults
    as_stream: bool = False

    @model_validator(mode="after")
    def _layer_xor_schema(self) -> TableSource:
        if self.layer and self.schema_conf:
            raise ValueError(
                f"source table {self.name!r}: give either layer or schema_conf, not both"
            )
        return self


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
    # Opt-out: error rules auto-create a quarantine (rows are never silently
    # dropped); set enabled: false to accept silent drops explicitly.
    enabled: bool = True
    name: Identifier | None = None  # default: <table>_quarantine
    # False == quarantine holds exactly the dropped rows.
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
    """TABLE-level quality config. Most rules belong on the columns
    themselves (``columns[].quality``); this block carries multi-column /
    dataset-level checks and the quarantine/metrics/reference settings."""

    checks: list[DQRule] = []
    quarantine: QuarantineSpec | None = None
    metrics: MetricsSpec = MetricsSpec()
    references: dict[Identifier, ReferenceSource] = {}
    # Dataset-level dqx rules (is_unique, foreign_key, ...) validate per
    # micro-batch on streaming targets; blocked unless explicitly accepted.
    allow_streaming_dataset_checks: bool = False


class ColumnSpec(ConfigBase):
    """One target-table column: source→target mapping, data type, and the
    column's own dqx rules. ``check.arguments.column`` is auto-filled with
    the target column name."""

    name: Identifier  # target column name
    source: str | None = None  # source column name; default: same as name
    type: str | None = None  # Spark data type; cast is ANSI-safe (try_cast)
    comment: str | None = None
    quality: list[DQRule] = []

    @property
    def source_name(self) -> str:
        return self.source or self.name


# --------------------------------------------------------------------------
# Dataset (one target table) + layer
# --------------------------------------------------------------------------
class DatasetSpec(ConfigBase):
    """One target table: the unit a coding agent authors from natural
    language, stored as ONE YAML file under the table's layer folder
    (``config/<domain>/<layer>/<table>.yml``)."""

    name: Identifier
    comment: str | None = None
    source: SourceSpec
    # Target-table columns: source→target names, data types, per-column dqx
    # rules. The framework generates the projection (ANSI-safe try_cast).
    columns: list[ColumnSpec] = []
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

    def effective_checks(self) -> list[dict[str, Any]]:
        """All dqx rules for this table: column-level rules (with the target
        column name and a derived rule name injected) + table-level checks."""
        out: list[dict[str, Any]] = []
        for col in self.columns:
            for rule in col.quality:
                meta = rule.to_dqx()
                meta.setdefault("check", {}).setdefault("arguments", {})
                meta["check"]["arguments"].setdefault("column", col.name)
                meta.setdefault("name", f"{col.name}_{rule.check.function}")
                out.append(meta)
        if self.quality:
            out.extend(rule.to_dqx() for rule in self.quality.checks)
        return out

    @property
    def has_checks(self) -> bool:
        return bool(self.effective_checks())

    def _has_error_rules(self) -> bool:
        return any(meta.get("criticality", "error") == "error" for meta in self.effective_checks())

    def quarantine_spec(self) -> QuarantineSpec | None:
        """Explicit spec if configured; otherwise error rules AUTO-create a
        default quarantine (rows are never silently dropped). None when
        disabled, annotate-only (temporary_view), or no error rules exist."""
        if isinstance(self.target, TemporaryViewTarget):
            return None
        explicit = self.quality.quarantine if self.quality else None
        if explicit is not None:
            return explicit if explicit.enabled else None
        return QuarantineSpec() if self._has_error_rules() else None

    def quarantine_name(self) -> str | None:
        spec = self.quarantine_spec()
        if spec is None:
            return None
        return spec.name or f"{self.name}_quarantine"

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
            if (self.quality.quarantine and self.quality.quarantine.enabled) or (
                self.quality.metrics.enabled
            ):
                raise ValueError(
                    f"dataset {name!r}: temporary_view targets carry quality results inline "
                    "(_errors/_warnings); quarantine/metrics are not allowed"
                )
        seen_cols: set[str] = set()
        for col in self.columns:
            if col.name in seen_cols:
                raise ValueError(f"dataset {name!r}: duplicate target column {col.name!r}")
            seen_cols.add(col.name)
        if self.quality and not self.quality.checks and not any(
            col.quality for col in self.columns
        ):
            raise ValueError(
                f"dataset {name!r}: a quality block with no checks and no column-level "
                "rules does nothing — add rules or remove it"
            )
        if self.quality and self.quality.quarantine and self.quality.quarantine.enabled:
            if not self._has_error_rules():
                raise ValueError(
                    f"dataset {name!r}: quarantine without any criticality=error rule "
                    "would always be empty — add an error rule or drop quarantine"
                )
        if self.quality and self.quality.metrics.enabled:
            q = self.quarantine_spec()
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


# --------------------------------------------------------------------------
# File-level models: what coding agents actually author.
#   config/<domain>/domain.yml            -> DomainConfig
#   config/<domain>/<layer>/<table>.yml   -> TableFile (one per target table)
# --------------------------------------------------------------------------
class LayerEntry(ConfigBase):
    schema_conf: ConfKey
    table_properties: dict[str, str] = {}


class DomainConfig(ConfigBase):
    """config/<domain>/domain.yml — environment-agnostic domain settings.

    Catalog and schema values are pipeline-conf KEYS resolved per target
    (dev/stage/prod) through bundle variables — literal catalog names are
    rejected by design so promotion across environments never edits configs.
    """

    schema_version: Literal[1] = 1
    domain: Identifier
    # Domain python modules whose import registers @transform functions and
    # custom dqx checks (e.g. sales_etl.transforms.sales).
    imports: list[str] = []
    catalog_conf: ConfKey = "datalab.catalog"
    layers: dict[Literal["bronze", "silver", "gold"], LayerEntry]
    dq: DQDefaults = DQDefaults()


class TableFile(DatasetSpec):
    """config/<domain>/<layer>/<table>.yml — one target table per file.

    The file name must equal the target table name; the layer comes from the
    folder. Everything else is DatasetSpec."""

    schema_version: Literal[1] = 1
