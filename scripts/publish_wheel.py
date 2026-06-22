"""Build + publish the common datalab FRAMEWORK wheel to the shared artifacts UC Volume.

Distribution model: the framework lives in its OWN repo
(``dediggibyte/datalab-framework``) and is consumed here two ways — a git
dependency for local/CI (pinned in ``pyproject.toml`` ``[tool.uv.sources]``) and
a versioned wheel (``datalab-<ver>-py3-none-any.whl``) that every pipeline/job
environment — across ALL domains — installs from a single shared Volume,
``/Volumes/<datalab_artifacts_catalog>/framework/wheels/`` (see
variables/medallion.yml ``datalab_artifacts_catalog`` / ``datalab_wheel``).

This repo (the adopter/reference bundle) BUILDS that wheel from the pinned git
dependency and uploads it — one upload per target serves the customer_sales and
sales pipelines alike. ``--build`` clones+builds ``datalab`` from the git ref in
``pyproject.toml`` (``pip wheel "datalab @ git+<url>@<tag>" --no-deps``); without
it the script just uploads a wheel already sitting in ``--dist-dir``.

    make publish-wheel TARGET=dev               # dry run (prints the build+upload plan)
    make publish-wheel TARGET=dev APPLY=1       # build from the git dep + upload via the SDK

Runs under ``uv run --with databricks-sdk --with pip`` so neither the SDK nor pip
enters uv.lock (the dev venv stays pyspark-only — see AGENTS.md). The Volume must
already exist: ``make bootstrap-uc TARGET=<t>`` provisions the shared catalog +
framework.wheels.

NOTE: the per-target artifacts catalog name comes from
bootstrap_uc.ARTIFACTS_CATALOGS (the bundle defaults). If a target overrides it
(the deploy `--var datalab_artifacts_catalog=...` escape hatch), pass
--artifacts-catalog to match, or the upload lands in the wrong catalog.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

# Single source of truth for the target -> shared artifacts catalog mapping
# (scripts/ is on sys.path[0] when this file is run directly).
from bootstrap_uc import ARTIFACTS_CATALOGS, FRAMEWORK_SCHEMA, FRAMEWORK_VOLUME

ARTIFACTS_PATH = f"{FRAMEWORK_SCHEMA}/{FRAMEWORK_VOLUME}"  # <catalog>.framework.wheels Volume
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
        "--artifacts-catalog",
        default="",
        help="override the shared artifacts catalog name (rare; matches deploy --var datalab_artifacts_catalog)",
    )
    args = parser.parse_args(argv)

    if args.build:
        build_wheel(args.dist_dir)

    version = args.version or _default_version()
    local = wheel_path(version, args.dist_dir)
    dest = volume_dir(args.target, args.artifacts_catalog)

    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply (APPLY=1) to upload\n")
        print(f"   source: {_git_requirement()}")
        print(f"   wheel:  {local}" + ("" if local.exists() else "  (not built yet — pass --build)"))
        print(f"   -> {dest}/{local.name}")
        return

    if not local.exists():
        raise SystemExit(f"wheel not found: {local} — run with --build (or build into --dist-dir first)")
    upload(local, dest, args.profile or None)
    print(f"published {local.name} to target '{args.target}'")


if __name__ == "__main__":
    main(sys.argv[1:])
