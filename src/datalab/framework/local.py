"""Local execution profile — run the medallion off-Databricks via OSS SDP.

The Databricks profile (``datalab.framework.generator``) emits the full Lakeflow
graph: streaming tables, AUTO CDC, Auto Loader, sinks. None of those exist in
open-source ``pyspark.pipelines``, so this module emits a deliberately simpler,
batch graph the OSS ``spark-pipelines`` CLI can actually run on a workstation:

* every target becomes a **materialized view** (batch);
* ``cloud_files``/``as_stream`` reads collapse to batch reads (``force_batch``);
* AUTO CDC / AUTO CDC FROM SNAPSHOT are NOT applied — the SCD merge is
  engine-owned, and OSS SDP rejects the dedup anyway (a window function over an
  in-graph dataset triggers eager analysis and fails graph registration), so the
  table holds the mapped/transformed source rows as-is (expect duplicate keys);
* delta/kafka sinks are skipped (append-only external targets).

**The dqx quality gate is NOT applied locally.** dqx inspects a DataFrame's
schema (``df.columns``) and emits telemetry (``df.isStreaming``) while building
checks — both trigger Spark *analysis*, which OSS SDP forbids inside a pipeline
query function (``ATTEMPT_ANALYSIS_IN_PIPELINE_QUERY_FUNCTION``), and the
upstream tables do not exist at graph-registration time anyway. So the local run
materializes the mapping/transform/CDC shape only; validate the dqx
valid/quarantine split with ``run_dataset`` (``make test``) or against a live
cluster (``make validate-connect``).

It is a development/validation aid: identical loader/column-mapping/transform
code as production, exercised end to end on sample data. SCD merge,
checkpointing, Auto Loader, sinks and dqx are verified by a dev refresh
(``make deploy run``) or the unit suite. See docs/FRAMEWORK.md "Run locally".

The generated ``spark-pipeline.yml`` (``write_local_spec`` /
``python -m datalab.framework.local``) carries ``datalab.profile: local`` in its
``configuration`` so the SAME ``transformations/pipeline.py`` routes here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from pyspark import pipelines as dp
from pyspark.sql import DataFrame, SparkSession

from datalab.framework.context import ResolveContext
from datalab.framework.errors import ConfigError
from datalab.framework.loader import load_domain, load_domain_configs
from datalab.framework.models import (
    DatasetSpec,
    DeltaSinkTarget,
    KafkaSinkTarget,
    LayerConfig,
    SnapshotFunctionSource,
    TemporaryViewTarget,
)
from datalab.framework.readers import prepare, read_source

# --------------------------------------------------------------------------
# Graph generation (datalab.profile == "local")
# --------------------------------------------------------------------------


def generate_local(
    spark: SparkSession, config_dir: str | Path, *, layers: list[str] | None = None
) -> None:
    """Register every dataset as a batch materialized view (local profile).

    Every query function stays fully lazy (no ``.columns``/``.collect``/dqx) so
    the OSS SDP runner can capture each relation without triggering analysis."""
    ctx = ResolveContext.from_spark(spark, force_batch=True, local=True)
    for layer_config in load_domain_configs(Path(config_dir), layers):
        for ds in layer_config.datasets:
            register_dataset_local(spark, ds, layer_config, ctx)


def register_dataset_local(
    spark: SparkSession, ds: DatasetSpec, layer: LayerConfig, ctx: ResolveContext
) -> None:
    target = ds.target

    if isinstance(target, (DeltaSinkTarget, KafkaSinkTarget)):
        # Append-only streaming exports to external systems — nothing to
        # materialize locally; verify them with a dev refresh.
        print(f"[datalab local] skipping {target.kind} target {ds.name!r} (sinks are Databricks-only)")
        return

    annotate_only = isinstance(target, TemporaryViewTarget)

    def _query(spark=spark, ds=ds, layer=layer, ctx=ctx) -> DataFrame:
        # Stays narrow (read + try_cast select + transform). No window/dedup:
        # OSS SDP eagerly analyzes window functions and fails to resolve the
        # in-graph upstream at registration. The SCD merge is engine-owned.
        return _prepared(spark, ds, layer, ctx)

    if annotate_only:
        dp.temporary_view(_query, name=ds.name, comment=ds.comment)
        return

    # Register the SHORT dataset name: OSS SDP qualifies it with the spec's
    # catalog/database (spark_catalog.default), which is exactly what the
    # framework's source FQNs resolve to locally — so cross-dataset reads
    # (silver→bronze, gold→silver) link to the in-graph datasets. (On Databricks
    # the generator uses the full 3-part FQN.) All layers share the one local
    # database, so dataset names must be unique across layers — true here.
    dp.materialized_view(
        _query,
        name=ds.name,
        comment=ds.comment,
        table_properties=_table_properties(ds, layer),
    )


def _prepared(spark: SparkSession, ds: DatasetSpec, layer: LayerConfig, ctx: ResolveContext) -> DataFrame:
    """Union every continuous flow's prepared (mapped + transformed) batch frame.

    Backfill once-flows are omitted — the continuous source already carries the
    data for a local sample run. Stays lazy: no schema or data is touched."""
    frames: list[DataFrame] = []
    for _suffix, src in ds.streaming_flows():
        if isinstance(src, SnapshotFunctionSource):
            frames.append(prepare(_latest_snapshot(src), ds))
        else:
            frames.append(prepare(read_source(spark, src, layer, ctx), ds))
    df = frames[0]
    for extra in frames[1:]:
        df = df.unionByName(extra, allowMissingColumns=True)
    return df


def _latest_snapshot(src: SnapshotFunctionSource) -> DataFrame:
    """Walk a registered ``@snapshot_source`` to its newest snapshot frame."""
    from datalab.framework.registry import resolve_snapshot_source

    walker = resolve_snapshot_source(src.function)
    version = None
    frame: DataFrame | None = None
    while True:
        result = walker(version)
        if result is None:
            break
        frame, version = result
    if frame is None:
        raise ConfigError(f"snapshot source {src.function!r} yielded no snapshots to preview")
    return frame


def _table_properties(ds: DatasetSpec, layer: LayerConfig) -> dict[str, str]:
    return {**layer.defaults.table_properties, **getattr(ds.target, "table_properties", {})}


# --------------------------------------------------------------------------
# spark-pipeline.yml generation (the OSS CLI's project spec)
# --------------------------------------------------------------------------


def write_local_spec(
    *,
    config_dir: str | Path,
    transformations: str | Path,
    out: str | Path,
    storage: str | Path | None = None,
    catalog: str = "spark_catalog",
    database: str = "default",
    extra_conf: dict[str, str] | None = None,
) -> dict:
    """Emit a ``spark-pipeline.yml`` for the OSS ``spark-pipelines`` CLI.

    All layers are mapped to a single local ``database`` (table names are unique
    across a domain) so no cross-database creation is needed. Source location
    confs (e.g. ``datalab.sales_landing_path``) are domain-specific — pass them
    in ``extra_conf`` (the CLI ``--conf key=value`` flag) pointing at local
    sample data. Returns the spec dict (also written to ``out``)."""
    config_dir = Path(config_dir).resolve()
    domain = load_domain(config_dir)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = out_path.resolve().parent
    storage_dir = Path(storage).resolve() if storage else (out_dir / ".local-storage")
    storage_dir.mkdir(parents=True, exist_ok=True)

    # The OSS CLI globs `libraries` RELATIVE to the spec's directory (pathlib
    # rejects absolute and '..' patterns), so the spec must sit at/above the
    # transformations dir.
    transformations_abs = Path(transformations).resolve()
    try:
        include = transformations_abs.relative_to(out_dir).as_posix()
    except ValueError:
        print(
            f"[datalab local] WARNING: {transformations_abs} is not under the spec dir "
            f"{out_dir}; spark-pipelines cannot glob it. Put --out at/above the "
            "transformations dir."
        )
        include = transformations_abs.as_posix()

    # Databricks exposes pipeline `configuration:` keys verbatim, but the OSS CLI
    # launches via spark-submit, which DROPS non-`spark.`-prefixed confs. Prefix
    # every key — datalab.config.pipeline_conf reads either form.
    raw_conf: dict[str, str] = {
        "datalab.profile": "local",
        "datalab.config_dir": str(config_dir),
        domain.catalog_conf: catalog,
    }
    for entry in domain.layers.values():
        raw_conf[entry.schema_conf] = database
    raw_conf.update(extra_conf or {})
    configuration = {f"spark.{key}": value for key, value in raw_conf.items()}

    # NB: no top-level `catalog`/`database`. Like the OSS `spark-pipelines init`
    # template, datasets register under their short name and resolve to each
    # other within the graph; adding catalog/database forces FQN qualification
    # that breaks short-name cross-dataset resolution. Tables materialize in the
    # session default (spark_catalog.default).
    spec = {
        "name": f"{domain.domain}_local",
        "libraries": [{"glob": {"include": f"{include}/**"}}],
        "storage": f"file://{storage_dir}",
        "configuration": configuration,
    }
    out_path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return spec


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a spark-pipeline.yml for a local OSS spark-pipelines run."
    )
    parser.add_argument("--config-dir", required=True, help="domain config dir (holds domain.yml)")
    parser.add_argument("--transformations", required=True, help="transformations dir (libraries glob root)")
    parser.add_argument("--out", default="spark-pipeline.yml", help="output spec path")
    parser.add_argument("--storage", default="", help="checkpoint/storage dir (default: <out>/.local-storage)")
    parser.add_argument("--catalog", default="spark_catalog")
    parser.add_argument("--database", default="default")
    parser.add_argument(
        "--conf",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="extra pipeline configuration (e.g. datalab.sales_landing_path=file://...); repeatable",
    )
    args = parser.parse_args(argv)

    extra: dict[str, str] = {}
    for item in args.conf:
        if "=" not in item:
            parser.error(f"--conf expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        extra[key] = value

    write_local_spec(
        config_dir=args.config_dir,
        transformations=args.transformations,
        out=args.out,
        storage=args.storage or None,
        catalog=args.catalog,
        database=args.database,
        extra_conf=extra,
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
