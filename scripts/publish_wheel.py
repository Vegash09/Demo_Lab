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
builds ``datalab`` from the git ref in ``pyproject.toml`` (shallow clone + ``uv
build --wheel``; formerly ``pip wheel "datalab @
git+<url>@<tag>" --no-deps``); without it the script just uploads a wheel already
sitting in ``--dist-dir``.

    make publish-wheel TARGET=dev               # dry run (prints the build+upload plan)
    make publish-wheel TARGET=dev APPLY=1       # build from the git dep + upload via the SDK

Runs under ``uv run --with databricks-sdk`` so the SDK never
enters uv.lock. The target volumes must already exist: ``make bootstrap-uc
TARGET=<t>`` provisions each project catalog's ``artifacts.wheels`` volume.

NOTE: the per-target domain catalogs are resolved by the domain registry
(scripts/domains.py) from the same bundle files the deploy reads. If a deploy
overrides a domain catalog (the ``--var catalog=...`` escape hatch), pass
``--catalog-for <domain>=<name>`` to repoint THAT domain's upload to match (the
deploy-dab action does this automatically), or ``--catalog <name>`` (repeatable)
to replace the whole list.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

# Single source of truth for the per-target domain catalogs + the wheel volume
# location (scripts/ is on sys.path[0] when this file is run directly).
from domains import (
    ARTIFACTS_SCHEMA,
    WHEELS_VOLUME,
    domain_catalogs,
    framework_version,
    targets,
)

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


def _git_requirement(version: str = "") -> str:
    """``datalab @ git+<url>@<ref>`` — the release that will actually be built.

    ``version`` (the TARGET's resolved ``datalab_version``) selects the ref, so a
    target soak-testing a newer framework reports and builds that release. With
    no version it falls back to pyproject's ``[tool.uv.sources].datalab`` pin,
    which is the repo-wide default every target normally shares."""
    data = tomllib.loads(PYPROJECT.read_text())
    src = data["tool"]["uv"]["sources"]["datalab"]
    git = src["git"]
    ref = f"v{version}" if version else (
        src.get("tag") or src.get("rev") or src.get("branch")
    )
    if not ref:
        raise SystemExit("pyproject [tool.uv.sources].datalab needs a tag/rev/branch to publish")
    return f"datalab @ git+{git}@{ref}"


def build_wheel(dist_dir: str, version: str = "") -> None:
    """Build ONLY the framework wheel from the pinned git dep into ``dist_dir``.

    Shallow-clones the pinned tag into a temp dir and runs ``uv build --wheel``.
    This used to shell ``python -m pip wheel <git url>``, which does not work in a
    uv-created venv: uv installs no pip, so the call dies with "No module named
    pip". It only appeared to work because the Makefile injected ``--with pip``;
    running the script directly always failed.
    Cloning + ``uv build`` needs neither pip nor a resolver pass, and uv is
    already a hard prerequisite for `bundle deploy`.

    The isolated ``dist_dir`` keeps the framework wheel out of the bundle's
    ``dist/`` (which ``bundle deploy`` fills with the domain wheel right after).
    Stale framework wheels from earlier bumps are removed first so the strict
    ``wheel_path`` check below can never pick one up.
    """
    for stale in Path(dist_dir).glob("datalab-*.whl"):
        print(f"  removing stale {stale}")
        stale.unlink()

    data = tomllib.loads(PYPROJECT.read_text())
    src = data["tool"]["uv"]["sources"]["datalab"]
    url = src["git"]
    # Build the version this TARGET installs. Normally identical to the pyproject
    # pin; when a target soak-tests a newer framework via a `datalab_version`
    # override (targets/stage.yml), it is that release that must be built and
    # published — building the pyproject pin instead would upload a wheel under a
    # filename var.datalab_wheel never looks for.
    ref = f"v{version}" if version else (src.get("tag") or src.get("rev") or src.get("branch"))
    out = Path(dist_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"  building datalab @ git+{url}@{ref} -> {dist_dir}/")
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "datalab-framework"
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, url, str(checkout)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out)],
            cwd=checkout,
            check=True,
        )


def wheel_path(version: str, dist_dir: str) -> Path:
    """The wheel to upload — STRICT: publishing anything but the pinned version
    would silently break every environment referencing var.datalab_wheel.

    With a known version, only the exact ``datalab-<version>-…`` filename is
    accepted (a stale wheel from an earlier bump sitting in dist_dir must never
    win). Without one (isolated env where ``datalab`` isn't importable), the
    dist dir must contain exactly one framework wheel."""
    built = sorted(Path(dist_dir).glob("datalab-*-py3-none-any.whl"))
    if version:
        exact = Path(dist_dir) / f"datalab-{version}-py3-none-any.whl"
        others = [w for w in built if w != exact]
        if others:
            raise SystemExit(
                f"{dist_dir}/ holds framework wheel(s) other than the pinned {version}: "
                f"{', '.join(w.name for w in others)} — remove them (stale earlier "
                "builds) and re-run with --build"
            )
        return exact
    if len(built) != 1:
        raise SystemExit(
            f"cannot determine which wheel to publish: found {len(built)} framework "
            f"wheels in {dist_dir}/ and no --version to disambiguate"
        )
    return built[0]


def target_catalogs(target: str, replace: list[str], per_domain: list[str]) -> list[str]:
    """The project catalogs to publish the wheel into.

    Default: every domain's catalog for ``target`` from the registry. ``--catalog``
    (``replace``) swaps in an explicit list; ``--catalog-for domain=name``
    (``per_domain``) repoints single domains — matching the ``--var`` overrides a
    deploy may apply, so the wheel lands where the pipelines will look."""
    if replace and per_domain:
        raise SystemExit("--catalog and --catalog-for are mutually exclusive")
    if replace:
        return replace
    resolved = domain_catalogs(target)
    for item in per_domain:
        domain, sep, catalog = item.partition("=")
        if not sep or not catalog:
            raise SystemExit(f"--catalog-for expects <domain>=<catalog>, got {item!r}")
        if domain not in resolved:
            raise SystemExit(
                f"--catalog-for: unknown domain {domain!r} (registry has: {', '.join(resolved)})"
            )
        resolved[domain] = catalog
    return list(resolved.values())


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
    parser.add_argument("--target", choices=targets(), required=True)
    parser.add_argument(
        "--build",
        action="store_true",
        help="build the framework wheel from the pinned git dep before uploading",
    )
    parser.add_argument(
        "--version",
        default="",
        help="framework version (default: the target's resolved var.datalab_version)",
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
        help="project catalog(s) to publish into, REPLACING the registry list; repeatable",
    )
    parser.add_argument(
        "--catalog-for",
        action="append",
        default=[],
        metavar="DOMAIN=CATALOG",
        help="repoint ONE domain's upload catalog (matches a deploy's --var catalog "
        "override); repeatable, other domains keep their registry catalogs",
    )
    args = parser.parse_args(argv)

    # The version THIS target installs: an explicit --version, else the target's
    # resolved `datalab_version` (per-target override or the medallion default).
    # NOT datalab.__version__ — that is whatever the repo-wide pyproject pin
    # installed locally, which is not what a soak-testing target's
    # var.datalab_wheel points at.
    version = args.version or framework_version(args.target)
    pinned = _default_version()
    if pinned and version != pinned:
        print(
            f"  note: target {args.target!r} installs datalab {version} while this repo's "
            f"pyproject pin is {pinned} — building and publishing {version} "
            "(a deliberate per-target override; see targets/)"
        )

    if args.build:
        build_wheel(args.dist_dir, version)

    local = wheel_path(version, args.dist_dir)
    catalogs = target_catalogs(args.target, args.catalog, args.catalog_for)

    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply (APPLY=1) to upload\n")
        print(f"   source: {_git_requirement(version)}")
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
