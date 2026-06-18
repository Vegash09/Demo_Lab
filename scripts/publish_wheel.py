"""Publish the common datalab FRAMEWORK wheel to the shared artifacts UC Volume.

Distribution model: the framework ships as a versioned wheel
(``datalab-<ver>-py3-none-any.whl``) that every pipeline/job environment — across
ALL domains — installs from a single shared Volume,
``/Volumes/<datalab_artifacts_catalog>/framework/wheels/`` (see
variables/medallion.yml ``datalab_artifacts_catalog`` / ``datalab_wheel``). One
upload per target serves the customer_sales and sales pipelines alike.

Build the wheel first, then publish:

    make publish-wheel TARGET=dev               # dry run (prints the upload plan)
    make publish-wheel TARGET=dev APPLY=1       # upload via the Databricks SDK

Runs under ``uv run --with databricks-sdk`` so the SDK never enters uv.lock (the
dev venv stays pyspark-only — see AGENTS.md). The Volume must already exist:
``make bootstrap-uc TARGET=<t>`` provisions the shared catalog + framework.wheels.

NOTE: the per-target artifacts catalog name comes from
bootstrap_uc.ARTIFACTS_CATALOGS (the bundle defaults). If a target overrides it
(the deploy `--var datalab_artifacts_catalog=...` escape hatch), pass
--artifacts-catalog to match, or the upload lands in the wrong catalog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Single source of truth for the target -> shared artifacts catalog mapping
# (scripts/ is on sys.path[0] when this file is run directly).
from bootstrap_uc import ARTIFACTS_CATALOGS, FRAMEWORK_SCHEMA, FRAMEWORK_VOLUME

ARTIFACTS_PATH = f"{FRAMEWORK_SCHEMA}/{FRAMEWORK_VOLUME}"  # <catalog>.framework.wheels Volume


def _default_version() -> str:
    import datalab

    return datalab.__version__


def wheel_path(version: str, dist_dir: str) -> Path:
    return Path(dist_dir) / f"datalab-{version}-py3-none-any.whl"


def volume_dir(target: str, catalog_override: str = "") -> str:
    """The single /Volumes/<catalog>/framework/wheels dir for ``target``.

    ``catalog_override`` matches a deploy `--var datalab_artifacts_catalog=...`
    escape hatch; empty (the default) uses the per-target ARTIFACTS_CATALOGS name."""
    catalog = catalog_override or ARTIFACTS_CATALOGS[target]
    return f"/Volumes/{catalog}/{ARTIFACTS_PATH}"


def upload(local: Path, dest: str, profile: str | None) -> None:
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    remote = f"{dest}/{local.name}"
    print(f"  uploading {local.name} -> {remote}")
    with local.open("rb") as f:
        client.files.upload(remote, f, overwrite=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(ARTIFACTS_CATALOGS), required=True)
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
        "--artifacts-catalog",
        default="",
        help="override the shared artifacts catalog name (rare; matches deploy --var datalab_artifacts_catalog)",
    )
    args = parser.parse_args(argv)

    version = args.version or _default_version()
    local = wheel_path(version, args.dist_dir)
    dest = volume_dir(args.target, args.artifacts_catalog)

    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply (APPLY=1) to upload\n")
        print(f"   wheel: {local}")
        print(f"   -> {dest}/{local.name}")
        return

    if not local.exists():
        raise SystemExit(f"wheel not found: {local} — run `uv build --wheel` first")
    upload(local, dest, args.profile or None)
    print(f"published {local.name} to target '{args.target}'")


if __name__ == "__main__":
    main(sys.argv[1:])
