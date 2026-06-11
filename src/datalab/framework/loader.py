"""YAML → validated configs, with three-station fail-fast validation.

Layout (what coding agents author from natural language):

    config/<domain>/domain.yml            environment-agnostic domain settings
    config/<domain>/<layer>/<table>.yml   ONE file per target table

Station 1 is the editor (JSON schemas, ``make schema``); station 2 is this
loader (pydantic shape + deep pass), which runs identically in pytest,
``make validate-configs`` and at pipeline import; station 3 is the pipeline
update itself. A bad config never moves data.

CLI: ``python -m datalab.framework config/ [more dirs ...]`` (the
``__main__`` wrapper around :func:`main` below).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from datalab.framework.errors import ConfigError
from datalab.framework.models import (
    DomainConfig,
    LayerConfig,
    LayerDefaults,
    SnapshotFunctionSource,
    TableFile,
    TableSource,
    ViewSource,
)
from datalab.framework.registry import check_registry, import_modules

LAYER_ORDER = ("bronze", "silver", "gold")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level, got {type(raw).__name__}")
    return raw


def _validate(model: type, raw: dict[str, Any], path: Path) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {path}: {'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_url=False)
        )
        raise ConfigError(f"invalid config:\n{problems}") from exc


def load_domain(config_dir: Path) -> DomainConfig:
    domain_path = config_dir / "domain.yml"
    if not domain_path.exists():
        domain_path = config_dir / "domain.yaml"
    if not domain_path.exists():
        raise ConfigError(
            f"{config_dir} has no domain.yml — every domain config dir starts with one "
            "(domain name, imports, catalog_conf, per-layer schema confs)"
        )
    return _validate(DomainConfig, _load_yaml(domain_path), domain_path)


def _resolve_layer_ref(source: Any, domain: DomainConfig, path: Path) -> Any:
    """`source.layer` references the domain's layer→schema mapping."""
    if not (isinstance(source, dict) and source.get("layer") and not source.get("schema_conf")):
        return source
    entry = domain.layers.get(source["layer"])
    if entry is None:
        raise ConfigError(
            f"{path}: source.layer {source['layer']!r} has no entry under domain.yml layers:"
        )
    source = {k: v for k, v in source.items() if k != "layer"}
    source["schema_conf"] = entry.schema_conf
    return source


def _load_table_file(path: Path, domain: DomainConfig) -> TableFile:
    raw = _load_yaml(path)
    # Layer references resolve in the single source, every fan-in flow, and
    # every backfill entry alike.
    if "source" in raw:
        raw = {**raw, "source": _resolve_layer_ref(raw.get("source"), domain, path)}
    for block in ("sources", "backfill"):
        entries = raw.get(block)
        if isinstance(entries, list):
            raw = {
                **raw,
                block: [
                    {**e, "source": _resolve_layer_ref(e.get("source"), domain, path)}
                    if isinstance(e, dict)
                    else e
                    for e in entries
                ],
            }
    spec = _validate(TableFile, raw, path)
    if spec.name != path.stem:
        raise ConfigError(
            f"{path}: file is named {path.stem!r} but declares the target table "
            f"{spec.name!r} — one artifact per target table, file name == table name"
        )
    return spec


def _deep_validate(config: LayerConfig, where: Path, known_datasets: set[str]) -> None:
    from databricks.labs.dqx.engine import DQEngine
    from databricks.labs.dqx.rule import CHECK_FUNC_REGISTRY

    custom = check_registry()
    for ds in config.datasets:
        from datalab.framework.registry import resolve_snapshot_source, resolve_transform

        for step in ds.transform:
            resolve_transform(step.function)  # raises ConfigError on unknown names
        if isinstance(ds.source, SnapshotFunctionSource):
            resolve_snapshot_source(ds.source.function)  # ConfigError on unknown

        checks = ds.effective_checks()
        if checks:
            status = DQEngine.validate_checks(checks, custom_check_functions=custom)
            if status.has_errors:
                raise ConfigError(
                    f"{where}/{ds.name}.yml: invalid dqx checks:\n{status.to_string()}"
                )
            references = ds.quality.references if ds.quality else {}
            allow_dataset = ds.quality.allow_streaming_dataset_checks if ds.quality else False
            for meta in checks:
                check = meta.get("check", {})
                ref = check.get("arguments", {}).get("ref_df_name")
                if ref and ref not in references:
                    raise ConfigError(
                        f"{where}/{ds.name}.yml: check {check.get('function')!r} uses "
                        f"ref_df_name {ref!r} but quality.references has no such key"
                    )
                kind = CHECK_FUNC_REGISTRY.get(check.get("function", ""))
                if kind == "dataset" and ds.is_streaming and not allow_dataset:
                    raise ConfigError(
                        f"{where}/{ds.name}.yml: dataset-level check "
                        f"{check.get('function')!r} on a STREAMING target would only "
                        "validate per micro-batch. Use a materialized_view target for "
                        "global guarantees, or set quality.allow_streaming_dataset_checks: "
                        "true to accept per-batch semantics."
                    )

        flow_sources = [src for _, src in ds.streaming_flows()] + [
            b.source for b in ds.backfill
        ]
        for src in flow_sources:
            if isinstance(src, ViewSource) and src.name not in known_datasets:
                raise ConfigError(
                    f"{where}/{ds.name}.yml: reads view {src.name!r}, which no "
                    "earlier dataset in this domain defines"
                )
        known_datasets.add(ds.name)
        for src in flow_sources:
            if isinstance(src, TableSource):
                known_datasets.add(src.name)  # cross-layer lineage by name


def load_domain_configs(config_dir: str | Path, layers: list[str] | None = None) -> list[LayerConfig]:
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        raise ConfigError(
            f"config directory {config_dir} does not exist — check the "
            "datalab.config_dir pipeline configuration value"
        )
    domain = load_domain(config_dir)
    import_modules(domain.imports)

    wanted = list(layers) if layers else [
        layer for layer in LAYER_ORDER if (config_dir / layer).is_dir()
    ]
    if not wanted:
        raise ConfigError(
            f"no layer folders ({'/'.join(LAYER_ORDER)}) found in {config_dir} — "
            "each target table lives in config/<domain>/<layer>/<table>.yml"
        )

    configs: list[LayerConfig] = []
    known: set[str] = set()
    for layer in wanted:
        layer_dir = config_dir / layer
        if not layer_dir.is_dir():
            raise ConfigError(f"requested layer {layer!r} has no folder in {config_dir}")
        entry = domain.layers.get(layer)
        if entry is None:
            raise ConfigError(
                f"{config_dir}/domain.yml: layer {layer!r} has table files but no "
                "layers: entry mapping it to a schema conf key"
            )
        files = sorted(layer_dir.glob("*.yml")) + sorted(layer_dir.glob("*.yaml"))
        if not files:
            raise ConfigError(f"{layer_dir} is empty — add <table>.yml artifacts or remove it")
        specs = [_load_table_file(path, domain) for path in files]
        config = LayerConfig(
            domain=domain.domain,
            layer=layer,
            imports=domain.imports,
            defaults=LayerDefaults(
                catalog_conf=domain.catalog_conf,
                schema_conf=entry.schema_conf,
                table_properties=entry.table_properties,
            ),
            dq=domain.dq,
            datasets=specs,
        )
        _deep_validate(config, layer_dir, known)
        configs.append(config)
    return configs


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m datalab.framework <config-dir> [<config-dir> ...]")
        return 2
    failed = False
    for arg in argv:
        root = Path(arg)
        if (root / "domain.yml").exists() or (root / "domain.yaml").exists():
            domains = [root]
        else:
            domains = sorted(d for d in root.iterdir() if d.is_dir())
        for domain_dir in domains:
            try:
                configs = load_domain_configs(domain_dir)
            except ConfigError as exc:
                print(f"FAIL {domain_dir}\n{exc}")
                failed = True
            else:
                datasets = sum(len(c.datasets) for c in configs)
                print(f"ok   {domain_dir} — {len(configs)} layer(s), {datasets} table(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
