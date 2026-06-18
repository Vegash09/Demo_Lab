"""Publish the datalab FRAMEWORK wheel to each domain's artifacts UC Volume.

Phase 0 distribution: the framework ships as a versioned wheel
(``datalab-<ver>-py3-none-any.whl``) that every pipeline/job environment installs
from ``/Volumes/<catalog>/artifacts/wheels/`` (see variables/medallion.yml —
``datalab_wheel`` / ``sales_datalab_wheel``). This uploads the locally built wheel
to that Volume in EVERY domain catalog for the target (per-domain volumes), so the
customer_sales and sales pipelines both resolve it.

Build the wheel first, then publish:

    make publish-wheel TARGET=dev               # dry run (prints the upload plan)
    make publish-wheel TARGET=dev APPLY=1       # upload via the Databricks SDK

Runs under ``uv run --with databricks-sdk`` so the SDK never enters uv.lock (the
dev venv stays pyspark-only — see AGENTS.md). The artifacts Volume must already
exist: ``make bootstrap-uc TARGET=<t>`` provisions it.

NOTE: the per-domain catalog names come from bootstrap_uc.CATALOGS (the bundle
defaults). If a target overrides catalog names (the deploy `--var catalog=...`
escape hatch), pass --catalog / --sales-catalog to match, or the upload lands in
the wrong catalog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Single source of truth for the target -> domain catalogs mapping (scripts/ is
# on sys.path[0] when this file is run directly).
from bootstrap_uc import CATALOGS

ARTIFACTS_PATH = "artifacts/wheels"  # the <catalog>.artifacts.wheels Volume


def _default_version() -> str:
    import datalab

    return datalab.__version__


def wheel_path(version: str, dist_dir: str) -> Path:
    return Path(dist_dir) / f"datalab-{version}-py3-none-any.whl"


def volume_dirs(target: str, overrides: dict[str, str]) -> list[str]:
    """The /Volumes/<catalog>/artifacts/wheels dir for every domain in ``target``.

    ``overrides`` maps a default catalog name to its per-target override (from
    the deploy --var escape hatch); empty by default."""
    dirs = []
    for catalog, _with_volumes in CATALOGS[target]:
        catalog = overrides.get(catalog, catalog)
        dirs.append(f"/Volumes/{catalog}/{ARTIFACTS_PATH}")
    return dirs


def upload(local: Path, dests: list[str], profile: str | None) -> None:
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    for d in dests:
        remote = f"{d}/{local.name}"
        print(f"  uploading {local.name} -> {remote}")
        with local.open("rb") as f:
            client.files.upload(remote, f, overwrite=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument(
        "--version", default="", help="framework version (default: datalab.__version__)"
    )
    parser.add_argument(
        "--dist-dir",
        default="dist-framework",
        help="directory holding the built framework wheel (isolated from the bundle's dist/)",
    )
    parser.add_argument("--apply", action="store_true", help="upload (default: print plan only)")
    parser.add_argument("--profile", default="", help="Databricks CLI profile (default: ambient auth)")
    parser.add_argument(
        "--catalog", default="", help="override the customer_sales catalog name (rare; matches deploy --var)"
    )
    parser.add_argument(
        "--sales-catalog", default="", help="override the sales catalog name (rare; matches deploy --var)"
    )
    args = parser.parse_args(argv)

    version = args.version or _default_version()
    local = wheel_path(version, args.dist_dir)
    overrides: dict[str, str] = {}
    if args.catalog:
        # The first default catalog for the target is the customer_sales one.
        overrides[CATALOGS[args.target][0][0]] = args.catalog
    if args.sales_catalog:
        overrides[CATALOGS[args.target][1][0]] = args.sales_catalog
    dests = volume_dirs(args.target, overrides)

    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply (APPLY=1) to upload\n")
        print(f"   wheel: {local}")
        for d in dests:
            print(f"   -> {d}/{local.name}")
        return

    if not local.exists():
        raise SystemExit(f"wheel not found: {local} — run `uv build --wheel` first")
    upload(local, dests, args.profile or None)
    print(f"published {local.name} to target '{args.target}'")


if __name__ == "__main__":
    main(sys.argv[1:])
