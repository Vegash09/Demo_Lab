"""The domain registry — the ONE place that says which domains this repo deploys.

Everything else about a domain's per-target identity is DERIVED from the bundle
files the deploy actually uses, not duplicated here:

    variables/medallion.yml   each domain's catalog variable default
    targets/<t>.yml           the per-target catalog value (overrides the default)
    rbac.yml                  reader/engineer group names (defaults + per-target)

bootstrap_uc.py and publish_wheel.py used to carry their own hardcoded
CATALOGS/GROUPS dicts with "keep in sync with targets/ and rbac.yml" comments —
the sync never held (and could not scale past two domains). Now they resolve
through this module, so a catalog rename in targets/<t>.yml or a group change in
rbac.yml is picked up automatically and there is nothing to drift.

Adding a domain = one entry in DOMAINS below (plus the domain's own
config/src/resources, its catalog variables in variables/medallion.yml, and the
uv workspace member — see AGENTS.md "Add a new domain pipeline").

Needs pyyaml (present in the dev venv). `make check-domains` resolves every
target as a CI smoke check that the registry and bundle files agree.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# domain name -> its bundle catalog VARIABLE (variables/medallion.yml, overridden
# per target in targets/<t>.yml) and, when bootstrap provisions the edge-lane
# Auto Loader landing + export volumes, the VOLUME NAME to create ("edge_volume").
# The volume name must match the volume segment of the domain's landing/export
# path variables (/Volumes/<catalog>/landing/<edge_volume>/...) — bootstrap used
# to hardcode `sales` while the adopter scaffold wrote `<catalog>` paths, so a
# fresh adopter's first `make run` failed on a missing volume. Now both sides
# read this one field. This repo's live volumes are named `sales`
# (var.sales_landing_path / var.sales_export_path); adopters get `<catalog>`.
DOMAINS: dict[str, dict] = {
    "customer_sales": {
        "catalog_var": "catalog",
        "edge_volume": "sales",
        "extra_schemas": ["mysql_raw", "mysql_gateway_meta"],
    },
    "sales": {"catalog_var": "sales_catalog", "edge_volume": None, "extra_schemas": []},
}

# Every domain catalog gets this schema/volume holding the datalab FRAMEWORK
# wheel — published by `make publish-wheel` into EACH project's own catalog and
# installed by that domain's pipeline/job environments (var.datalab_wheel /
# var.sales_datalab_wheel; see AGENTS.md "Wheel delivery").
ARTIFACTS_SCHEMA = "artifacts"
WHEELS_VOLUME = "wheels"


def targets() -> list[str]:
    """Deploy targets, from the bundle's targets/ directory."""
    return sorted(p.stem for p in (REPO_ROOT / "targets").glob("*.yml"))


def _variable_defaults() -> dict[str, str]:
    data = yaml.safe_load((REPO_ROOT / "variables" / "medallion.yml").read_text())
    return {
        name: spec.get("default")
        for name, spec in (data.get("variables") or {}).items()
        if isinstance(spec, dict)
    }


def _target_variables(target: str) -> dict[str, str]:
    data = yaml.safe_load((REPO_ROOT / "targets" / f"{target}.yml").read_text())
    return (data.get("targets") or {}).get(target, {}).get("variables") or {}


def catalogs(target: str) -> list[tuple[str, str | None]]:
    """``[(catalog, edge_volume_name_or_None), ...]`` for every domain on
    ``target`` — the per-target value from targets/<t>.yml, else the
    medallion.yml default. A non-None edge volume name means bootstrap creates
    the ``landing``/``exports`` volumes under that name in the catalog."""
    defaults = _variable_defaults()
    overrides = _target_variables(target)
    resolved = []
    for domain, spec in DOMAINS.items():
        var = spec["catalog_var"]
        catalog = overrides.get(var) or defaults.get(var)
        if not catalog:
            raise SystemExit(
                f"domain {domain!r}: catalog variable {var!r} has no value for target "
                f"{target!r} (checked targets/{target}.yml and variables/medallion.yml) — "
                "fix the bundle files or scripts/domains.py DOMAINS"
            )
        resolved.append((catalog, spec["edge_volume"]))
    return resolved


def domain_catalogs(target: str) -> dict[str, str]:
    """``{domain: catalog}`` for ``target`` (same resolution as :func:`catalogs`)."""
    return {
        domain: catalog
        for domain, (catalog, _) in zip(DOMAINS, catalogs(target), strict=True)
    }


def extra_schemas_by_catalog(target: str) -> dict[str, list[str]]:
    """Additional UC schemas required by each resolved catalog."""
    return {
        catalog: list(spec.get("extra_schemas") or [])
        for spec, (catalog, _) in zip(DOMAINS.values(), catalogs(target), strict=True)
    }


def framework_version(target: str) -> str:
    """The framework version THIS target installs — the per-target
    ``datalab_version`` override from targets/<t>.yml when present, else the
    ``variables/medallion.yml`` default.

    This is the version the bundle composes ``var.datalab_wheel`` from, so it is
    the version that must exist on each catalog's artifacts.wheels Volume. A
    target soak-testing a newer framework (see targets/stage.yml) overrides it,
    which is exactly why publishing must resolve it per target rather than from
    the repo-wide pyproject pin."""
    value = _target_variables(target).get("datalab_version") or _variable_defaults().get(
        "datalab_version"
    )
    if not value:
        raise SystemExit(
            f"datalab_version has no value for target {target!r} (checked "
            f"targets/{target}.yml and variables/medallion.yml)"
        )
    return str(value)


def groups(target: str) -> dict[str, str]:
    """``{"reader": ..., "engineer": ...}`` from rbac.yml — the target's
    override when present, else the variable default."""
    data = yaml.safe_load((REPO_ROOT / "rbac.yml").read_text())
    defaults = data.get("variables") or {}
    overrides = (data.get("targets") or {}).get(target, {}).get("variables") or {}

    def resolve(var: str) -> str:
        value = overrides.get(var) or (defaults.get(var) or {}).get("default")
        if not value:
            raise SystemExit(f"rbac.yml: no value for {var!r} (target {target!r})")
        return value

    return {"reader": resolve("reader_group"), "engineer": resolve("engineer_group")}


def main() -> int:
    """`make check-domains`: resolve every target and print the result — fails
    loudly if the registry and the bundle files disagree anywhere."""
    for target in targets():
        resolved = catalogs(target)
        who = groups(target)
        pretty = ", ".join(
            f"{domain}->{catalog}{f' (+edge volumes: {edge})' if edge else ''}"
            for domain, (catalog, edge) in zip(DOMAINS, resolved, strict=True)
        )
        print(f"{target}: {pretty}; reader={who['reader']!r} engineer={who['engineer']!r}")
    print("domain registry resolves cleanly against variables/, targets/ and rbac.yml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
