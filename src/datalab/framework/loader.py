"""YAML → validated LayerConfig, with three-station fail-fast validation.

Station 1 is the editor (JSON schema, ``make schema``); station 2 is this
loader (pydantic shape + deep pass), which runs identically in pytest,
``make validate-configs`` and at pipeline import; station 3 is the pipeline
update itself. A bad config never moves data.

CLI: ``python -m datalab.framework.loader config/sales [config/finance ...]``
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from datalab.framework.errors import ConfigError
from datalab.framework.models import LayerConfig, TableSource, ViewSource
from datalab.framework.registry import check_registry, import_modules, resolve_transform

LAYER_ORDER = ("bronze", "silver", "gold")


def load_layer_config(path: Path) -> LayerConfig:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level, got {type(raw).__name__}")
    try:
        return LayerConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {path}: {'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_url=False)
        )
        raise ConfigError(f"invalid layer config:\n{problems}") from exc


def _deep_validate(config: LayerConfig, path: Path, known_datasets: set[str]) -> None:
    from databricks.labs.dqx.engine import DQEngine
    from databricks.labs.dqx.rule import CHECK_FUNC_REGISTRY

    import_modules(config.imports)
    custom = check_registry()
    for ds in config.datasets:
        for step in ds.transform:
            resolve_transform(step.function)  # raises ConfigError on unknown names

        if ds.quality:
            status = DQEngine.validate_checks(
                [rule.to_dqx() for rule in ds.quality.checks], custom_check_functions=custom
            )
            if status.has_errors:
                raise ConfigError(
                    f"{path}: dataset {ds.name!r} has invalid dqx checks:\n{status.to_string()}"
                )
            for rule in ds.quality.checks:
                ref = rule.check.arguments.get("ref_df_name")
                if ref and ref not in ds.quality.references:
                    raise ConfigError(
                        f"{path}: dataset {ds.name!r} check {rule.check.function!r} uses "
                        f"ref_df_name {ref!r} but quality.references has no such key"
                    )
                kind = CHECK_FUNC_REGISTRY.get(rule.check.function)
                if (
                    kind == "dataset"
                    and ds.is_streaming
                    and not ds.quality.allow_streaming_dataset_checks
                ):
                    raise ConfigError(
                        f"{path}: dataset {ds.name!r} uses dataset-level check "
                        f"{rule.check.function!r} on a STREAMING target — it would only "
                        "validate per micro-batch. Use a materialized_view target for "
                        "global guarantees, or set quality.allow_streaming_dataset_checks: "
                        "true to accept per-batch semantics."
                    )

        if isinstance(ds.source, ViewSource) and ds.source.name not in known_datasets:
            raise ConfigError(
                f"{path}: dataset {ds.name!r} reads view {ds.source.name!r}, which no "
                "earlier dataset in this domain defines"
            )
        known_datasets.add(ds.name)
        if isinstance(ds.source, TableSource):
            known_datasets.add(ds.source.name)  # cross-layer lineage by name


def load_domain_configs(config_dir: str | Path, layers: list[str] | None = None) -> list[LayerConfig]:
    config_dir = Path(config_dir)
    if not config_dir.is_dir():
        raise ConfigError(
            f"config directory {config_dir} does not exist — check the "
            "datalab.config_dir pipeline configuration value"
        )
    wanted = list(layers) if layers else [
        layer for layer in LAYER_ORDER
        if (config_dir / f"{layer}.yml").exists() or (config_dir / f"{layer}.yaml").exists()
    ]
    if not wanted:
        raise ConfigError(f"no {'/'.join(LAYER_ORDER)} YAML files found in {config_dir}")

    configs: list[LayerConfig] = []
    known: set[str] = set()
    for layer in wanted:
        path = config_dir / f"{layer}.yml"
        if not path.exists():
            path = config_dir / f"{layer}.yaml"
        if not path.exists():
            raise ConfigError(f"requested layer {layer!r} has no YAML file in {config_dir}")
        config = load_layer_config(path)
        if config.layer != layer:
            raise ConfigError(f"{path}: file is named {layer}.yml but declares layer: {config.layer}")
        _deep_validate(config, path, known)
        configs.append(config)
    return configs


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m datalab.framework.loader <config-dir> [<config-dir> ...]")
        return 2
    failed = False
    for arg in argv:
        root = Path(arg)
        domains = sorted(d for d in root.iterdir() if d.is_dir()) if not any(
            (root / f"{layer}.yml").exists() for layer in LAYER_ORDER
        ) else [root]
        for domain_dir in domains:
            try:
                configs = load_domain_configs(domain_dir)
            except ConfigError as exc:
                print(f"FAIL {domain_dir}\n{exc}")
                failed = True
            else:
                datasets = sum(len(c.datasets) for c in configs)
                print(f"ok   {domain_dir} — {len(configs)} layer(s), {datasets} dataset(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
