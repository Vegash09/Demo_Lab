"""Configure a minimal datalab adopter repo — deterministically, no per-run surgery.

It DROPS the reference domains (``projects/``), design assets and the dev-time
pilot (``omnigent/``), writes ONE minimal root-level domain renamed to your
catalog, rewrites the repo-level files for the adopter layout (single-package
``pyproject.toml``, root ``resources/``, single catalog) and repoints the
workspace-specific surfaces at your workspace — including the MCP grounding
config (``.mcp.json`` / ``.cursor/mcp.json``), which the old flow left pointing
at the template's workspace.

Two run modes:

* ``--in-place`` — convert the CURRENT repo (a clone you made from the GitHub
  template) into the adopter, editing it in place. This is the path the
  ``bootstrap-adopter-repo`` skill / ``make configure-adopter`` drive.
* ``--out <dir>`` — generate a fresh sibling repo from this one, copying only
  git-tracked files (never secrets/state/build output). This is ``make
  new-adopter``.

Add ``--interactive`` to be PROMPTED for the two irreducible values — catalog and
host (each skipped when its flag was passed) — and to confirm a summary; every
other value (SQL warehouse id, MCP CLI profile, RBAC groups, deploy SP, framework
tag) takes its flag or a derived default, with remaining placeholders printed as
fill-before-deploy TODOs. Otherwise pass values as flags (the agent/CI path).

    # convert a template clone in place, prompting for everything:
    python scripts/scaffold_adopter.py --in-place --interactive

    # non-interactive (agent/CI), every value supplied:
    python scripts/scaffold_adopter.py --in-place --yes --catalog acme \\
        --host https://<workspace> --warehouse-id <id> --mcp-profile acme_dev \\
        --deploy-sp <app-id> --reader-group acme_readers \\
        --engineer-group acme_engineers --admin-group acme_admins

    # fresh sibling repo:
    python scripts/scaffold_adopter.py --catalog acme --out ../acme-datalab \\
        [--host …] [--deploy-sp …] [--warehouse-id …] [--mcp-profile …] [--force]

Then, inside the configured repo:

    git init -b main && make lock install && make validate-configs lint test

The ``<catalog>`` must be the BASE catalog name (lowercase, no ``_dev`` /
``_stage`` / ``_prod`` suffix — the bundle appends those per target; see
``docs/NAMING.md``); a suffixed name is rejected. This is the deterministic
engine behind the ``bootstrap-adopter-repo`` agent skill; the file templates
here mirror that skill's ``references/templates.md``. Stdlib only.
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

# Top-level TRACKED entries NOT copied into the adopter (sibling mode), and the
# set REMOVED from the clone in --in-place mode: the reference domains, design
# assets, dev-time pilot, and the lockfile (regenerated for the single package).
# In sibling mode we copy only git-TRACKED files, so secrets (.env), local state
# (.venv/.databricks), and build output (dist/) are excluded automatically.
EXCLUDE_TOP = {"projects", "design", "omnigent", "uv.lock"}

CATALOG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# The bundle appends these per target (targets/<env>.yml), so the BASE catalog
# folder/var must not already carry one — `xflow_prod` would deploy
# `xflow_prod_prod`. Reject by default; --allow-env-suffix overrides.
ENV_SUFFIXES = ("_dev", "_stage", "_prod")

# Canonical template repo. --in-place refuses to run against it (you would be
# converting the template itself, not an adopter clone); --force overrides.
TEMPLATE_SLUG = "dediggibyte/datalab"

# The template's own MCP grounding workspace, hardcoded in .mcp.json and
# .cursor/mcp.json. patch_mcp swaps these for the adopter's so the read-only
# Databricks queries hit the customer's workspace (AGENTS.md "Databricks MCP").
TEMPLATE_MCP_PROFILE = "diggi_dev_aws"
TEMPLATE_WAREHOUSE_ID = "c1cdbe2406e5cf04"

# The template's own Databricks workspace + CI/CD deploy service principal, both
# baked into docs/ (CICD.md's federation-policy command, AGENT_MCP.md's auth
# commands). Repointed at the adopter's, or a first-timer copying a command out
# of their OWN docs authenticates against the template's workspace/SP.
TEMPLATE_HOST = "https://dbc-425be768-f138.cloud.databricks.com"
TEMPLATE_DEPLOY_SP = "437346a1-0b53-418a-80d4-abaf2586ed97"

# Placeholder default for --host: interactive mode prompts only while the flag
# still holds this sentinel (a passed flag skips the prompt).
HOST_PLACEHOLDER = "https://<your-workspace-host>"


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
        # Pins the Python runtime + preinstalled library set independently of DBR
        # upgrades. COMMENTED OUT for the FIRST deploy: Databricks gates enabling
        # environment_version on a new pipeline behind a fingerprint check that
        # rejects it (NO_PREVIOUS_FINGERPRINT, then FINGERPRINT_MISMATCH) and
        # leaves the pipeline unable to run until the setting is removed. Every
        # documented remedy was tried against a real pipeline (2026-08),
        # including a compatibility scan that reported ZERO issues while the gate
        # still refused. Uncomment once the pipeline has a stable update history
        # — see docs/ADOPTING.md "environment_version".
        # environment_version: "4"
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
# aligned with .databricksignore — `make check-sync-lists` (CI) enforces it.
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
    - .mcp.json
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
requires      = ["hatchling>=1.31.0"]
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
    # Capped: the OSS SDP subset moves between minors (4.2.0 added an abstract
    # method to GraphElementRegistry and an SCD1-only create_auto_cdc_flow).
    # Needs datalab >= 0.8.2 for 4.2. Raise deliberately, after running tests.
    "pyspark[pipelines]>=4.1.0,<4.3",
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
make lock install                # resolve the framework git dep into .venv
make enable-githooks             # protected-files pre-commit guard (one-time)
make validate-configs lint test  # pydantic + dqx · ruff · pytest (local Spark)
make validate                    # databricks bundle validate -t dev
```

## First deploy (one-time setup per target)

The full ordered checklist — prerequisites, GitHub/OIDC wiring, and the
account-level persona groups that must exist BEFORE bootstrap — is
**[docs/NEW_ADOPTER.md](docs/NEW_ADOPTER.md)**. The commands, once those
prerequisites stand (`PROFILE=` pins the workspace — without it the SDK uses
your DEFAULT CLI profile, which may point somewhere else):

```bash
databricks auth login --host <workspace-url> --profile <cli-profile>
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<id> PROFILE=<cli-profile>
make publish-wheel TARGET=dev APPLY=1 PROFILE=<cli-profile>
git add -A && git commit -m "configure @@CATALOG@@ adopter" && git push  # CI needs the regenerated uv.lock
make deploy
databricks fs cp sample_data/landing/@@CATALOG@@/events/events.json \\
    dbfs:/Volumes/@@CATALOG@@/landing/@@CATALOG@@/events/ --profile <cli-profile>
make run
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

# Starter sample landing data so `make run-local` (and the "bronze.events_raw
# materializes" done check) work out of the box — the Makefile's LOCAL_LANDING
# points at exactly this directory.
SAMPLE_EVENTS_JSON = """\
{"event_id": "e-0001", "event_type": "signup", "user_id": "u-001", "ts": "2026-01-15T09:30:00Z"}
{"event_id": "e-0002", "event_type": "login", "user_id": "u-001", "ts": "2026-01-16T08:02:11Z"}
{"event_id": "e-0003", "event_type": "purchase", "user_id": "u-002", "ts": "2026-01-16T12:44:03Z"}
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def framework_tag(default: str = "main") -> str:
    """Read the pinned `datalab` git tag from this repo's pyproject.toml."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    src = data.get("tool", {}).get("uv", {}).get("sources", {}).get("datalab", {})
    return src.get("tag") or src.get("rev") or src.get("branch") or default


def check_catalog(catalog: str, allow_suffix: bool) -> tuple[bool, str]:
    """Validate a base catalog name. Returns (ok, error-message-if-not)."""
    catalog = catalog.strip()
    if not catalog:
        return False, "a catalog name is required"
    if not CATALOG_RE.match(catalog):
        return False, "use lowercase letters/digits/underscores, starting with a letter"
    if not allow_suffix and catalog.endswith(ENV_SUFFIXES):
        return False, (
            f"'{catalog}' looks like it includes an environment suffix — pass the BASE "
            "name only (the bundle appends _stage/_prod per target; see docs/NAMING.md). "
            "Re-run with --allow-env-suffix only if the base catalog truly ends this way."
        )
    return True, ""


def repo_slug(path: Path) -> str:
    """`<owner>/<repo>` from the git origin of `path` (empty if none).

    Only a real GitHub remote yields a slug. A LOCAL-path origin (a
    `git clone /some/dir` used for testing, or a repo with no GitHub remote
    yet) has no owner, and naively taking its last two path segments produced
    nonsense like `datalab/.` — which then landed in docs/CICD.md as the OIDC
    federation SUBJECT, the one string that must match exactly or every deploy
    fails TOKEN_SUBJECT_INVALID. Returning "" makes the caller fall back to the
    honest `<owner>/<repo>` placeholder.
    """
    try:
        url = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    url = url.removesuffix(".git")
    if url.startswith("git@") and ":" in url:  # git@github.com:owner/repo
        host, url = url[4:].split(":", 1)
        if "github" not in host:
            return ""
    elif "://" in url:
        scheme_less = url.split("://", 1)[1]
        host, _, url = scheme_less.partition("/")
        if "github" not in host:
            return ""
    else:
        return ""  # a bare local path — no owner to name
    parts = [p for p in url.split("/") if p and p != "."]
    return "/".join(parts[-2:]) if len(parts) >= 2 else ""


def drop_reference_material(out: Path) -> None:
    """In-place: delete the reference-only top-level entries from the clone.

    The adopter keeps the framework scaffold (scripts/, schemas/, .github/, the
    agent harness, docs/) but not the reference domains, design assets, dev-time
    pilot, or the multi-package lockfile (regenerated by `make lock`).
    """
    for rel in sorted(EXCLUDE_TOP):
        target = out / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


# NESTED paths that only make sense alongside the template's reference material
# (EXCLUDE_TOP covers top-level entries only). The two skill copies must BOTH go
# or `make check-skills` fails on .agents/.claude drift.
TEMPLATE_ONLY_PATHS = [
    "scripts/export_design.py",                # exports the deleted design/*.drawio
    ".agents/skills/maintain-design-diagram",  # skill for the deleted design/ package
    ".claude/skills/maintain-design-diagram",  # its generated Claude Code copy
    # THIS repo's restructure history ("this repo has been through two
    # restructures", legacy DLT -> SDP). A brand-new customer repo has no such
    # history, so it reads as a false statement about their own code.
    "docs/MIGRATION.md",
]


def remove_template_only_paths(out: Path) -> None:
    for rel in TEMPLATE_ONLY_PATHS:
        target = out / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


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
        "## Ruff lint over scripts/ and projects/",
        "## Ruff lint over scripts/ and src/",
        "Makefile",
    )
    text = require_replace(
        text,
        "# Domain config roots: a root-level config/ (adopter layout) and every\n"
        "# projects/<domain>/config/ — $(wildcard) drops whichever doesn't exist.\n"
        "CONFIG_DIRS := $(wildcard config) $(wildcard projects/*/config)",
        "# Domain config root (adopter layout: one root-level config/ directory).\n"
        "CONFIG_DIRS := config",
        "Makefile",
    )
    text = require_replace(
        text,
        "PIPELINE ?= customer_sales_etl",
        f"PIPELINE ?= {catalog}_etl",
        "Makefile",
    )
    text = text.replace("datalab.sales_landing_path=file://", "datalab.landing_path=file://")
    # The publish-wheel comment block names the template's SECOND domain wheel
    # variable, which does not exist here (one domain, one var.datalab_wheel).
    text = require_replace(
        text,
        "# UC Volume inside EACH project's own catalog (one upload per project catalog). CI\n"
        "# runs this in the deploy-dab action BEFORE `bundle deploy` (the version each domain\n"
        "# references via var.datalab_wheel / var.sales_datalab_wheel must be on its volume\n"
        "# first). Bump the git tag + var.datalab_version in lockstep when upgrading.",
        "# UC Volume inside this catalog. CI runs it in the deploy-dab action BEFORE\n"
        "# `bundle deploy` (the version var.datalab_wheel references must be on the volume\n"
        "# first). Bump the git tag + var.datalab_version in lockstep when upgrading.",
        "Makefile (publish-wheel comment)",
    )
    # Adopters have no design/ assets — drop the export target (its script and
    # the maintain-design-diagram skill are removed by remove_template_only_paths).
    text = require_replace(
        text, " validate-connect design \\", " validate-connect \\", "Makefile (.PHONY)"
    )
    text, n = re.subn(
        r"# ---- design assets.*?export_design\.py\n\n", "", text, count=1, flags=re.S
    )
    if not n:
        raise SystemExit("scaffold: could not strip the design target from the Makefile")
    path.write_text(text, encoding="utf-8")


def patch_bootstrap_uc(out: Path, catalog: str, ctx: dict[str, str]) -> None:
    """bootstrap_uc.py only carries the deploy SP now — the per-target catalogs
    and groups are RESOLVED from the bundle files through scripts/domains.py."""
    path = out / "scripts" / "bootstrap_uc.py"
    text = path.read_text(encoding="utf-8")
    text, n = re.subn(
        r'^DEPLOY_SP = ".*?"', f'DEPLOY_SP = "{ctx["@@DEPLOY_SP@@"]}"', text, count=1, flags=re.M
    )
    if not n:
        raise SystemExit("scaffold: could not patch scripts/bootstrap_uc.py DEPLOY_SP")
    path.write_text(text, encoding="utf-8")


def patch_domains(out: Path, catalog: str) -> None:
    """Rewrite the domain registry to the adopter's single root-level domain.

    Everything per-target (catalog names, groups) resolves from the rewritten
    variables/ + targets/ + rbac.yml, so this is the ONLY registry edit needed."""
    path = out / "scripts" / "domains.py"
    text = path.read_text(encoding="utf-8")
    # edge_volume names the landing/exports UC volume bootstrap creates — it must
    # equal the volume segment of var.landing_path (VARIABLES_MEDALLION writes
    # /Volumes/${var.catalog}/landing/<catalog>/events/), or the adopter's first
    # `make run` fails on a volume that was never provisioned.
    registry = (
        "DOMAINS: dict[str, dict] = {\n"
        f'    "{catalog}": {{"catalog_var": "catalog", "edge_volume": "{catalog}"}},\n'
        "}"
    )
    text, n = re.subn(
        r"^DOMAINS: dict\[str, dict\] = \{.*?^\}", registry, text, count=1, flags=re.M | re.S
    )
    if not n:
        raise SystemExit("scaffold: could not patch scripts/domains.py DOMAINS")
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


CI_TEMPLATE_ONLY_MARKER = (
    "  # --- template-only below: stripped from generated adopters by scaffold_adopter.py ---"
)


def patch_ci(out: Path) -> None:
    path = out / ".github" / "workflows" / "common-ci-steps.yml"
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text, "ruff check scripts projects", "ruff check scripts src", "common-ci-steps.yml"
    )
    for old, new in (
        (
            "        # Same paths as `make lint` — the framework moved to the datalab-framework\n"
            "        # repo; here we lint scripts/ + the reference domains under projects/.",
            "        # Same paths as `make lint`: the repo's scripts/ + the domain package.",
        ),
        (
            "        # the Makefile's CONFIG_DIRS (root config/ for adopters, projects/*/config here).\n"
            "        run: |\n"
            "          dirs=()\n"
            '          for d in config projects/*/config; do [ -d "$d" ] && dirs+=("$d"); done\n'
            '          uv run python -m datalab.framework "${dirs[@]}"',
            "        # the Makefile's CONFIG_DIRS (the root-level config/ directory).\n"
            "        run: uv run python -m datalab.framework config",
        ),
    ):
        text = require_replace(text, old, new, "common-ci-steps.yml")
    # Strip the template-only trailing jobs (the scaffold smoke test exercises
    # the TEMPLATE layout — its Makefile anchors don't exist in an adopter).
    if CI_TEMPLATE_ONLY_MARKER not in text:
        raise SystemExit("scaffold: template-only marker missing in common-ci-steps.yml")
    text = text.split(CI_TEMPLATE_ONLY_MARKER)[0].rstrip() + "\n"
    path.write_text(text, encoding="utf-8")


def patch_cd(out: Path, catalog: str) -> None:
    """Repoint the CD plumbing at the adopter's single domain.

    The template forwards sales-domain overrides (sales-catalog,
    sales_landing_path) that don't exist in an adopter's variables — the day
    someone set the matching Actions variable, `bundle deploy` would fail on an
    unknown --var. Drop them, rename the landing override to the adopter's
    `landing_path` variable, and point the wheel-publish override at the
    adopter's domain."""
    cd = out / ".github" / "workflows" / "common-cd-steps.yml"
    text = cd.read_text(encoding="utf-8")
    text = require_replace(
        text,
        "          sales-catalog:      ${{ vars.DATALAB_SALES_CATALOG || '' }}\n",
        "",
        "common-cd-steps.yml",
    )
    text = require_replace(
        text,
        "sales-landing-path: ${{ vars.DATALAB_SALES_LANDING_PATH || '' }}",
        "landing-path:       ${{ vars.DATALAB_LANDING_PATH || '' }}",
        "common-cd-steps.yml",
    )
    cd.write_text(text, encoding="utf-8")

    action = out / ".github" / "actions" / "deploy-dab" / "action.yml"
    text = action.read_text(encoding="utf-8")
    text = require_replace(
        text,
        """  sales-catalog:
    description: "Unity Catalog catalog override for the sales domain (overrides var.sales_catalog)."
    required: false
    default: ""
  sales-landing-path:
    description: "Override for the Auto Loader landing volume path."
    required: false
    default: ""
""",
        """  landing-path:
    description: "Override for the Auto Loader landing volume path."
    required: false
    default: ""
""",
        "deploy-dab/action.yml",
    )
    text = require_replace(
        text,
        '        [ -n "$IN_CATALOG" ]       && PUBLISH_ARGS+=(--catalog-for "customer_sales=$IN_CATALOG")\n'
        '        [ -n "$IN_SALES_CATALOG" ] && PUBLISH_ARGS+=(--catalog-for "sales=$IN_SALES_CATALOG")\n',
        f'        [ -n "$IN_CATALOG" ] && PUBLISH_ARGS+=(--catalog-for "{catalog}=$IN_CATALOG")\n',
        "deploy-dab/action.yml",
    )
    text = require_replace(
        text,
        "        IN_SALES_CATALOG:  ${{ inputs.sales-catalog }}\n"
        "        IN_LANDING_PATH:   ${{ inputs.sales-landing-path }}\n",
        "        IN_LANDING_PATH:   ${{ inputs.landing-path }}\n",
        "deploy-dab/action.yml",
    )
    text = require_replace(
        text,
        '        [ -n "$IN_SALES_CATALOG" ]  && ARGS+=(--var "sales_catalog=$IN_SALES_CATALOG")\n'
        '        [ -n "$IN_LANDING_PATH" ]   && ARGS+=(--var "sales_landing_path=$IN_LANDING_PATH")\n',
        '        [ -n "$IN_LANDING_PATH" ]   && ARGS+=(--var "landing_path=$IN_LANDING_PATH")\n',
        "deploy-dab/action.yml",
    )
    text = text.replace(
        "        IN_SALES_CATALOG: ${{ inputs.sales-catalog }}\n", ""
    )
    # The surviving `catalog` input + the comments around the publish/deploy
    # steps still advertised the template's two domains. No runtime effect, but
    # the input description is what a maintainer reads in the Actions UI — and
    # the "no template identity" done-check deliberately skips .github/, so this
    # is exactly the drift nobody would catch.
    text = require_replace(
        text,
        '    description: "Unity Catalog catalog override for the customer_sales '
        'domain (overrides var.catalog)."',
        f'    description: "Unity Catalog catalog override for the {catalog} '
        'domain (overrides var.catalog)."',
        "deploy-dab/action.yml",
    )
    for old, new in (
        (
            "references (var.datalab_wheel / var.sales_datalab_wheel) is present when a",
            "references (var.datalab_wheel) is present when a",
        ),
        (
            "publish_wheel uploads to the per-target domain catalogs (bootstrap_uc.CATALOGS)",
            "publish_wheel uploads to the per-target domain catalogs (scripts/domains.py)",
        ),
        (
            "# When a domain catalog is overridden below (--var catalog / sales_catalog),",
            "# When the domain catalog is overridden below (--var catalog),",
        ),
        (
            "# it (var.datalab_wheel / var.sales_datalab_wheel derive from the same vars).",
            "# it (var.datalab_wheel derives from the same var).",
        ),
    ):
        text = text.replace(old, new)
    action.write_text(text, encoding="utf-8")


def patch_cicd_docs(out: Path, ctx: dict[str, str], slug: str) -> None:
    """Repoint docs/CICD.md at the adopter's identity.

    Left untouched, a generated repo's own CI/CD doc still carries the
    TEMPLATE's OIDC federation subject, deploy SP and workspace host — a
    first-timer copying the federation-policy command from their own docs would
    wire OIDC to the template's service principal."""
    path = out / "docs" / "CICD.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text, "repo:dediggibyte/datalab:environment:", f"repo:{slug}:environment:", "docs/CICD.md"
    )
    text = text.replace(TEMPLATE_DEPLOY_SP, ctx["@@DEPLOY_SP@@"])
    text = text.replace(TEMPLATE_HOST, ctx["@@HOST@@"])
    # docs/MIGRATION.md is template history and is deleted from adopters, so its
    # nav link would 404 in the generated repo.
    text = require_replace(
        text,
        "[← README](../README.md) · [Architecture](ARCHITECTURE.md) · "
        "[Framework](FRAMEWORK.md) · **CI/CD** · [Migration](MIGRATION.md)",
        "[← README](../README.md) · [Architecture](ARCHITECTURE.md) · "
        "[Framework](FRAMEWORK.md) · **CI/CD**",
        "docs/CICD.md",
    )
    # Template-workspace identity that used to survive into adopters: the shared-SP
    # sentence, the SP's display name, and the sales-domain landing-path variable
    # (patch_cd already renamed the workflow input to DATALAB_LANDING_PATH).
    text = require_replace(
        text,
        "This repo deliberately reuses the **same workspace + OIDC service principal**\n"
        "as the `klarna-access-agent` and `databricks_dqx_agent` repos:",
        "This repo's CI/CD deploy identity:",
        "docs/CICD.md",
    )
    text = require_replace(
        text, "\n  (`access-management-sp-rulebook`)", "", "docs/CICD.md"
    )
    text = require_replace(
        text,
        "   - optional variables: `DATALAB_CATALOG`, `DATALAB_SALES_CATALOG`,\n"
        "     `DATALAB_SALES_LANDING_PATH` (the medallion vars from `variables/`),",
        "   - optional variables: `DATALAB_CATALOG`, `DATALAB_LANDING_PATH`\n"
        "     (the medallion vars from `variables/`),",
        "docs/CICD.md",
    )
    text = text.replace("DATALAB_SALES_LANDING_PATH", "DATALAB_LANDING_PATH")
    path.write_text(text, encoding="utf-8")


# --- docs/, harness + CI surfaces that also carry template identity ----------
# patch_cicd_docs used to be the ONLY doc rewrite, which left an adopter reading
# their OWN docs pointed at the template's workspace, deleted folders and
# second-domain variables. Everything below closes that gap; `make
# check-adopter-docs` (run on the generated repo in CI) fails if any of it
# regresses.

# Template-only regions in docs/, swapped exactly like AGENTS.md's. Markers must
# sit OUTSIDE fenced code blocks — a comment inside ```mermaid breaks rendering.
DOC_REGIONS: dict[str, dict[str, str]] = {
    "docs/ARCHITECTURE.md": {
        # docs/MIGRATION.md is template history and is deleted from adopters.
        "arch-nav": (
            "[← README](../README.md) · **Architecture** · "
            "[Framework](FRAMEWORK.md) · [CI/CD](CICD.md)\n"
        ),
        "arch-design-banner": "",       # no design/ package in an adopter
        "arch-design-section": "",      # ...and no `make design` to document
        "arch-code-diagram": """\
```mermaid
flowchart TD
    FW["datalab framework — EXTERNAL dependency<br/>(dediggibyte/datalab-framework: git dep + UC-Volume wheel)<br/>models · adapters · generator · devtools · param helpers"]
    subgraph REPO["this repo — the @@CATALOG@@ domain + deploy bundle"]
        subgraph DOMAIN["repo root — the domain"]
            CFG["config/@@CATALOG@@/<br/>domain.yml + &lt;layer&gt;/&lt;table&gt;.yml"]
            DOM["src/@@CATALOG@@_etl/<br/>pure @transform fns · custom dqx checks ·<br/>3-line pipeline entrypoint"]
            JOBS["src/jobs/ + notebooks/<br/>edge lanes"]
            RES["resources/<br/>the domain's bundle resources"]
            DTESTS["tests/<br/>the domain's own tests"]
        end
    end
    CFG -->|consumed by| FW
    DOM -->|registered into| FW
    DTESTS -->|exercise| FW
```
""",
        "arch-layer-rule": """\
2. **The repo root** — this adopter's single domain: the YAML artifacts
   (`config/@@CATALOG@@/`), the domain package (`src/@@CATALOG@@_etl/`), the
   edge-lane entry points (`src/jobs/@@CATALOG@@/`, `notebooks/@@CATALOG@@/`),
   the bundle `resources/`, and `tests/`. The datalab template repo carries the
   same shape nested under `projects/<domain>/`, one folder per reference domain.
""",
    },
    "docs/ADOPTING.md": {
        "adopting-repo-row": (
            "| this repo | the **domain + deploy bundle** that CONSUMES the framework "
            "— `databricks.yml` + your domain at the repo root | add/change tables, "
            "jobs, notebooks; deploy |\n"
        ),
        "adopting-no-src": (
            "This repo has **no `src/datalab`** — the framework is a dependency,\n"
            "consumed two ways (below). Your domain lives at the repo **root**\n"
            "(`config/@@CATALOG@@/`, `src/@@CATALOG@@_etl/`, `resources/`).\n"
        ),
        "adopting-wheel-path": (
            "`var.datalab_wheel` derives the full path from `var.catalog` +\n"
            "`var.datalab_version`, so you never hand-write the wheel path.\n"
            "**Upgrading the framework = bump the git tag AND `datalab_version`, then\n"
            '`make lock` + `make publish-wheel`** (see "Upgrading the framework later").\n'
        ),
        # "Adopters: this section is not for you" — so don't ship it to them.
        "adopting-second-domain": (
            "## Adding a second domain\n"
            "\n"
            "This repo is deliberately SINGLE-domain: the root-level layout\n"
            "(`config/@@CATALOG@@/`, `src/@@CATALOG@@_etl/`, `resources/`) has exactly\n"
            "one domain in it, and `pyproject.toml` is one package with no uv\n"
            "workspace. For another domain or customer, stand up a separate adopter\n"
            "repo ([NEW_ADOPTER.md](NEW_ADOPTER.md)) rather than grafting a second one\n"
            "on here.\n"
            "\n"
        ),
    },
    "docs/NAMING.md": {
        "naming-diagram": """\
```mermaid
flowchart LR
  subgraph repo ["Repo layout (the repo root IS the domain)"]
    A["&lt;repo root&gt;"]
    B["config/@@CATALOG@@/silver/customers.yml"]
    C["src/@@CATALOG@@_etl/"]
    D["src/jobs/@@CATALOG@@/ + notebooks/@@CATALOG@@/"]
    E["resources/@@CATALOG@@_*.yml"]
  end
  subgraph uc ["Unity Catalog + workspace"]
    F["catalog @@CATALOG@@ (dev)<br/>@@CATALOG@@_stage / @@CATALOG@@_prod"]
    G["table @@CATALOG@@.silver.customers"]
    H["pipeline @@CATALOG@@_etl (workspace object)"]
    I["jobs @@CATALOG@@_export, @@CATALOG@@_quarantine_report, ... (workspace objects)"]
  end
  A --> F
  B --> G
  C --> H
  D --> I
  E --> H
  E --> I
```
""",
        "naming-domain-folder": """\
The domain folder is the repo ROOT here, and the repo is named after the
**base catalog** that holds the domain's medallion schemas — `@@CATALOG@@`.
(The datalab template repo nests each reference domain under
`projects/<catalog>/` instead; the contract is identical.)
""",
        "naming-resource-table": """\
| File | Resource key / name | Kind |
|---|---|---|
| `@@CATALOG@@_etl.pipeline.yml` | `@@CATALOG@@_etl` | SDP pipeline |
| `@@CATALOG@@_etl.job.yml` | `@@CATALOG@@_etl_refresh` | scheduled `pipeline_task` |
| `@@CATALOG@@_export.job.yml` | `@@CATALOG@@_export` | python-file lane (when you add one) |
| `@@CATALOG@@_quarantine_report.job.yml` | `@@CATALOG@@_quarantine_report` | notebook lane (when you add one) |

The pipeline is `<catalog>_etl`; edge jobs are `<catalog>_<purpose>`.
""",
        "naming-out-of-scope": """\
These are fixed by the framework or by Unity Catalog, not by this page:

- The `landing`/`exports` UC volumes (`landing.@@CATALOG@@`,
  `exports.@@CATALOG@@`) — UC objects can't be renamed in place; they are
  out-of-band governance state created by `scripts/bootstrap_uc.py`, and the
  name must match `scripts/domains.py`'s `edge_volume` and the volume segment
  of `var.landing_path`.
- `domain.yml`'s file name and the `layers:`/`domain:` model fields — that is
  the framework contract (defined in the `datalab-framework` repo's models),
  shared by every adopter; this page only constrains the *values* (e.g.
  `domain: @@CATALOG@@`).
""",
    },
}


def patch_doc_regions(out: Path, subst) -> None:
    """Swap every `<!-- template-only:… -->` region in docs/ for adopter text."""
    for rel, regions in DOC_REGIONS.items():
        path = out / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for name, replacement in regions.items():
            text = _replace_template_region(text, name, subst(replacement), rel)
        path.write_text(text, encoding="utf-8")


def patch_agent_mcp(out: Path, ctx: dict[str, str]) -> None:
    """Repoint docs/AGENT_MCP.md at the adopter's workspace.

    patch_mcp rewrites the two JSON files; this doc carries the SAME identity in
    copy-pasteable `databricks auth login` / `databricks warehouses get`
    commands and in its value table. Left alone it tells a new adopter to log
    into the TEMPLATE's workspace — while its own "Adopter setup" section claims
    everything has already been rewritten for them."""
    path = out / "docs" / "AGENT_MCP.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = require_replace(text, TEMPLATE_MCP_PROFILE, ctx["@@MCP_PROFILE@@"], "docs/AGENT_MCP.md")
    text = require_replace(
        text, TEMPLATE_WAREHOUSE_ID, ctx["@@WAREHOUSE_ID@@"], "docs/AGENT_MCP.md"
    )
    text = text.replace(TEMPLATE_HOST, ctx["@@HOST@@"])
    path.write_text(text, encoding="utf-8")


CODEOWNERS_ADOPTER = """\
# Code owners — review routing for pull requests.
#
# Intentionally empty: the datalab template routed reviews at its own approvers
# team, which does not exist in this org. A CODEOWNERS file naming a team GitHub
# cannot resolve is INVALID, and GitHub then silently
# never applies the "Require review from Code Owners" branch protection — the
# rule looks enabled and enforces nothing.
#
# To enable it here: create a team with write access, uncomment the line below
# with that team (or a user), then turn on "Require review from Code Owners"
# in the branch protection rule for `main`.
#
# *   @<your-org>/<your-review-team>
"""


def patch_codeowners(out: Path) -> None:
    path = out / ".github" / "CODEOWNERS"
    if path.exists():
        path.write_text(CODEOWNERS_ADOPTER, encoding="utf-8")


DEPENDABOT_CROSS_ORG_NOTE = """\
  - package-ecosystem: uv
    directory: /
    # CROSS-ORG ADOPTERS READ THIS FIRST. Resolving uv.lock touches EVERY git
    # dependency, including the PRIVATE dediggibyte/datalab-framework — so
    # without read access the updater fails `git_dependencies_not_reachable` on
    # every PR, even a bump of an unrelated package. Two working setups:
    #   * same org as the framework → grant Dependabot access to it (org
    #     Settings → Code security → Dependabot → private repository access);
    #   * different org → add a `registries:` entry of `type: git` backed by a
    #     PAT stored in THIS repo's *Dependabot* secret store (a separate store
    #     from Actions), or drop this ecosystem block entirely.
    # docs/CICD.md "Private framework dependency".
"""


def patch_dependabot(out: Path) -> None:
    """Leave the cross-org framework-access trap where the reader will hit it.

    An adopter in another org gets a permanently red `uv` ecosystem until they
    wire a git credential. That is documented in docs/CICD.md, but nobody reads
    CICD.md because of a dependabot failure — they open dependabot.yml."""
    path = out / ".github" / "dependabot.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text,
        "  - package-ecosystem: uv\n    directory: /\n",
        DEPENDABOT_CROSS_ORG_NOTE,
        ".github/dependabot.yml",
    )
    path.write_text(text, encoding="utf-8")


def patch_workflow_comments(out: Path) -> None:
    """Drop header comments naming workflows that no longer exist (there is one
    ci-cd.yml now, not ci-cd-{dev,stage,prod}.yml)."""
    for rel in ("common-ci-steps.yml", "common-cd-steps.yml"):
        path = out / ".github" / "workflows" / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "# Reusable workflow. Called by ci-cd-{dev,stage,prod}.yml.",
            "# Reusable workflow. Called by ci-cd.yml (one workflow; the target is\n"
            "# derived from the trigger).",
        )
        path.write_text(text, encoding="utf-8")


def patch_cursor_rules(out: Path, catalog: str) -> None:
    """.cursor/rules/project.mdc is auto-attached context for every Cursor edit,
    so it must describe the adopter's root-level layout, not projects/."""
    path = out / ".cursor" / "rules" / "project.mdc"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for old, new in (
        (
            "  (`config/<catalog>/<schema>/<table>.yml`; in this repo the example lives at\n"
            "  `projects/customer_sales/config/customer_sales/`) — author it with the",
            f"  (`config/<catalog>/<schema>/<table>.yml`; here `config/{catalog}/`)"
            " — author it with the",
        ),
        (
            "  domain package (`src/<catalog>_etl/transforms/`, in this repo under\n"
            "  `projects/customer_sales/`) as pure, unit-tested `@transform` functions.",
            f"  domain package (here `src/{catalog}_etl/transforms/`) as pure,\n"
            "  unit-tested `@transform` functions.",
        ),
        (
            "  `projects/*/resources/*.yml` (adopters: `resources/*.yml`), targets `dev`",
            "  `resources/*.yml`, targets `dev`",
        ),
    ):
        text = require_replace(text, old, new, ".cursor/rules/project.mdc")
    path.write_text(text, encoding="utf-8")


# Each entry is (skill-relative path, [(old, new), ...]) applied to BOTH the
# canonical .agents/skills copy and the generated .claude/skills mirror — patch
# one and `make check-skills` fails on drift.
SKILL_EDITS: dict[str, list[tuple[str, str]]] = {
    "deploy-databricks-bundle/SKILL.md": [
        (
            "per-domain resource files — in this repo `projects/*/resources/*.yml`",
            "per-domain resource files — in this repo `resources/*.yml`",
        ),
        (
            "  `sales_landing_path`, permission lists) and per-target values. Resources",
            "  `landing_path`, permission lists) and per-target values. Resources",
        ),
        (
            "   `DATALAB_CATALOG`, `DATALAB_SALES_LANDING_PATH`).",
            "   `DATALAB_CATALOG`, `DATALAB_LANDING_PATH`).",
        ),
        (
            "| Auto Loader path errors on first run | The landing volume "
            "(`${var.sales_landing_path}`) doesn't exist",
            "| Auto Loader path errors on first run | The landing volume "
            "(`${var.landing_path}`) doesn't exist",
        ),
    ],
    "author-ldp-artifact/SKILL.md": [
        (
            "live under `projects/<catalog>/config/`\n"
            "(e.g. `projects/customer_sales/config/customer_sales/silver/customers.yml`);",
            "live under `config/<catalog>/`\n"
            "(e.g. `config/@@CATALOG@@/silver/customers.yml`);",
        ),
        (
            "Live example: `projects/sales/config/sales/gold/sales_by_category.yml`.",
            "Live example: the datalab template repo's "
            "`projects/sales/config/sales/gold/sales_by_category.yml`.",
        ),
        (
            "`projects/customer_sales/` shape; naming contract: `docs/NAMING.md`).",
            "the datalab template repo's `projects/customer_sales/` shape; naming "
            "contract: `docs/NAMING.md`).",
        ),
    ],
}


def patch_skills(out: Path, subst) -> None:
    for rel, edits in SKILL_EDITS.items():
        for root in (".agents/skills", ".claude/skills"):
            path = out / root / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for old, new in edits:
                text = require_replace(text, subst(old), subst(new), f"{root}/{rel}")
            path.write_text(text, encoding="utf-8")


# --- AGENTS.md adopter conversion -------------------------------------------
# AGENTS.md is the document of record and CLAUDE.md auto-loads it, so a generated
# adopter must not ship it describing the template's projects/ + design/ +
# omnigent/ layout (none of which exist there — day one, the agent's ground truth
# would be wrong). Template-only regions in the canonical AGENTS.md are fenced
# with `<!-- template-only:<name> start/end -->` markers; the scaffold swaps each
# region for its adopter text, rewrites the remaining example paths to name the
# template repo explicitly, and then ASSERTS no dead reference survived — an
# unmarked new template-only reference fails the scaffold (and the CI scaffold
# smoke test) instead of silently shipping.

ADOPTER_REPO_INTRO = """\
> **Framework consumption.** The reusable framework lives in its OWN repo,
> **[dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework)** —
> there is no framework source in this repo. THIS repo is a single-domain
> **adopter** (domain + deploy bundle) that CONSUMES `datalab` two ways: a
> **git dependency** for local dev/CI (pinned in `pyproject.toml`
> `[tool.uv.sources]` to a release tag) and a versioned **UC-Volume wheel** for
> serverless (`var.datalab_wheel`) that this repo **builds from the pinned git
> dep and publishes on every deploy** (`make publish-wheel` / the `deploy-dab`
> action). Keep the git tag and `var.datalab_version` in lockstep. The framework
> **reference** (artifact anatomy, target kinds, dqx, the SDP capability matrix)
> lives in that repo's
> [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md);
> first-deploy checklist: [`docs/NEW_ADOPTER.md`](docs/NEW_ADOPTER.md).
"""

ADOPTER_OVERVIEW_DOMAINS = """\
- **Single-domain adopter layout**: the domain lives at the repo ROOT —
  `config/@@CATALOG@@/` (one YAML artifact per table), `src/@@CATALOG@@_etl/`
  (the domain package), `resources/*.yml` (bundle resources). Complete worked
  examples of every framework feature (edge jobs, notebooks, AUTO CDC
  SCD1/SCD2, snapshot CDC, config templates, ABAC SQL) live in the datalab
  template repo under `projects/`.
"""

ADOPTER_ARCHITECTURE = """\
```
Developer ──push/PR──▶ GitHub Actions ──OIDC──▶ Declarative Automation Bundle
                       ci-cd.yml (ONE workflow;   (databricks.yml + resources/*.yml)
                       target derived from the             │ deploys
                       trigger) → common-ci / common-cd    ▼
                       + framework-bump.yml (bot) + dependabot
                  ┌──────── Lakeflow SDP pipeline: @@CATALOG@@_etl ─────────┐
landing volume ─▶ │ bronze.events_raw ─▶ silver / gold: add tables with the │
(Auto Loader)     │ author-ldp-artifact skill (dqx quarantine per table)    │
                  └─────────────────────────────────────────────────────────┘
                  refreshed daily by job @@CATALOG@@_etl_refresh (paused in dev)
```
"""

ADOPTER_CODEBASE_LAYOUT = """\
```
databricks.yml            Bundle: name + include only (variables/ + targets/ + rbac + resources merged in)
variables/                Variable declarations + defaults (medallion catalog/schemas/paths)
targets/                  One file per environment (dev/stage/prod): mode, host, per-env variable values
rbac.yml                  Workspace-resource RBAC: groups + permission levels + per-target overrides
config/@@CATALOG@@/       domain.yml + ONE <schema>/<table>.yml artifact per target table
src/@@CATALOG@@_etl/      Domain package: pipeline entrypoint, @transform fns, custom dqx checks
resources/                This domain's bundle resources (pipeline + refresh job)
tests/                    The domain's unit tests (make test)
sample_data/              Local sample landing files for `make run-local`
scripts/                  bootstrap_uc · publish_wheel · domain registry · repo-integrity checks
schemas/                  GENERATED editor schemas from the pinned framework (make sync-schemas)
docs/                     NEW_ADOPTER (first-deploy checklist) · ADOPTING · GETTING_STARTED ·
                          NAMING · CICD · ARCHITECTURE · AGENT_MCP
.github/                  CI/CD workflows (OIDC deploy; framework App token) + dependabot
.agents/ .claude/ .cursor/ .codex/  Agent harness — skills authored ONCE in .agents/skills
                          (make sync-skills regenerates the .claude copy)
.githooks/                Human pre-commit guard (make enable-githooks)
.mcp.json                 Opt-in read-only Databricks MCP grounding (docs/AGENT_MCP.md)
Makefile                  Developer + CI entrypoints (run `make help`)
pyproject.toml, uv.lock   Single-package project (uv end to end; CI runs --frozen)
```

The folder ↔ UC namespace naming contract is `docs/NAMING.md`. The multi-domain
reference layout lives in the datalab template repo (`projects/`).
"""

ADOPTER_MAINTENANCE_DESIGN = """\
2. If the architecture moved, update `docs/ARCHITECTURE.md` in the same PR.
"""

ADOPTER_COMMON_TASK_NEW_DOMAIN = """\
- **Add a second domain**: an adopter repo is deliberately SINGLE-domain
  (root-level layout). For another domain or customer, stand up a separate
  adopter repo (`docs/NEW_ADOPTER.md`); if you truly need several domains in
  one repo, follow the multi-domain layout of the datalab
  template repo (`projects/` + uv-workspace members) rather than grafting on.
"""


def _replace_template_region(text: str, name: str, replacement: str, where: str) -> str:
    """Swap one `<!-- template-only:<name> start/end -->` region (markers
    included) for `replacement`, failing loudly if the region is missing."""
    pattern = re.compile(
        rf"<!-- template-only:{name} start[^>]*-->\n.*?<!-- template-only:{name} end -->\n",
        re.S,
    )
    text, n = pattern.subn(replacement.replace("\\", "\\\\"), text, count=1)
    if not n:
        raise SystemExit(f"scaffold: template-only region {name!r} not found in {where}")
    return text


def patch_agents_md(out: Path, catalog: str, subst) -> None:
    path = out / "AGENTS.md"
    text = path.read_text(encoding="utf-8")

    for name, replacement in (
        ("repo-intro", ADOPTER_REPO_INTRO),
        ("overview-domains", ADOPTER_OVERVIEW_DOMAINS),
        ("architecture", ADOPTER_ARCHITECTURE),
        ("codebase-layout", ADOPTER_CODEBASE_LAYOUT),
        ("maintenance-design", ADOPTER_MAINTENANCE_DESIGN),
        ("common-task-new-domain", ADOPTER_COMMON_TASK_NEW_DOMAIN),
        ("common-task-design", ""),
        ("agents-conversion-gotcha", ""),
        # Template-maintenance knowledge about the conversion itself. An adopter
        # never runs the scaffold, and the passage necessarily names the
        # projects/ + design/ material this repo just deleted.
        ("adopter-surface-knowledge", ""),
    ):
        text = _replace_template_region(text, name, subst(replacement), "AGENTS.md")

    # Scattered single-site rewrites. Example FILES that only exist in the
    # template are re-pointed at it by name; repo-shape references become the
    # adopter's own paths. Each anchor is require_replace'd so template-side
    # edits to these passages fail the scaffold loudly instead of drifting.
    for old, new in (
        (
            "`databricks.yml` + `projects/*/resources/*.yml` (adopters:\n"
            "  root-level `resources/*.yml`),",
            "`databricks.yml` + root-level `resources/*.yml`,",
        ),
        (
            "make lint             # ruff check scripts and projects",
            "make lint             # ruff check scripts and src",
        ),
        (
            "make run              # databricks bundle run customer_sales_etl -t dev (dev refresh)",
            f"make run              # databricks bundle run {catalog}_etl -t dev (dev refresh)",
        ),
        (
            "make design           # re-export design/*.drawio diagrams to design/images/*.png (needs draw.io Desktop)\n",
            "",
        ),
        (
            "`projects/customer_sales/src/jobs/customer_sales/export_customer_summary.py`",
            "the template repo's `projects/customer_sales/src/jobs/customer_sales/export_customer_summary.py`",
        ),
        (
            "`projects/customer_sales/notebooks/customer_sales/quarantine_report.py`",
            "the template repo's `projects/customer_sales/notebooks/customer_sales/quarantine_report.py`",
        ),
        (
            "`projects/sales/config/sales/silver/orders.yml`",
            "the template repo's `projects/sales/config/sales/silver/orders.yml`",
        ),
        (
            "(`projects/customer_sales/resources/customer_sales_*.job.yml`)",
            "(the template repo's `projects/customer_sales/resources/customer_sales_*.job.yml`)",
        ),
        (
            "`projects/customer_sales/resources/customer_sales_export.job.yml`",
            "the template repo's `projects/customer_sales/resources/customer_sales_export.job.yml`",
        ),
        ("`projects/customer_sales/sql/abac/`", "`sql/abac/`"),
        (
            "`projects/customer_sales/config/customer_sales/...`",
            f"`config/{catalog}/...`",
        ),
        ("(same rule as omnigent)", "(never a locked dependency)"),
        (
            r"`^(resources\|projects/[^/]+/resources)/.*\.yml$`",
            r"`^resources/.*\.yml$`",
        ),
        (
            r"`^(config\|projects/[^/]+/config)/.*\.ya?ml$`",
            r"`^config/.*\.ya?ml$`",
        ),
        # docs/MIGRATION.md is template history; the scaffold deletes it, so the
        # protected-surface table must stop naming it (the table is the thing
        # people edit that surface FROM).
        (
            r"`^docs/(ARCHITECTURE\|CICD\|MIGRATION\|GETTING_STARTED\|NAMING"
            r"\|NEW_ADOPTER\|ADOPTING\|AGENT_MCP)\.md$`",
            r"`^docs/(ARCHITECTURE\|CICD\|GETTING_STARTED\|NAMING"
            r"\|NEW_ADOPTER\|ADOPTING\|AGENT_MCP)\.md$`",
        ),
        # Second-domain (sales) wheel plumbing: an adopter has ONE domain, so
        # var.sales_datalab_wheel does not exist and the domain wheel sits one
        # directory up, not three.
        (
            "- Serverless `environments:` block installs the framework wheel from THIS\n"
            "  domain's catalog artifacts.wheels Volume (`${var.datalab_wheel}` /\n"
            "  `${var.sales_datalab_wheel}`) plus this domain's wheel\n"
            "  (`../../../dist/<catalog>_etl-*.whl`)",
            "- Serverless `environments:` block installs the framework wheel from THIS\n"
            "  domain's catalog artifacts.wheels Volume (`${var.datalab_wheel}`) plus\n"
            "  this domain's wheel (`../dist/<catalog>_etl-*.whl`)",
        ),
        (
            "  framework wheel from THIS domain's catalog — `${var.datalab_wheel}`\n"
            "  (customer_sales: `/Volumes/${var.catalog}/artifacts/wheels/...`) or\n"
            "  `${var.sales_datalab_wheel}` (sales: `/Volumes/${var.sales_catalog}/...`) — and\n"
            "  `../../../dist/<catalog>_etl-*.whl` (this domain's own wheel, built by the\n"
            "  bundle's `artifacts:` — `uv build --package <catalog>_etl`, relative to the\n"
            "  resource file).",
            "  framework wheel from THIS domain's catalog — `${var.datalab_wheel}`\n"
            "  (`/Volumes/${var.catalog}/artifacts/wheels/...`) — and\n"
            "  `../dist/<catalog>_etl-*.whl` (this domain's own wheel, built by the\n"
            "  bundle's `artifacts:` — `uv build --wheel`, relative to the\n"
            "  resource file).",
        ),
        (
            "  (`customer_sales.artifacts.wheels`, `sales.artifacts.wheels` — one upload per\n"
            "  project catalog, NOT a separate shared catalog)",
            "  (`<catalog>.artifacts.wheels` — the wheel rides in the domain's own catalog,\n"
            "  NOT a separate shared catalog)",
        ),
    ):
        text = require_replace(text, old, new, "AGENTS.md")

    # The MCP grounding profile: patch_mcp rewires the JSON, so AGENTS.md must
    # not keep telling the agent to authenticate as the template's profile.
    text = text.replace(TEMPLATE_MCP_PROFILE, subst("@@MCP_PROFILE@@"))

    # Drift guard: nothing may still point at material the scaffold removed,
    # unless the line explicitly attributes it to the template repo.
    offenders = [
        f"  {i}: {line.strip()}"
        for i, line in enumerate(text.splitlines(), 1)
        if re.search(r"projects/|design/|omnigent|make design", line)
        and "template repo" not in line
    ]
    if offenders:
        raise SystemExit(
            "scaffold: AGENTS.md still references template-only material after the "
            "conversion — fence the passage with <!-- template-only:<name> start/end --> "
            "markers (and handle it in patch_agents_md) or rewrite it:\n"
            + "\n".join(offenders)
        )
    path.write_text(text, encoding="utf-8")


def patch_databricksignore(out: Path) -> None:
    """Drop entries whose paths don't exist in the adopter layout (the reference
    domains, design assets, dev-time pilot) so the list stays ALIGNED with the
    rewritten databricks.yml sync.exclude — `make check-sync-lists` enforces it."""
    path = out / ".databricksignore"
    if not path.exists():
        return
    dropped = ("projects/", "design/", "omnigent/")
    kept = [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if not any(gone in ln for gone in dropped)
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def patch_mcp(out: Path, ctx: dict[str, str]) -> None:
    """Repoint the read-only Databricks MCP grounding config at the adopter.

    Both `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) ship with the
    template's CLI profile + dev SQL warehouse baked in; left untouched, an
    adopter's agents would query the TEMPLATE's workspace. Swap in the adopter's
    profile + warehouse id. The MCP is opt-in/dev-time, so a placeholder
    warehouse id is fine — `.mcp.json` keeps its `${VAR:-default}` env override,
    and the literal doubles as a visible TODO in `.cursor/mcp.json`.
    """
    profile, warehouse = ctx["@@MCP_PROFILE@@"], ctx["@@WAREHOUSE_ID@@"]
    # `.mcp.json` is the canonical file — fail loudly if its template literals
    # drift; `.cursor/mcp.json` mirrors it best-effort.
    mcp = out / ".mcp.json"
    if mcp.exists():
        text = require_replace(mcp.read_text(encoding="utf-8"), TEMPLATE_MCP_PROFILE, profile, ".mcp.json")
        text = require_replace(text, TEMPLATE_WAREHOUSE_ID, warehouse, ".mcp.json")
        mcp.write_text(text, encoding="utf-8")
    cursor = out / ".cursor" / "mcp.json"
    if cursor.exists():
        text = cursor.read_text(encoding="utf-8")
        text = text.replace(TEMPLATE_MCP_PROFILE, profile).replace(TEMPLATE_WAREHOUSE_ID, warehouse)
        cursor.write_text(text, encoding="utf-8")


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
        f"sample_data/landing/{cat}/events/events.json": SAMPLE_EVENTS_JSON,
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
# Interactive prompting (the user CONFIRMS every workspace-specific value)
# --------------------------------------------------------------------------- #

def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        resp = input(f"  {label}{suffix}: ").strip()
    except EOFError:
        resp = ""
    return resp or default


def confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def gather_interactive(args, default_tag: str) -> dict[str, str]:
    """Prompt ONLY for the two irreducible values — catalog and host — and skip
    even those when they were passed as flags. Everything else (warehouse id,
    MCP profile, groups, deploy SP, framework tag) silently takes its flag value
    or a derived default: a first-timer answers two questions, reviews one
    summary, and the placeholders they left are printed as fill-before-deploy
    TODOs at the end instead of blocking the conversion."""
    print("\nConfigure this datalab adopter repo — two questions; everything else defaults.")
    print("(Override any default later by re-running with flags, or fix the files directly.)\n")
    catalog = args.catalog.strip()
    while True:
        if not catalog:
            catalog = _prompt("Base catalog / domain (lowercase, no _dev/_stage/_prod)")
        ok, msg = check_catalog(catalog, args.allow_env_suffix)
        if ok:
            break
        print(f"    ! {msg}\n")
        catalog = ""
    host = args.host
    if host == HOST_PLACEHOLDER:
        host = _prompt("Databricks workspace host (https://…; Enter to fill in later)", host)
    resolved = {
        "catalog": catalog,
        "host": host,
        "warehouse_id": args.warehouse_id,
        "mcp_profile": args.mcp_profile or f"{catalog}_dev",
        "reader_group": args.reader_group or f"{catalog}_readers",
        "engineer_group": args.engineer_group or f"{catalog}_engineers",
        "admin_group": args.admin_group or f"{catalog}_admins",
        "deploy_sp": args.deploy_sp,
        "framework_tag": args.framework_tag or default_tag,
    }
    print("\n  Summary (defaults are fine; <placeholders> become TODOs to fill before deploy):")
    for key, value in resolved.items():
        print(f"    {key:14} {value}")
    if not confirm("\nApply this configuration?"):
        raise SystemExit(
            "scaffold: aborted at confirmation. To change a defaulted value, re-run with "
            "its flag, e.g. make configure-adopter CATALOG=acme WAREHOUSE_ID=<id> DEPLOY_SP=<app-id>"
        )
    return resolved


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--catalog", default="", help="base catalog / domain name (lowercase, no env suffix)")
    parser.add_argument("--out", default="", help="output dir for a fresh sibling repo (omit with --in-place)")
    parser.add_argument("--in-place", action="store_true", help="convert THIS repo (a template clone) in place")
    parser.add_argument("--interactive", action="store_true", help="prompt for catalog + host (skipped when passed as flags) and confirm a summary; everything else defaults")
    parser.add_argument("--host", default=HOST_PLACEHOLDER, help="Databricks workspace URL")
    parser.add_argument("--warehouse-id", default="<sql-warehouse-id>", help="SQL warehouse id for the MCP grounding config")
    parser.add_argument("--mcp-profile", default="", help="Databricks CLI profile for MCP auth (default: <catalog>_dev)")
    parser.add_argument("--deploy-sp", default="<deploy-sp-app-id>", help="CI/CD deploy SP application id")
    parser.add_argument("--reader-group", default="", help="reader group (default: <catalog>_readers)")
    parser.add_argument("--engineer-group", default="", help="engineer group (default: <catalog>_engineers)")
    parser.add_argument("--admin-group", default="", help="admin group (default: <catalog>_admins)")
    parser.add_argument("--framework-tag", default="", help="datalab framework tag (default: this repo's pin)")
    parser.add_argument("--allow-env-suffix", action="store_true", help="permit a catalog ending in _dev/_stage/_prod")
    parser.add_argument("--force", action="store_true", help="overwrite a non-empty --out; or bypass the in-place template guard")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the in-place destructive confirmation (agent/CI)")
    args = parser.parse_args(argv)

    if args.in_place and args.out:
        parser.error("--in-place and --out are mutually exclusive")
    if not args.in_place and not args.out:
        parser.error("pass --out <dir> for a fresh sibling repo, or --in-place to convert this clone")

    # Resolve the target dir + guard early, before any prompting.
    if args.in_place:
        out = REPO_ROOT
        slug = repo_slug(out)
        if slug == TEMPLATE_SLUG and not args.force:
            parser.error(
                f"refusing to convert the template repo in place (origin {slug}). Run this inside "
                "a repo generated from the template, or pass --force."
            )
    else:
        out = Path(args.out).expanduser().resolve()
        if out == REPO_ROOT:
            parser.error("--out must not be this repo (use --in-place to convert it)")

    default_tag = args.framework_tag or framework_tag()
    if args.interactive:
        if not sys.stdin.isatty():
            parser.error("--interactive needs a terminal; pass values as flags for non-interactive use")
        r = gather_interactive(args, default_tag)
    else:
        ok, msg = check_catalog(args.catalog, args.allow_env_suffix)
        if not ok:
            parser.error(f"--catalog: {msg}")
        cat = args.catalog.strip()
        r = {
            "catalog": cat,
            "host": args.host,
            "warehouse_id": args.warehouse_id,
            "mcp_profile": args.mcp_profile or f"{cat}_dev",
            "reader_group": args.reader_group or f"{cat}_readers",
            "engineer_group": args.engineer_group or f"{cat}_engineers",
            "admin_group": args.admin_group or f"{cat}_admins",
            "deploy_sp": args.deploy_sp,
            "framework_tag": default_tag,
        }

    catalog, tag = r["catalog"], r["framework_tag"]
    if not re.match(r"^v\d+\.\d+\.\d+$", tag):
        raise SystemExit(
            f"scaffold: framework tag {tag!r} is not a vX.Y.Z release tag. var.datalab_version "
            "becomes the Volume wheel FILENAME (datalab-<version>-py3-none-any.whl), so a "
            "branch/rev pin (e.g. 'main') would never match the wheel publish_wheel builds. "
            "Pass --framework-tag v<x.y.z>."
        )
    ctx = {
        "@@CATALOG@@": catalog,
        "@@HOST@@": r["host"],
        "@@FRAMEWORK_TAG@@": tag,
        "@@DATALAB_VERSION@@": tag.lstrip("v"),
        "@@READER_GROUP@@": r["reader_group"],
        "@@ENGINEER_GROUP@@": r["engineer_group"],
        "@@ADMIN_GROUP@@": r["admin_group"],
        "@@DEPLOY_SP@@": r["deploy_sp"],
        "@@WAREHOUSE_ID@@": r["warehouse_id"],
        "@@MCP_PROFILE@@": r["mcp_profile"],
    }

    def subst(text: str) -> str:
        for key, value in ctx.items():
            text = text.replace(key, value)
        return text

    if args.in_place:
        print(f"scaffold: configuring '{catalog}' adopter IN PLACE at {out}")
        print("  removing: " + ", ".join(sorted(EXCLUDE_TOP)) + "; rewriting repo-level files")
        if not (args.yes or args.interactive):  # interactive already confirmed via the summary
            if not sys.stdin.isatty():
                parser.error("--in-place needs --yes (or --interactive) for non-interactive use")
            if not confirm("Proceed? This rewrites the current repo in place."):
                raise SystemExit("scaffold: aborted")
        drop_reference_material(out)
    else:
        if out.exists() and any(out.iterdir()):
            if not args.force:
                parser.error(f"{out} exists and is not empty (use --force to overwrite)")
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        print(f"scaffold: generating '{catalog}' adopter repo at {out}")
        copy_scaffold(out)

    remove_template_only_paths(out)
    write_domain(out, ctx, subst)
    write_repo_level(out, subst)
    patch_makefile(out, catalog)
    patch_bootstrap_uc(out, catalog, ctx)
    patch_domains(out, catalog)
    patch_rbac(out, ctx)
    patch_ci(out)
    patch_cd(out, catalog)
    slug = repo_slug(out) if args.in_place else ""
    patch_cicd_docs(out, ctx, slug if slug and slug != TEMPLATE_SLUG else "<owner>/<repo>")
    patch_agents_md(out, catalog, subst)
    patch_databricksignore(out)
    patch_mcp(out, ctx)
    # The rest of the surfaces an adopter actually reads: the remaining docs,
    # the Cursor rule file, the two domain-aware skills, CODEOWNERS, dependabot
    # and the stale workflow headers.
    patch_doc_regions(out, subst)
    patch_agent_mcp(out, ctx)
    patch_cursor_rules(out, catalog)
    patch_skills(out, subst)
    patch_codeowners(out)
    patch_dependabot(out)
    patch_workflow_comments(out)

    print("scaffold: done. Next:")
    if args.in_place:
        print("  make lock install && make validate-configs lint test")
    else:
        print(f"  cd {args.out} && git init -b main && make lock install")
        print("  make validate-configs lint test")
    print("  # then follow docs/NEW_ADOPTER.md — the ordered first-deploy checklist")
    print("  # (GitHub wiring, account-level groups, bootstrap-uc, publish-wheel, deploy)")
    todos = [
        label
        for label, value in (("host", r["host"]), ("deploy SP", r["deploy_sp"]), ("warehouse id", r["warehouse_id"]))
        if "<" in value
    ]
    if todos:
        print(f"  NOTE: still placeholders — fill before deploy: {', '.join(todos)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
