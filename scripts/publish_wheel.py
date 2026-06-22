"""Build + publish the datalab FRAMEWORK wheel into each project catalog's volume.

Distribution model: the framework lives in its OWN repo
(``dediggibyte/datalab-framework``) and is consumed here two ways — a git
dependency for local/CI (pinned in ``pyproject.toml`` ``[tool.uv.sources]``) and
a versioned wheel (``datalab-<ver>-py3-none-any.whl``) installed by serverless
pipeline/job environments. The wheel is NOT in a separate shared catalog — it
lives in an ``artifacts.wheels`` UC Volume INSIDE EACH PROJECT'S OWN CATALOG
(``customer_sales.artifacts.wheels``, ``sales.artifacts.wheels``; see
variables/medallion.yml ``datalab_wheel`` / ``sales_datalab_wheel``).

This repo (the adopter/reference bundle) BUILDS that wheel from the pinned git
dependency and uploads it to each project catalog's volume. ``--build`` clones+
builds ``datalab`` from the git ref in ``pyproject.toml`` (``pip wheel "datalab @
git+<url>@<tag>" --no-deps``); without it the script just uploads a wheel already
sitting in ``--dist-dir``.

    make publish-wheel TARGET=dev               # dry run (prints the build+upload plan)
    make publish-wheel TARGET=dev APPLY=1       # build from the git dep + upload via the SDK

Runs under ``uv run --with databricks-sdk --with pip`` so neither the SDK nor pip
enters uv.lock. The target volumes must already exist: ``make bootstrap-uc
TARGET=<t>`` provisions each project catalog's ``artifacts.wheels`` volume.

NOTE: the per-target domain catalogs come from bootstrap_uc.CATALOGS (the bundle
defaults). If a deploy overrides a domain catalog (the ``--var catalog=...``
escape hatch), pass ``--catalog <name>`` (repeatable) to match, or the wheel
lands in the wrong catalog.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

# Single source of truth for the per-target domain catalogs + the wheel volume
# location (scripts/ is on sys.path[0] when this file is run directly).
from bootstrap_uc import ARTIFACTS_SCHEMA, CATALOGS, WHEELS_VOLUME

ARTIFACTS_PATH = f"{ARTIFACTS_SCHEMA}/{WHEELS_VOLUME}"  # <catalog>.artifacts.wheels Volume
REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _default_version() -> str:
    """The pinned framework version, from the installed git dependency."""
    try:
        import datalab

        return datalab.__version__
    except Exception:  # not importable (e.g. an isolated build env) — fall back to a glob
        return ""


def _git_requirement() -> str:
    """``datalab @ git+<url>@<ref>`` from pyproject's ``[tool.uv.sources].datalab``.

    This is the single source of truth for which framework release is published —
    bumping the tag here (in lockstep with ``var.datalab_version``) is the only
    version knob this repo owns."""
    data = tomllib.loads(PYPROJECT.read_text())
    src = data["tool"]["uv"]["sources"]["datalab"]
    git = src["git"]
    ref = src.get("tag") or src.get("rev") or src.get("branch")
    if not ref:
        raise SystemExit("pyproject [tool.uv.sources].datalab needs a tag/rev/branch to publish")
    return f"datalab @ git+{git}@{ref}"


def build_wheel(dist_dir: str) -> None:
    """Build ONLY the framework wheel from the pinned git dep into ``dist_dir``.

    ``--no-deps`` keeps it to ``datalab`` alone (no pyspark etc.); the isolated
    ``dist_dir`` keeps it out of the bundle's ``dist/`` (which ``bundle deploy``
    fills with the per-domain ``<catalog>_etl`` wheels right after)."""
    req = _git_requirement()
    print(f"  building {req} -> {dist_dir}/")
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", req, "--no-deps", "-w", dist_dir],
        check=True,
    )


def wheel_path(version: str, dist_dir: str) -> Path:
    if version:
        exact = Path(dist_dir) / f"datalab-{version}-py3-none-any.whl"
        if exact.exists() or not list(Path(dist_dir).glob("datalab-*.whl")):
            return exact
    # version skew / unknown version: take the single built framework wheel
    built = sorted(Path(dist_dir).glob("datalab-*-py3-none-any.whl"))
    return built[-1] if built else Path(dist_dir) / f"datalab-{version}-py3-none-any.whl"


def target_catalogs(target: str, overrides: list[str]) -> list[str]:
    """The project catalogs to publish the wheel into — explicit ``--catalog``
    overrides, else the per-target domain catalogs from bootstrap_uc.CATALOGS."""
    return overrides or [catalog for catalog, _ in CATALOGS[target]]


def volume_dir(catalog: str) -> str:
    """The single /Volumes/<catalog>/artifacts/wheels dir for one project catalog."""
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
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument(
        "--build",
        action="store_true",
        help="build the framework wheel from the pinned git dep before uploading",
    )
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
        "--catalog",
        action="append",
        default=[],
        help="project catalog(s) to publish into (default: the target's domain catalogs); repeatable",
    )
    args = parser.parse_args(argv)

    if args.build:
        build_wheel(args.dist_dir)

    version = args.version or _default_version()
    local = wheel_path(version, args.dist_dir)
    catalogs = target_catalogs(args.target, args.catalog)

    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply (APPLY=1) to upload\n")
        print(f"   source: {_git_requirement()}")
        print(f"   wheel:  {local}" + ("" if local.exists() else "  (not built yet — pass --build)"))
        for catalog in catalogs:
            print(f"   -> {volume_dir(catalog)}/{local.name}")
        return

    if not local.exists():
        raise SystemExit(f"wheel not found: {local} — run with --build (or build into --dist-dir first)")
    for catalog in catalogs:
        upload(local, volume_dir(catalog), args.profile or None)
    print(f"published {local.name} to {len(catalogs)} catalog(s) for '{args.target}': {', '.join(catalogs)}")


if __name__ == "__main__":
    main(sys.argv[1:])
