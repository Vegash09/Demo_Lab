"""Generate a minimal datalab adopter repo from this reference repo.

One deterministic command — no per-run agent surgery. It copies the repo-level
scaffold (bundle manifest, variables/targets/rbac, scripts, schemas, CI, agent
harness, docs, githooks), DROPS the reference domains (``projects/``) and design
assets, writes ONE minimal root-level domain renamed to your catalog, and
rewrites the repo-level files for the adopter layout (single-package
``pyproject.toml``, root ``resources/``, single catalog).

    python scripts/scaffold_adopter.py --catalog acme --out ../acme-datalab \\
        [--host https://<workspace>] [--deploy-sp <app-id>] \\
        [--reader-group acme_readers] [--engineer-group acme_engineers] \\
        [--admin-group acme_admins] [--framework-tag v0.3.0] [--force]

Then, inside the generated repo:

    git init -b main && make lock install && make validate-configs lint test

This is the deterministic equivalent of the ``bootstrap-adopter-repo`` agent
skill; the file templates here mirror that skill's
``references/templates.md``. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Top-level TRACKED entries NOT copied into the adopter: the reference domains,
# design assets, dev-time pilot, and the lockfile (regenerated for the single
# package). We copy only git-TRACKED files, so secrets (.env), local state
# (.venv/.databricks), and build output (dist/) are excluded automatically.
EXCLUDE_TOP = {"projects", "design", "omnigent", "uv.lock"}

CATALOG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# --------------------------------------------------------------------------- #
# File templates (placeholders substituted by `ctx`).
# --------------------------------------------------------------------------- #

DOMAIN_YML = """\
# yaml-language-server: $schema=../../schemas/domain_config.schema.json
#
# Domain settings — environment-agnostic: catalog/schema values are pipeline-conf
# KEYS resolved per target (dev/stage/prod) through bundle variables. Never put a
# literal catalog name here.
schema_version: 1
domain: @@CATALOG@@
imports: [] # python modules registering @transform fns + custom checks
catalog_conf: datalab.catalog
layers:
  bronze:
    schema_conf: datalab.bronze_schema
    table_properties:
      datalab.layer: bronze
  silver:
    schema_conf: datalab.silver_schema
    table_properties:
      datalab.layer: silver
  gold:
    schema_conf: datalab.gold_schema
    table_properties:
      datalab.layer: gold
"""

BRONZE_YML = """\
# yaml-language-server: $schema=../../../schemas/table_config.schema.json
#
# Starter table: bronze.events_raw — raw incremental ingest (Auto Loader).
# Add silver/gold with the author-ldp-artifact skill.
schema_version: 1
name: events_raw
comment: Raw events ingested incrementally from the landing volume (Auto Loader).
source:
  kind: cloud_files
  path_conf: datalab.landing_path
  format: json
  options:
    cloudFiles.inferColumnTypes: "true" # quote YAML-1.1 ambiguous scalars
    cloudFiles.schemaEvolutionMode: addNewColumns
  add_lineage: true # framework adds _ingest_ts + _source_file
target:
  kind: streaming_table
"""

PKG_INIT = '''\
"""@@CATALOG@@_etl — the @@CATALOG@@ domain's adoption of the datalab framework.

Domain-owned code only: transforms/ (pure functions), checks/ (custom dqx
checks), transformations/pipeline.py (the LDP entrypoint). The reusable
framework lives in ``datalab`` and is never edited from here.
"""
'''

TRANSFORMS_INIT = '''\
"""Pure @transform functions for the @@CATALOG@@ domain (registered via decorators)."""
'''

CHECKS_INIT = '''\
"""Custom @check_function dqx checks for the @@CATALOG@@ domain."""
'''

PIPELINE_PY = '''\
"""@@CATALOG@@_etl pipeline entrypoint — the entire domain is config-driven.

Datasets, transforms and dqx quality rules live in the domain's config dir (the
bundle supplies the deployed path as ``datalab.config_dir``); the framework
validates them and registers every LDP dataset. Add a table by editing YAML —
see docs/GETTING_STARTED.md.
"""

from pyspark.sql import SparkSession

from datalab.config import pipeline_conf
from datalab.framework import generate

# The active session is the SDP-runtime session on Databricks and the session the
# OSS `spark-pipelines` CLI creates locally — one entrypoint, every profile.
spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
generate(spark, pipeline_conf(spark, "datalab.config_dir"))
'''

PIPELINE_RESOURCE = """\
# Lakeflow Spark Declarative Pipeline for the @@CATALOG@@ domain (bronze→silver→gold).
# Paths below are relative to THIS file (resources/ sits beside src/ and dist/).
resources:
  pipelines:
    @@CATALOG@@_etl:
      name: @@CATALOG@@_etl
      catalog: ${var.catalog}
      schema: ${var.silver_schema}
      serverless: true
      channel: CURRENT
      root_path: "../src/@@CATALOG@@_etl"

      libraries:
        - glob:
            include: ../src/@@CATALOG@@_etl/transformations/**

      environment:
        environment_version: "4"
        dependencies:
          # datalab FRAMEWORK wheel from THIS catalog's artifacts.wheels Volume
          # (make publish-wheel; bump var.datalab_version to roll it). Serverless
          # does NOT honor an --editable install of synced workspace files.
          - ${var.datalab_wheel}
          # This domain's wheel — built by the bundle's @@CATALOG@@_etl_wheel artifact.
          - ../dist/@@CATALOG@@_etl-*.whl

      configuration:
        datalab.env: ${bundle.target}
        datalab.catalog: ${var.catalog}
        datalab.bronze_schema: ${var.bronze_schema}
        datalab.silver_schema: ${var.silver_schema}
        datalab.gold_schema: ${var.gold_schema}
        datalab.landing_path: ${var.landing_path}
        datalab.config_dir: ${workspace.file_path}/config/@@CATALOG@@

      permissions: ${var.pipeline_permissions}
"""

JOB_RESOURCE = """\
# Scheduled refresh of the @@CATALOG@@_etl pipeline (paused in dev).
resources:
  jobs:
    @@CATALOG@@_etl_refresh:
      name: @@CATALOG@@_etl_refresh
      trigger:
        periodic:
          interval: 1
          unit: DAYS
      tasks:
        - task_key: refresh_@@CATALOG@@_etl
          pipeline_task:
            pipeline_id: ${resources.pipelines.@@CATALOG@@_etl.id}
      queue:
        enabled: true
      permissions: ${var.job_permissions}
"""

CONFTEST_PY = '''\
"""Local SparkSession fixture for the @@CATALOG@@ domain tests."""

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .appName("@@CATALOG@@-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
'''

SMOKE_TEST_PY = '''\
"""Smoke test: the domain package imports (keeps `make test` non-empty)."""

import importlib


def test_domain_package_imports():
    assert importlib.import_module("@@CATALOG@@_etl") is not None
'''

DATABRICKS_YML = """\
# Declarative Automation Bundle for the @@CATALOG@@ datalab adopter repo.
# Thin manifest: bundle name + includes. Everything else is deep-merged in.
bundle:
  name: @@CATALOG@@

# One wheel: this domain's package (uv build at the root). The framework wheel is
# delivered separately from the UC Volume (var.datalab_wheel). uv must be on PATH
# for `bundle deploy`.
artifacts:
  @@CATALOG@@_etl_wheel:
    type: whl
    build: uv build --wheel
    path: .

include:
  - variables/*.yml
  - targets/*.yml
  - rbac.yml
  - resources/*.yml

# Dev-only surfaces kept OUT of the deployed workspace files (DAB ignores
# .databricksignore; sync.exclude is the bundle-effective mechanism). Keep this
# aligned with .databricksignore.
sync:
  exclude:
    - tests
    - docs
    - .github
    - .claude
    - .cursor
    - .codex
    - .agents
    - .githooks
    - Makefile
    - uv.lock
    - .markdownlint.json
"""

PYPROJECT_TOML = """\
# @@CATALOG@@ — single-domain adopter repo for the datalab framework.
#
# The reusable FRAMEWORK lives in dediggibyte/datalab-framework and is consumed:
#   * local dev / CI         → the `datalab` git dependency (pinned to a tag);
#   * Databricks serverless  → the versioned wheel from this catalog's
#     artifacts.wheels UC Volume (var.datalab_wheel), listed in each resource.
# KEEP IN LOCKSTEP: the `datalab` git tag below and var.datalab_version.

[build-system]
requires      = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name            = "@@CATALOG@@_etl"
version         = "0.1.0"
description     = "@@CATALOG@@ medallion (bronze→silver→gold) — datalab adopter domain."
requires-python = ">=3.12,<3.14"
dependencies    = []

[tool.hatch.build.targets.wheel]
packages = ["src/@@CATALOG@@_etl"]

[dependency-groups]
dev = [
    "pytest>=8.4",
    "ruff>=0.14",
    # Local Spark for tests + the OSS local-run profile. Never add
    # databricks-connect here (conflicts with pyspark; use `make validate-connect`).
    "pyspark[pipelines]>=4.1.0",
    "pandas>=2.0",
    # The framework, pinned to a release tag (source mapped to git below). Keep the
    # tag in lockstep with var.datalab_version (the serverless UC-Volume wheel).
    "datalab",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts   = "-ra --tb=short"

[tool.ruff]
line-length    = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
ignore = ["E501"]

[tool.ruff.lint.isort]
known-first-party = ["datalab", "@@CATALOG@@_etl"]

[tool.ruff.lint.per-file-ignores]
# `spark` is injected by the SDP runtime in the pipeline entrypoint; notebooks
# additionally get ambient dbutils/display (F821) + cell imports (E402).
"src/*/transformations/**" = ["F821"]
"notebooks/**" = ["F821", "E402"]

[tool.uv]
managed = true

[tool.uv.sources]
datalab = { git = "https://github.com/dediggibyte/datalab-framework.git", tag = "@@FRAMEWORK_TAG@@" }
"""

VARIABLES_MEDALLION = """\
# Bundle variable declarations + defaults for the @@CATALOG@@ medallion.
# Per-target VALUES live in targets/<env>.yml; access control in rbac.yml.
variables:
  catalog:
    description: Unity Catalog catalog that holds the medallion schemas.
    default: @@CATALOG@@
  bronze_schema:
    description: Schema for raw/ingested data.
    default: bronze
  silver_schema:
    description: Schema for cleaned, validated data.
    default: silver
  gold_schema:
    description: Schema for business-level aggregates.
    default: gold
  landing_path:
    description: UC volume path where raw JSON files land (Auto Loader source).
    default: /Volumes/${var.catalog}/landing/@@CATALOG@@/events/
  # --- framework wheel distribution (lockstep with the datalab git tag) -------
  datalab_version:
    description: Version of the datalab framework wheel installed from this catalog's artifacts.wheels volume.
    default: "@@DATALAB_VERSION@@"
  datalab_wheel:
    description: UC Volume path of the framework wheel in this catalog (var.catalog).
    default: /Volumes/${var.catalog}/artifacts/wheels/datalab-${var.datalab_version}-py3-none-any.whl
"""

TARGET_DEV = """\
# dev target — development copies: resources get a '[dev <user>]' prefix and
# schedules/triggers are paused automatically.
targets:
  dev:
    mode: development
    default: true
    workspace:
      host: @@HOST@@
    variables:
      catalog: @@CATALOG@@
"""

TARGET_STAGE = """\
# stage target — production mode, explicit root_path.
targets:
  stage:
    mode: production
    workspace:
      host: @@HOST@@
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: @@CATALOG@@_stage
"""

TARGET_PROD = """\
# prod target — production mode, explicit root_path.
targets:
  prod:
    mode: production
    workspace:
      host: @@HOST@@
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: @@CATALOG@@_prod
"""

README_MD = """\
# @@CATALOG@@-datalab

Single-domain [datalab](https://github.com/dediggibyte/datalab-framework) adopter
repo for **@@CATALOG@@**, generated from the datalab template. Every target table
is ONE YAML artifact, generated into Lakeflow Spark Declarative Pipelines,
quality-checked with dqx, and deployed as a Declarative Automation Bundle.

> Document of record for agents + humans: **[AGENTS.md](AGENTS.md)**. Wiring to
> the framework: **[docs/ADOPTING.md](docs/ADOPTING.md)**. Author your first table:
> **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**.

## Quick start

```bash
make lock install              # resolve the framework git dep into .venv
make validate-configs lint test  # pydantic + dqx · ruff · pytest (local Spark)
make validate                  # databricks bundle validate -t dev

# first deploy (one-time UC bootstrap + framework wheel publish):
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<id>
make publish-wheel TARGET=dev APPLY=1
make deploy && make run
```

## Add tables

Use the `author-ldp-artifact` agent skill: one `config/@@CATALOG@@/<layer>/<table>.yml`
artifact per table, pure `@transform` functions in `src/@@CATALOG@@_etl/transforms/`,
registered in `config/@@CATALOG@@/domain.yml` `imports:`.
"""

CHANGELOG_MD = """\
# Changelog

## Unreleased

- Initial @@CATALOG@@ adopter repo generated from the datalab template
  (one minimal bronze table; extend with the author-ldp-artifact skill).
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def framework_tag(default: str = "main") -> str:
    """Read the pinned `datalab` git tag from this repo's pyproject.toml."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    src = data.get("tool", {}).get("uv", {}).get("sources", {}).get("datalab", {})
    return src.get("tag") or src.get("rev") or src.get("branch") or default


def copy_scaffold(out: Path) -> None:
    """Copy every git-TRACKED file except the reference/dev-only top-level set.

    Using `git ls-files` (not a filesystem walk) means gitignored files —
    secrets (.env), .venv, .databricks, dist/ build output — are never copied.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [p for p in result.stdout.split("\0") if p]
    if not tracked:
        raise SystemExit("scaffold: `git ls-files` returned nothing — run inside the repo")
    for rel in tracked:
        if rel.split("/", 1)[0] in EXCLUDE_TOP or rel == "uv.lock":
            continue
        src = REPO_ROOT / rel
        if not src.is_file():  # skip submodule gitlinks etc.
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def require_replace(text: str, old: str, new: str, where: str) -> str:
    """str.replace that fails loudly if the anchor is missing (drift guard)."""
    if old not in text:
        raise SystemExit(f"scaffold: expected anchor not found in {where}: {old!r}")
    return text.replace(old, new)


def patch_makefile(out: Path, catalog: str) -> None:
    path = out / "Makefile"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "projects/customer_sales/config/customer_sales", f"config/{catalog}"
    )
    text = text.replace(
        "projects/customer_sales/src/customer_sales_etl/transformations",
        f"src/{catalog}_etl/transformations",
    )
    text = text.replace(
        "projects/customer_sales/sample_data/landing/sales/customers",
        f"sample_data/landing/{catalog}/events",
    )
    text = text.replace(
        "CONNECT_DOMAIN ?= projects/customer_sales", "CONNECT_DOMAIN ?= ."
    )
    text = require_replace(
        text, "LINT_PATHS := scripts projects", "LINT_PATHS := scripts src", "Makefile"
    )
    text = require_replace(
        text,
        "databricks bundle run customer_sales_etl",
        f"databricks bundle run {catalog}_etl",
        "Makefile",
    )
    text = text.replace("datalab.sales_landing_path=file://", "datalab.landing_path=file://")
    path.write_text(text, encoding="utf-8")


def patch_bootstrap_uc(out: Path, catalog: str, ctx: dict[str, str]) -> None:
    path = out / "scripts" / "bootstrap_uc.py"
    text = path.read_text(encoding="utf-8")
    catalogs = (
        "CATALOGS = {\n"
        f'    "dev":   [("{catalog}",       True)],\n'
        f'    "stage": [("{catalog}_stage", True)],\n'
        f'    "prod":  [("{catalog}_prod",  True)],\n'
        "}"
    )
    reader, engineer = ctx["@@READER_GROUP@@"], ctx["@@ENGINEER_GROUP@@"]
    groups = (
        "GROUPS = {\n"
        f'    "dev":   {{"reader": "{reader}", "engineer": "{engineer}"}},\n'
        f'    "stage": {{"reader": "{reader}", "engineer": "{engineer}"}},\n'
        f'    "prod":  {{"reader": "{reader}", "engineer": "{engineer}"}},\n'
        "}"
    )
    text, n1 = re.subn(r"^CATALOGS = \{.*?^\}", catalogs, text, count=1, flags=re.M | re.S)
    text, n2 = re.subn(r"^GROUPS = \{.*?^\}", groups, text, count=1, flags=re.M | re.S)
    text, n3 = re.subn(
        r'^DEPLOY_SP = ".*?"', f'DEPLOY_SP = "{ctx["@@DEPLOY_SP@@"]}"', text, count=1, flags=re.M
    )
    if not (n1 and n2 and n3):
        raise SystemExit("scaffold: could not patch scripts/bootstrap_uc.py constants")
    path.write_text(text, encoding="utf-8")


def patch_rbac(out: Path, ctx: dict[str, str]) -> None:
    path = out / "rbac.yml"
    text = path.read_text(encoding="utf-8")
    for old, key in (
        ("default: demo_analyst", "@@READER_GROUP@@"),
        ("default: Data Science group", "@@ENGINEER_GROUP@@"),
        ("default: dl_platform_admins", "@@ADMIN_GROUP@@"),
        ("reader_group: dl_sales_readers", "@@READER_GROUP@@"),
        ("engineer_group: dl_sales_engineers", "@@ENGINEER_GROUP@@"),
    ):
        prefix = old.split(":")[0]
        text = text.replace(old, f"{prefix}: {ctx[key]}")
    path.write_text(text, encoding="utf-8")


def patch_ci(out: Path) -> None:
    path = out / ".github" / "workflows" / "common-ci-steps.yml"
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text, "ruff check scripts projects", "ruff check scripts src", "common-ci-steps.yml"
    )
    path.write_text(text, encoding="utf-8")


def patch_databricksignore(out: Path) -> None:
    path = out / ".databricksignore"
    if not path.exists():
        return
    kept = [ln for ln in path.read_text(encoding="utf-8").splitlines() if "projects/" not in ln]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def write_domain(out: Path, ctx: dict[str, str], subst) -> None:
    cat = ctx["@@CATALOG@@"]
    files = {
        f"config/{cat}/domain.yml": DOMAIN_YML,
        f"config/{cat}/bronze/events_raw.yml": BRONZE_YML,
        f"src/{cat}_etl/__init__.py": PKG_INIT,
        f"src/{cat}_etl/transformations/pipeline.py": PIPELINE_PY,
        f"src/{cat}_etl/transforms/__init__.py": TRANSFORMS_INIT,
        f"src/{cat}_etl/checks/__init__.py": CHECKS_INIT,
        f"resources/{cat}_etl.pipeline.yml": PIPELINE_RESOURCE,
        f"resources/{cat}_etl.job.yml": JOB_RESOURCE,
        "tests/conftest.py": CONFTEST_PY,
        "tests/test_smoke.py": SMOKE_TEST_PY,
    }
    for rel, template in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(subst(template), encoding="utf-8")
    # NB: do NOT pre-create empty silver/gold layer dirs — the framework config
    # validator rejects an empty layer dir. The author-ldp-artifact skill creates
    # them when the first silver/gold table is added.


def write_repo_level(out: Path, subst) -> None:
    files = {
        "databricks.yml": DATABRICKS_YML,
        "pyproject.toml": PYPROJECT_TOML,
        "variables/medallion.yml": VARIABLES_MEDALLION,
        "targets/dev.yml": TARGET_DEV,
        "targets/stage.yml": TARGET_STAGE,
        "targets/prod.yml": TARGET_PROD,
        "README.md": README_MD,
        "CHANGELOG.md": CHANGELOG_MD,
    }
    for rel, template in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(subst(template), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, help="base catalog / domain name (lowercase)")
    parser.add_argument("--out", required=True, help="output directory for the new repo")
    parser.add_argument("--host", default="https://<your-workspace-host>", help="Databricks workspace URL")
    parser.add_argument("--deploy-sp", default="<deploy-sp-app-id>", help="CI/CD deploy SP application id")
    parser.add_argument("--reader-group", default="", help="reader group (default: <catalog>_readers)")
    parser.add_argument("--engineer-group", default="", help="engineer group (default: <catalog>_engineers)")
    parser.add_argument("--admin-group", default="", help="admin group (default: <catalog>_admins)")
    parser.add_argument("--framework-tag", default="", help="datalab framework tag (default: this repo's pin)")
    parser.add_argument("--force", action="store_true", help="overwrite a non-empty --out")
    args = parser.parse_args(argv)

    catalog = args.catalog.strip()
    if not CATALOG_RE.match(catalog):
        parser.error("--catalog must be lowercase letters/digits/underscores, starting with a letter")

    out = Path(args.out).expanduser().resolve()
    if out == REPO_ROOT:
        parser.error("--out must not be this repo")
    if out.exists() and any(out.iterdir()):
        if not args.force:
            parser.error(f"{out} exists and is not empty (use --force to overwrite)")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    tag = args.framework_tag or framework_tag()
    ctx = {
        "@@CATALOG@@": catalog,
        "@@HOST@@": args.host,
        "@@FRAMEWORK_TAG@@": tag,
        "@@DATALAB_VERSION@@": tag.lstrip("v"),
        "@@READER_GROUP@@": args.reader_group or f"{catalog}_readers",
        "@@ENGINEER_GROUP@@": args.engineer_group or f"{catalog}_engineers",
        "@@ADMIN_GROUP@@": args.admin_group or f"{catalog}_admins",
        "@@DEPLOY_SP@@": args.deploy_sp,
    }

    def subst(text: str) -> str:
        for key, value in ctx.items():
            text = text.replace(key, value)
        return text

    print(f"scaffold: generating '{catalog}' adopter repo at {out}")
    copy_scaffold(out)
    write_domain(out, ctx, subst)
    write_repo_level(out, subst)
    patch_makefile(out, catalog)
    patch_bootstrap_uc(out, catalog, ctx)
    patch_rbac(out, ctx)
    patch_ci(out)
    patch_databricksignore(out)

    print("scaffold: done. Next:")
    rel = args.out
    print(f"  cd {rel} && git init -b main && make lock install")
    print("  make validate-configs lint test")
    print("  # set the real workspace host (targets/*.yml), groups (rbac.yml),")
    print("  # deploy SP (scripts/bootstrap_uc.py) + CI secrets — see docs/ADOPTING.md")
    if "<" in args.host or "<" in args.deploy_sp:
        print("  NOTE: --host / --deploy-sp left as placeholders; fill them before deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
