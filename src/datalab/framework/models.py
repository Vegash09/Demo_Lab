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
FileFormat = Literal["json", "csv", "parquet", "avro", "orc", "text", "xml", "binaryFile"]


class CloudFilesSource(ConfigBase):
    """Streaming ingest from cloud storage via Auto Loader (``cloudFiles``).

    SDP manages schemaLocation/checkpoints itself; everything else from the
    Auto Loader option catalog goes in ``options:`` verbatim
    (``cloudFiles.inferColumnTypes``, ``cloudFiles.schemaEvolutionMode``,
    ``cloudFiles.maxFilesPerTrigger``, per-format reader options, …)."""

    kind: Literal["cloud_files"]
    path_conf: ConfKey
    format: FileFormat = "json"
    options: dict[str, str] = {}
    # NOT named `schema` — that shadows BaseModel.schema.
    schema_hints: str | None = None  # cloudFiles.schemaHints (partial contract)
    reader_schema: str | None = None  # full explicit DDL schema (skips inference)
    add_lineage: bool = True


class FileSource(ConfigBase):
    """BATCH read of files (``spark.read.format(...).load(path)``) — for
    materialized views over file drops and for ``backfill:`` once-flows.
    For incremental ingest use ``cloud_files`` instead."""

    kind: Literal["files"]
    path_conf: ConfKey
    format: FileFormat | Literal["delta"] = "parquet"
    options: dict[str, str] = {}
    reader_schema: str | None = None


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
    # Reader options, passed verbatim. Streaming: skipChangeCommits (REQUIRED
    # when the source is an AUTO CDC/SCD target or takes updates/deletes),
    # readChangeFeed + startingVersion (stream the change feed), …
    # Batch: versionAsOf / timestampAsOf time travel, …
    options: dict[str, str] = {}

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


class KafkaSource(ConfigBase):
    """Streaming read from Kafka — including Kafka-compatible endpoints such
    as Azure Event Hubs' Kafka surface and AWS MSK.

    The frame arrives with the Kafka wire schema (binary ``key``/``value``,
    ``topic``, ``partition``, ``offset``, ``timestamp``); decode in
    ``columns:``/``transform:``. Auth/tuning options (``kafka.security.*``,
    ``startingOffsets``, ``maxOffsetsPerTrigger``, …) pass through verbatim."""

    kind: Literal["kafka"]
    bootstrap_servers_conf: ConfKey  # kafka.bootstrap.servers is per-environment
    topic: str | None = None  # subscribe
    subscribe_pattern: str | None = None  # subscribePattern
    options: dict[str, str] = {}

    @model_validator(mode="after")
    def _exactly_one_subscription(self) -> KafkaSource:
        if bool(self.topic) == bool(self.subscribe_pattern):
            raise ValueError("kafka source needs exactly one of topic or subscribe_pattern")
        return self


class SnapshotFunctionSource(ConfigBase):
    """Historical snapshot sets for ``cdc_from_snapshot`` (pattern B): a
    registered ``@snapshot_source`` function with the SDP contract
    ``(latest_processed_version | None) -> (DataFrame, version) | None``.
    Only valid with a ``streaming_table`` + ``cdc_from_snapshot`` target."""

    kind: Literal["snapshot_function"]
    function: str  # registry key, e.g. 'sales.customer_snapshots'


SourceSpec = Annotated[
    CloudFilesSource
    | FileSource
    | TableSource
    | ViewSource
    | KafkaSource
    | SnapshotFunctionSource,
    Field(discriminator="kind"),
]


def _is_streaming_source(src: object) -> bool:
    if isinstance(src, (CloudFilesSource, KafkaSource)):
        return True
    if isinstance(src, (FileSource, SnapshotFunctionSource)):
        return False
    return bool(getattr(src, "as_stream", False))


class FlowSource(ConfigBase):
    """One named source flow of a multi-source (fan-in) streaming table.

    ``name`` is part of the generated flow name — SDP uses the flow name as
    the streaming-checkpoint identity, so RENAMING a flow abandons its
    checkpoint and reprocesses from scratch. Pick stable names."""

    name: Identifier
    source: SourceSpec
    comment: str | None = None


class BackfillSpec(ConfigBase):
    """A one-time historical load into the target (``once=True`` flow).

    Runs once, then idles in the graph as an audit trail — and re-runs
    automatically on a FULL REFRESH to recreate its slice of the table.
    Leave it in the config after it completes; deleting it deletes that
    data's recreation path."""

    name: Identifier
    source: SourceSpec
    comment: str | None = None


# --------------------------------------------------------------------------
# Targets (discriminated on `kind`)
# --------------------------------------------------------------------------
class CdcSpec(ConfigBase):
    """AUTO CDC (``dp.create_auto_cdc_flow``) — upserts/SCD from a change feed.

    A CDC-fed streaming table accepts ONLY CDC flows (SDP rule): extra
    ``sources:`` become further CDC flows and ``backfill:`` entries become
    ``once`` CDC flows (whose sources must therefore be STREAMING)."""

    keys: list[Identifier] = Field(min_length=1)
    # str, or a list for multi-column ordering (becomes struct(): first field
    # orders, later fields break ties). Must be sortable, never NULL.
    sequence_by: str | list[str]
    scd_type: Literal[1, 2] = 1
    apply_as_deletes: str | None = None  # SQL condition marking DELETE events
    apply_as_truncates: str | None = None  # SQL condition → full truncate; SCD1 only
    column_list: list[str] = []  # include-list of source columns …
    except_columns: list[str] = []  # … OR exclude-list (not both)
    ignore_null_updates: bool = False
    track_history_columns: list[str] = []  # SCD2: only these open history rows …
    track_history_except_columns: list[str] = []  # … OR all except these (not both)

    @property
    def sequence_columns(self) -> list[str]:
        return [self.sequence_by] if isinstance(self.sequence_by, str) else list(self.sequence_by)

    @model_validator(mode="after")
    def _consistent(self) -> CdcSpec:
        if isinstance(self.sequence_by, list) and not self.sequence_by:
            raise ValueError("cdc.sequence_by list cannot be empty")
        if self.column_list and self.except_columns:
            raise ValueError("cdc: give either column_list or except_columns, not both")
        if self.track_history_columns and self.track_history_except_columns:
            raise ValueError(
                "cdc: give either track_history_columns or track_history_except_columns, not both"
            )
        if self.apply_as_truncates and self.scd_type != 1:
            raise ValueError("cdc.apply_as_truncates is SCD type 1 only (SDP does not "
                             "support truncates for SCD2)")
        clash = set(self.keys) & set(self.except_columns)
        if clash:
            raise ValueError(f"cdc.keys {sorted(clash)} cannot also be in cdc.except_columns")
        for seq in self.sequence_columns:
            if seq in self.except_columns:
                raise ValueError(f"cdc.sequence_by {seq!r} cannot be in cdc.except_columns")
        if self.column_list:
            missing = [k for k in self.keys if k not in self.column_list]
            if missing:
                raise ValueError(f"cdc.keys {missing} must be included in cdc.column_list")
        return self


class SnapshotCdcSpec(ConfigBase):
    """AUTO CDC FROM SNAPSHOT (``dp.create_auto_cdc_from_snapshot_flow``) —
    SCD1/SCD2 computed by DIFFING successive full snapshots (keys absent from
    the newest snapshot are deleted). Two patterns, chosen by the dataset's
    ``source:``:

    * batch ``table``/``files``/``view`` source → the prepared frame is
      re-read on every pipeline update (periodic snapshots);
    * ``snapshot_function`` source → a registered ``@snapshot_source``
      function walks an historical snapshot set version by version."""

    keys: list[Identifier] = Field(min_length=1)
    scd_type: Literal[1, 2] = 1
    track_history_columns: list[str] = []
    track_history_except_columns: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> SnapshotCdcSpec:
        if self.track_history_columns and self.track_history_except_columns:
            raise ValueError(
                "cdc_from_snapshot: give either track_history_columns or "
                "track_history_except_columns, not both"
            )
        return self


SCD2_PERIOD_COLUMNS = ("__START_AT", "__END_AT")


class StreamingTableTarget(ConfigBase):
    kind: Literal["streaming_table"]
    cdc: CdcSpec | None = None
    cdc_from_snapshot: SnapshotCdcSpec | None = None
    partition_cols: list[str] = []
    cluster_by: list[str] = []
    cluster_by_auto: bool = False  # automatic liquid clustering (may combine with cluster_by)
    table_properties: dict[str, str] = {}
    table_schema: str | None = Field(None, alias="schema")

    @model_validator(mode="after")
    def _one_cdc_mode(self) -> StreamingTableTarget:
        if self.cdc and self.cdc_from_snapshot:
            raise ValueError(
                "streaming_table: cdc and cdc_from_snapshot cannot share a target "
                "(SDP forbids mixing feed-CDC and snapshot-CDC flows)"
            )
        if self.partition_cols and (self.cluster_by or self.cluster_by_auto):
            raise ValueError("partition_cols cannot be combined with liquid clustering")
        scd2 = (self.cdc and self.cdc.scd_type == 2) or (
            self.cdc_from_snapshot and self.cdc_from_snapshot.scd_type == 2
        )
        if scd2 and self.table_schema:
            missing = [c for c in SCD2_PERIOD_COLUMNS if c not in self.table_schema]
            if missing:
                raise ValueError(
                    f"SCD type 2 with an explicit schema must declare {missing} "
                    "(same data type as sequence_by) — SDP requirement"
                )
        return self


class MaterializedViewTarget(ConfigBase):
    kind: Literal["materialized_view"]
    partition_cols: list[str] = []
    cluster_by: list[str] = []
    cluster_by_auto: bool = False
    table_properties: dict[str, str] = {}
    table_schema: str | None = Field(None, alias="schema")
    # SDP refresh policy (Beta): auto (cost-based) | incremental (fall back to
    # full) | incremental_strict (fail instead of full recompute) | full.
    refresh_policy: Literal["auto", "incremental", "incremental_strict", "full"] | None = None

    @model_validator(mode="after")
    def _clustering(self) -> MaterializedViewTarget:
        if self.partition_cols and (self.cluster_by or self.cluster_by_auto):
            raise ValueError("partition_cols cannot be combined with liquid clustering")
        return self


class TemporaryViewTarget(ConfigBase):
    """Pipeline-scoped ('dynamic') view — no table is materialized."""

    kind: Literal["temporary_view"]


class DeltaSinkTarget(ConfigBase):
    """Streaming append to a delta table/path OUTSIDE pipeline management
    (dp.create_sink + dp.append_flow). Prefer materialized_view for ordinary
    batch tables — this is for external destinations only. NOTE (SDP): a full
    refresh does NOT clear sink data; reprocessed rows are appended."""

    kind: Literal["delta_sink"]
    table_conf: ConfKey | None = None
    path_conf: ConfKey | None = None
    options: dict[str, str] = {}

    @model_validator(mode="after")
    def _exactly_one_destination(self) -> DeltaSinkTarget:
        if bool(self.table_conf) == bool(self.path_conf):
            raise ValueError("delta_sink needs exactly one of table_conf or path_conf")
        return self


class KafkaSinkTarget(ConfigBase):
    """Streaming append to a Kafka topic (dp.create_sink format=kafka +
    dp.append_flow) — also Kafka-compatible endpoints (Event Hubs, MSK).

    The flow's frame must follow the Kafka writer contract: a ``value``
    column (string/binary; ``framework.to_json_value`` packs rows for you),
    optional ``key``/``partition``/``headers``/``topic`` columns. Same SDP
    caveat as delta_sink: full refresh never clears sink data."""

    kind: Literal["kafka_sink"]
    bootstrap_servers_conf: ConfKey
    topic: str | None = None  # static topic; omit to route via a per-row `topic` column
    options: dict[str, str] = {}


TargetSpec = Annotated[
    StreamingTableTarget
    | MaterializedViewTarget
    | TemporaryViewTarget
    | DeltaSinkTarget
    | KafkaSinkTarget,
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
    # Exactly one of `source` (single flow) or `sources` (fan-in: one named
    # append/CDC flow per entry — the SDP replacement for UNION, keeps the
    # target incrementally updatable).
    source: SourceSpec | None = None
    sources: list[FlowSource] = []
    # One-time historical loads (`once` flows); re-run only on full refresh.
    backfill: list[BackfillSpec] = []
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
    def primary_source(self) -> SourceSpec:
        """The single source, or the first fan-in flow's source (devtools)."""
        if self.source is not None:
            return self.source
        return self.sources[0].source

    def streaming_flows(self) -> list[tuple[str | None, SourceSpec]]:
        """(flow-name-suffix, source) per continuous flow; suffix None for the
        legacy single-source form (keeps existing view/flow/checkpoint names)."""
        if self.sources:
            return [(fs.name, fs.source) for fs in self.sources]
        return [(None, self.primary_source)]

    @property
    def is_streaming(self) -> bool:
        if self.sources:
            return True  # every fan-in source is validated streaming
        return _is_streaming_source(self.primary_source)

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

        # ---- source/sources/backfill shape -------------------------------
        if (self.source is None) == (not self.sources):
            raise ValueError(
                f"dataset {name!r}: give exactly one of source (single flow) or "
                "sources (fan-in flow list)"
            )
        if self.sources:
            if not isinstance(t, (StreamingTableTarget, DeltaSinkTarget, KafkaSinkTarget)):
                raise ValueError(
                    f"dataset {name!r}: sources (fan-in) is for streaming_table or "
                    "sink targets — materialized_view/temporary_view take one source"
                )
            for fs in self.sources:
                if not _is_streaming_source(fs.source):
                    raise ValueError(
                        f"dataset {name!r}: fan-in source {fs.name!r} must be "
                        "streaming (cloud_files/kafka, or as_stream: true)"
                    )
        flow_names = [fs.name for fs in self.sources] + [b.name for b in self.backfill]
        dupes = {n for n in flow_names if flow_names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"dataset {name!r}: duplicate flow name(s) {sorted(dupes)} across "
                "sources/backfill — flow names are checkpoint identities, keep them unique"
            )
        for spec in [self.source, *(fs.source for fs in self.sources),
                     *(b.source for b in self.backfill)]:
            if isinstance(spec, SnapshotFunctionSource) and not (
                isinstance(t, StreamingTableTarget) and t.cdc_from_snapshot and spec is self.source
            ):
                raise ValueError(
                    f"dataset {name!r}: a snapshot_function source is only valid as the "
                    "single source of a streaming_table with cdc_from_snapshot"
                )

        # ---- backfill rules ----------------------------------------------
        if self.backfill:
            if not isinstance(t, StreamingTableTarget):
                raise ValueError(
                    f"dataset {name!r}: backfill is for streaming_table targets "
                    "(sinks are never cleared by full refresh; MVs recompute instead)"
                )
            if t.cdc_from_snapshot:
                raise ValueError(
                    f"dataset {name!r}: cdc_from_snapshot computes history from the "
                    "snapshots themselves — backfill is not applicable"
                )
            for b in self.backfill:
                if t.cdc and not _is_streaming_source(b.source):
                    raise ValueError(
                        f"dataset {name!r}: backfill {b.name!r} feeds a CDC target, so "
                        "its source must be STREAMING (SDP: AUTO CDC once-flows read "
                        "streaming sources)"
                    )
                if not t.cdc and _is_streaming_source(b.source):
                    raise ValueError(
                        f"dataset {name!r}: backfill {b.name!r} must be a BATCH source "
                        "(files, or table/view without as_stream) — once-flows read "
                        "batch frames"
                    )

        # ---- target kind ↔ source mode -----------------------------------
        if isinstance(t, StreamingTableTarget):
            if t.cdc_from_snapshot:
                if self.sources:
                    raise ValueError(
                        f"dataset {name!r}: cdc_from_snapshot takes the single dataset "
                        "source as its snapshot feed — fan-in sources are not supported"
                    )
                if self.is_streaming:
                    raise ValueError(
                        f"dataset {name!r}: cdc_from_snapshot diffs BATCH snapshots — "
                        "use a batch table/files/view source (or snapshot_function), "
                        "not a streaming one"
                    )
                if isinstance(self.source, SnapshotFunctionSource) and self.has_checks:
                    raise ValueError(
                        f"dataset {name!r}: quality rules cannot gate a snapshot_function "
                        "source (the engine consumes the function's frames whole; there "
                        "is no stream to split into valid/quarantine). Validate the "
                        "snapshot upstream, or ingest snapshots via a batch source first."
                    )
            elif t.cdc and not self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: target.cdc needs a streaming source — "
                    "set source.as_stream: true or use a cloud_files source"
                )
            elif not t.cdc and not self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: a streaming_table target needs a streaming "
                    "source; for batch sources use target.kind: materialized_view"
                )
        if isinstance(t, MaterializedViewTarget):
            if isinstance(self.primary_source, (CloudFilesSource, KafkaSource)):
                raise ValueError(
                    f"dataset {name!r}: {self.primary_source.kind} sources are streaming; "
                    "a materialized_view target needs a batch source"
                )
            if self.is_streaming:
                raise ValueError(
                    f"dataset {name!r}: materialized_view targets need batch sources — "
                    "drop source.as_stream"
                )
        if isinstance(t, (DeltaSinkTarget, KafkaSinkTarget)) and not self.is_streaming:
            raise ValueError(
                f"dataset {name!r}: {t.kind} appends from a stream; the source must be streaming"
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
