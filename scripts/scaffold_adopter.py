"""Configure a minimal datalab adopter repo — deterministically, no per-run surgery.

It DROPS the reference domains (``projects/``), the template's design assets and
the dev-time pilot (``omnigent/``), writes ONE minimal root-level domain renamed
to your catalog, rewrites the repo-level files for the adopter layout
(single-package ``pyproject.toml``, root ``resources/``, single catalog) and
repoints the workspace-specific surfaces at your workspace — including the MCP
grounding config (``.mcp.json`` / ``.cursor/mcp.json``).

Only the MANDATORY surface is fixed. Everything else is a choice, confirmed per
repo (``AGENT_CHOICES`` / ``COMPONENT_CHOICES`` below):

* **coding agents** — any of claude, codex, cursor, genie (or none). Each brings
  only its own harness files; the shared skills in ``.agents/skills`` ship when
  at least one agent is chosen.
* **components** — docs/, design/ (generated for THIS customer's pipeline, with
  a pipeline inventory that ``make design`` keeps current), schemas/, local dev
  tooling (sample_data/ + run-local + validate-connect), the git pre-commit
  guard, the PR template, dependabot, the framework-bump bot, MCP grounding.

What a choice REMOVES is declared once: ``TOP_LEVEL`` + ``PATH_RULES`` say which
files it owns, and ``adopter-if:<feature>`` markers in the shared files
(Makefile, CI, AGENTS.md, docs, …) fence the prose/targets/steps that only make
sense with it — see ``apply_markers``. A new top-level file in the template that
is not classified in ``TOP_LEVEL`` fails the scaffold, so nothing ships (or
vanishes) by accident.

Two run modes:

* ``--in-place`` — convert the CURRENT repo (a clone you made from the GitHub
  template) into the adopter. This is the path the ``bootstrap-adopter-repo``
  skill / ``make configure-adopter`` drive.
* ``--out <dir>`` — generate a fresh sibling repo from this one, copying only
  git-tracked files (never secrets/state/build output). This is ``make
  new-adopter``.

Both BUILD the adopter in a scratch directory first and touch the destination
only once every patch and check has passed — a failure never leaves a
half-converted clone behind.

``--interactive`` walks a short form (identity → workspace & environments →
access → coding agents → components → framework), shows a summary of what will
be kept and dropped, and asks for confirmation; flags prefill (and skip) its
questions. Every answer is recorded in the adopter's ``.datalab-adopter.json``,
which ``--answers <file>`` replays — the non-interactive path for agents/CI:

    # convert a template clone in place, walking the form:
    python scripts/scaffold_adopter.py --in-place --interactive

    # non-interactive (agent/CI), every value supplied:
    python scripts/scaffold_adopter.py --in-place --yes --catalog acme \\
        --customer "Acme Corp" --host https://<workspace> --warehouse-id <id> \\
        --deploy-sp <app-id> --agents claude,cursor --components default,+design

    # fresh sibling repo, replaying a previous run's answers:
    python scripts/scaffold_adopter.py --out ../acme-datalab \\
        --answers ../acme-datalab-old/.datalab-adopter.json [--force]

Then, inside the configured repo:

    git init -b main && make lock install && make validate-configs lint test

The ``<catalog>`` must be the BASE catalog name (lowercase, no ``_dev`` /
``_stage`` / ``_prod`` suffix — the bundle appends those per target; see
``docs/NAMING.md``); a suffixed name is rejected. The scaffold only runs from
the template (or a fresh template clone) — an already-generated adopter is
refused. This is the deterministic engine behind the ``bootstrap-adopter-repo``
agent skill; the file templates here mirror that skill's
``references/templates.md``. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The adopter's record of how it was generated (answers + template commit).
# `--answers <file>` replays it; it is dev-only, so the bundle never syncs it.
MANIFEST = ".datalab-adopter.json"

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

# Placeholder defaults for values the user may not have yet. They land in the
# files verbatim and are listed as fill-before-deploy TODOs at the end.
HOST_PLACEHOLDER = "https://<your-workspace-host>"
WAREHOUSE_PLACEHOLDER = "<sql-warehouse-id>"
DEPLOY_SP_PLACEHOLDER = "<deploy-sp-app-id>"
REPO_PLACEHOLDER = "<owner>/<repo>"

# Where adopters find material the conversion did not ship (a dropped doc, the
# worked examples): the template repo itself. Adopters already need read access
# to it (docs/NEW_ADOPTER.md step 0).
TEMPLATE_URL = f"https://github.com/{TEMPLATE_SLUG}/blob/main"

# The bundle promotes dev → stage → prod; all three targets are always defined
# (an environment whose GitHub Environment has no Databricks secrets is skipped
# gracefully by CI/CD, so a customer without stage yet just leaves it unwired).
ENVIRONMENTS = ("dev", "stage", "prod")


# --------------------------------------------------------------------------- #
# What is optional — the choices, and the files each one owns.
# --------------------------------------------------------------------------- #

# Coding agents. Each brings only its own harness; `.agents/skills` (the shared,
# canonical skills) ships whenever at least one is chosen.
AGENT_CHOICES: dict[str, str] = {
    "claude": "Claude Code — CLAUDE.md, .claude/ (settings, hooks, skills copy)",
    "codex": "OpenAI Codex — .codex/hooks.json (reads AGENTS.md + .agents/skills)",
    "cursor": "Cursor — .cursor/ rules + hooks (reads .agents/skills natively)",
    "genie": "Databricks Genie Code — make publish-genie-skills (Workspace skills)",
}

# Optional components: name -> (on by default?, what it adds). The defaults keep
# the long-standing adopter shape; `design` is opt-in.
COMPONENT_CHOICES: dict[str, tuple[bool, str]] = {
    "docs": (True, "docs/ — onboarding checklist, CI/CD, naming, architecture guides"),
    "design": (False, "design/ — architecture diagram + overview + generated pipeline inventory"),
    "schemas": (True, "schemas/ — JSON schemas that validate config YAML in the editor"),
    "local-dev": (True, "sample_data/ + make run-local / dry-run-local / validate-connect"),
    "githooks": (True, ".githooks/ — human pre-commit guard (branch-first, protected files)"),
    "pr-template": (True, "unified PR template + its CI check (+ the agents' gh pr guard)"),
    "dependabot": (True, ".github/dependabot.yml — dependency-update PRs"),
    "framework-bot": (True, "bot workflow that opens a PR when datalab releases a new tag"),
    "mcp": (True, "read-only Databricks SQL MCP grounding (needs claude or cursor)"),
}

# Features derived from the selection (usable in `adopter-if:` markers and the
# ownership rules below), beyond the plain agent-<name> / component names.
DERIVED_FEATURES = {
    "any-agent": "at least one coding agent",
    "hooked-agent": "claude, codex or cursor — the agents that run the repo's guard hooks",
    "template": "never true in an adopter — content that exists only in the template",
}
KNOWN_FEATURES = (
    {f"agent-{a}" for a in AGENT_CHOICES} | set(COMPONENT_CHOICES) | set(DERIVED_FEATURES)
)

# Every TRACKED top-level entry of the template and its fate in an adopter:
#   "keep"     — copied (then patched; some are rewritten whole by the engine)
#   "template" — never copied (reference material, template-only tooling, or a
#                file the engine generates from scratch when its feature is on)
#   <expr>     — copied only when the feature expression holds (see evaluate())
# The scaffold FAILS on a tracked top-level entry missing here, so a new root
# file is a deliberate decision, never an accident.
TOP_LEVEL: dict[str, str] = {
    ".agents": "any-agent",
    ".claude": "agent-claude|agent-codex",  # codex hooks reuse the .claude guard
    ".codex": "agent-codex",
    ".cursor": "hooked-agent",  # .cursor/hooks/*.py are the SHARED guard scripts
    ".databricksignore": "keep",  # regenerated to match databricks.yml sync.exclude
    ".gitattributes": "template",  # design-only linguist rules; regenerated with design
    ".githooks": "githooks",
    ".github": "keep",
    ".gitignore": "keep",
    ".markdownlint.json": "keep",
    ".mcp.json": "mcp&agent-claude",
    "AGENTS.md": "keep",
    "CHANGELOG.md": "keep",  # regenerated
    "CLAUDE.md": "agent-claude",
    "Makefile": "keep",
    "README.md": "keep",  # regenerated
    "databricks.yml": "keep",  # regenerated
    "design": "template",  # the adopter's own design/ is generated (design component)
    "docs": "docs",
    "omnigent": "template",
    "projects": "template",
    "pyproject.toml": "keep",  # regenerated
    "rbac.yml": "keep",
    "schemas": "schemas",
    "scripts": "keep",
    "targets": "keep",  # regenerated
    "uv.lock": "template",  # regenerated for the single package by `make lock`
    "variables": "keep",  # regenerated
}

# Finer-grained ownership below the top level: a file ships only if EVERY rule
# whose path is it (or one of its parents) holds. Paths must exist in the
# template — a stale rule fails the scaffold.
PATH_RULES: list[tuple[str, str]] = [
    # agent harness — shared guards vs per-agent files
    (".agents/skills/bootstrap-adopter-repo", "template"),  # drives THIS conversion
    (".agents/skills/maintain-design-diagram", "design"),
    (".agents/skills/drawio-architecture-designer", "design"),  # the diagrams are built with it
    (".agents/skills/query-databricks", "mcp"),
    (".claude/skills", "agent-claude"),  # regenerated from .agents/skills
    (".claude/settings.json", "agent-claude"),
    (".claude/hooks/protected_files_guard.py", "agent-claude|agent-codex"),
    (".cursor/hooks/branch_guard.py", "hooked-agent"),
    (".cursor/hooks/pr_template_guard.py", "hooked-agent&pr-template"),
    (".cursor/hooks/design_drawio_guard.py", "hooked-agent&design"),
    (".cursor/hooks.json", "agent-cursor"),
    (".cursor/rules", "agent-cursor"),
    (".cursor/mcp.json", "agent-cursor&mcp"),
    # docs that only make sense with their feature / only in the template
    ("docs/AGENT_MCP.md", "mcp"),
    ("docs/MIGRATION.md", "template"),  # the template's own restructure history
    # scripts follow the feature they serve; the scaffold tooling stays home
    ("scripts/scaffold_adopter.py", "template"),
    ("scripts/check_templates_doc.py", "template"),
    ("scripts/check_adopter_docs.py", "template"),
    ("scripts/tests", "template"),  # the gate scripts' tests; adopters collect only tests/
    ("scripts/check_framework_surface.py", "schemas&any-agent"),  # reads schemas/ + the .agents skill
    ("scripts/export_design.py", "design"),
    ("scripts/design_inventory.py", "design"),
    ("scripts/design_diagram.py", "design"),
    ("scripts/design_spec.py", "design"),
    ("scripts/drawio_kit", "design"),
    ("scripts/sync_skills.py", "agent-claude"),
    ("scripts/publish_genie_skills.py", "agent-genie"),
    ("scripts/check_agent_settings.py", "hooked-agent"),
    ("scripts/sync_schemas.py", "schemas"),
    ("scripts/validate_connect.py", "local-dev"),
    # GitHub extras
    (".github/pull_request_template.md", "pr-template"),
    (".github/workflows/pr-template-check.yml", "pr-template"),
    (".github/dependabot.yml", "dependabot"),
    (".github/workflows/framework-bump.yml", "framework-bot"),
]


def evaluate(expr: str, features: set[str], where: str = "") -> bool:
    """Evaluate a feature expression: `a|b` (any), `a&b` (all), `!a` (not);
    `&` binds tighter than `|`. Unknown names fail loudly — a typo in a marker
    must not silently drop (or keep) a region."""
    for term in expr.split("|"):
        ok = True
        for literal in term.split("&"):
            name = literal.removeprefix("!")
            if name not in KNOWN_FEATURES:
                raise SystemExit(
                    f"scaffold: unknown feature {name!r} in {expr!r}{f' ({where})' if where else ''}. "
                    f"Known: {', '.join(sorted(KNOWN_FEATURES))}"
                )
            ok = ok and ((name in features) != literal.startswith("!"))
        if ok:
            return True
    return False


@dataclass
class Selection:
    """Which coding agents and optional components an adopter carries."""

    agents: list[str]
    components: list[str]

    def __post_init__(self) -> None:
        # Canonical order + drop what cannot apply: MCP grounding is wired only
        # for Claude Code (.mcp.json) and Cursor (.cursor/mcp.json).
        self.agents = [a for a in AGENT_CHOICES if a in set(self.agents)]
        comps = set(self.components)
        if not {"claude", "cursor"} & set(self.agents):
            comps.discard("mcp")
        self.components = [c for c in COMPONENT_CHOICES if c in comps]

    @property
    def features(self) -> set[str]:
        feats = {f"agent-{a}" for a in self.agents} | set(self.components)
        if self.agents:
            feats.add("any-agent")
        if {"claude", "codex", "cursor"} & set(self.agents):
            feats.add("hooked-agent")
        return feats

    def has(self, feature: str) -> bool:
        return evaluate(feature, self.features)


def parse_choice_list(value: str, choices, defaults: list[str], what: str) -> list[str]:
    """Parse `--agents` / `--components`: a comma list, or `all` / `none` /
    `default`, or +x / -x edits applied to the defaults (`default,+design,-githooks`
    or just `+design`). Unknown names fail loudly."""
    value = value.strip()
    if not value:
        return list(defaults)
    picked: list[str] = []
    relative = False
    for raw in (part.strip() for part in value.split(",")):
        if not raw:
            continue
        if raw in ("all", "none", "default"):
            picked = {"all": list(choices), "none": [], "default": list(defaults)}[raw]
            relative = True
            continue
        sign, name = (raw[0], raw[1:]) if raw[0] in "+-" else ("", raw)
        if name not in choices:
            raise SystemExit(
                f"scaffold: unknown {what} {name!r} — choose from: {', '.join(choices)} "
                "(or all / none / default, and +name / -name edits)"
            )
        if sign and not relative and not picked:
            picked, relative = list(defaults), True
        if sign == "-":
            picked = [p for p in picked if p != name]
        elif name not in picked:
            picked.append(name)
    return picked


def default_components() -> list[str]:
    return [name for name, (on, _) in COMPONENT_CHOICES.items() if on]


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
@@SYNC_EXCLUDE@@
"""

# Written from the SAME entry list as databricks.yml's sync.exclude (see
# sync_excludes()), so the two can never disagree about a path this repo has.
DATABRICKSIGNORE = """\
# Exclusions for `databricks sync` and the Databricks IDE extension.
#
# IMPORTANT: `databricks bundle deploy` does NOT read this file — it honors
# .gitignore plus the `sync.exclude:` block in databricks.yml. Keep this list
# ALIGNED with that block so the sync command and the bundle deploy exclude the
# same dev-only surfaces (`make check-sync-lists` enforces it).
#
# The deploy MUST ship pyproject.toml + src/** + config/** + resources/** — the
# domain wheel is built by the databricks.yml `artifacts:`, and the framework
# wheel is installed from this catalog's artifacts.wheels UC Volume (AGENTS.md
# "Wheel delivery").

@@IGNORE_ENTRIES@@
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
# adopter-if:design start
# Vendored verbatim from the drawio-architecture-designer skill (the diagram
# kit scripts/design_diagram.py builds on) - kept byte-close to its upstream.
extend-exclude = ["scripts/drawio_kit"]
# adopter-if:design end

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
      catalog: @@CATALOG_DEV@@
"""

TARGET_STAGE = """\
# stage target — production mode, explicit root_path. Deployed by CI on a
# vX.Y.Z-rcN tag once the `stage` GitHub Environment carries its secrets.
targets:
  stage:
    mode: production
    workspace:
      host: @@HOST_STAGE@@
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: @@CATALOG_STAGE@@
"""

TARGET_PROD = """\
# prod target — production mode, explicit root_path. Deployed by CI on a vX.Y.Z
# tag once the `prod` GitHub Environment carries its secrets.
targets:
  prod:
    mode: production
    workspace:
      host: @@HOST_PROD@@
      root_path: /Workspace/Bundles/${bundle.name}/${bundle.target}
    variables:
      catalog: @@CATALOG_PROD@@
"""

# Sections fenced `<!-- adopter-if:<feature> start/end -->` are kept only when
# the feature was chosen (apply_markers) — one README per selection.
README_MD = """\
# @@CATALOG@@-datalab

**@@CUSTOMER@@** — @@DESCRIPTION@@

Single-domain [datalab](https://github.com/dediggibyte/datalab-framework) adopter
repo for @@CUSTOMER@@, generated from the datalab template. Every target table
is ONE YAML artifact, generated into Lakeflow Spark Declarative Pipelines,
quality-checked with dqx, and deployed as a Declarative Automation Bundle.

<!-- adopter-if:docs start -->
> Document of record for agents + humans: **[AGENTS.md](AGENTS.md)**. First-deploy
> checklist: **[docs/NEW_ADOPTER.md](docs/NEW_ADOPTER.md)**. Wiring to the
> framework: **[docs/ADOPTING.md](docs/ADOPTING.md)**. Author your first table:
> **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**.
<!-- adopter-if:docs end -->
<!-- adopter-if:!docs start -->
> Document of record for agents + humans: **[AGENTS.md](AGENTS.md)**. This repo
> was generated without the `docs/` guides; the first-deploy checklist, the
> framework wiring reference and the authoring walkthrough live in the datalab
> template repo: [NEW_ADOPTER.md](@@TEMPLATE_URL@@/docs/NEW_ADOPTER.md) ·
> [ADOPTING.md](@@TEMPLATE_URL@@/docs/ADOPTING.md) ·
> [GETTING_STARTED.md](@@TEMPLATE_URL@@/docs/GETTING_STARTED.md).
<!-- adopter-if:!docs end -->
<!-- adopter-if:design start -->
> Architecture and the generated pipeline inventory for @@CUSTOMER@@:
> **[design/OVERVIEW.md](design/OVERVIEW.md)**.
<!-- adopter-if:design end -->

## Quick start

```bash
make lock install                # resolve the framework git dep into .venv
make validate-configs lint test  # pydantic + dqx · ruff · pytest (local Spark)
make validate                    # databricks bundle validate -t dev
```
<!-- adopter-if:githooks start -->

Once per clone, turn on the branch-first / protected-files pre-commit guard:
`make enable-githooks`.
<!-- adopter-if:githooks end -->

## First deploy (one-time setup per target)

<!-- adopter-if:docs start -->
The full ordered checklist — prerequisites, GitHub/OIDC wiring, and the
account-level persona groups that must exist BEFORE bootstrap — is
**[docs/NEW_ADOPTER.md](docs/NEW_ADOPTER.md)** (start at step 3: this repo is
already generated).
<!-- adopter-if:docs end -->
<!-- adopter-if:!docs start -->
The full ordered checklist — prerequisites, GitHub/OIDC wiring, and the
account-level persona groups that must exist BEFORE bootstrap — is the datalab
template repo's [docs/NEW_ADOPTER.md](@@TEMPLATE_URL@@/docs/NEW_ADOPTER.md)
(start at step 3: this repo is already generated).
<!-- adopter-if:!docs end -->
The commands, once those prerequisites stand (`PROFILE=` pins the workspace —
without it the SDK uses your DEFAULT CLI profile, which may point somewhere
else):

```bash
databricks auth login --host @@HOST@@ --profile @@MCP_PROFILE@@
make bootstrap-uc TARGET=dev WAREHOUSE_ID=@@WAREHOUSE_ID@@ PROFILE=@@MCP_PROFILE@@
make publish-wheel TARGET=dev APPLY=1 PROFILE=@@MCP_PROFILE@@
git add -A && git commit -m "configure @@CATALOG@@ adopter" && git push  # CI needs the regenerated uv.lock
make deploy
```

<!-- adopter-if:local-dev start -->
Seed the landing volume with the starter sample, then refresh the pipeline:

```bash
databricks fs cp sample_data/landing/@@CATALOG@@/events/events.json \\
    dbfs:/Volumes/@@CATALOG_DEV@@/landing/@@CATALOG@@/events/ --profile @@MCP_PROFILE@@
make run
```
<!-- adopter-if:local-dev end -->
<!-- adopter-if:!local-dev start -->
Drop a JSON file into `/Volumes/@@CATALOG_DEV@@/landing/@@CATALOG@@/events/`,
then refresh the pipeline with `make run`.
<!-- adopter-if:!local-dev end -->

## Add tables

<!-- adopter-if:any-agent start -->
Use the `author-ldp-artifact` agent skill: one `config/@@CATALOG@@/<layer>/<table>.yml`
artifact per table, pure `@transform` functions in `src/@@CATALOG@@_etl/transforms/`,
registered in `config/@@CATALOG@@/domain.yml` `imports:`.
<!-- adopter-if:any-agent end -->
<!-- adopter-if:!any-agent start -->
Author one `config/@@CATALOG@@/<layer>/<table>.yml` artifact per table, pure
`@transform` functions in `src/@@CATALOG@@_etl/transforms/`, registered in
`config/@@CATALOG@@/domain.yml` `imports:`. Field reference: the framework's
[FRAMEWORK.md](https://github.com/dediggibyte/datalab-framework/blob/@@FRAMEWORK_TAG@@/docs/FRAMEWORK.md);
the datalab template repo's
[author-ldp-artifact skill](@@TEMPLATE_URL@@/.agents/skills/author-ldp-artifact/SKILL.md)
doubles as a human guide (plain-language rule → dqx check mapping).
<!-- adopter-if:!any-agent end -->
<!-- adopter-if:design start -->

After adding or changing tables, jobs or pipelines, run `make design`: it
re-renders the pipeline inventory in `design/PIPELINES.md` and regenerates the
draw.io diagrams from the estate (CI's `make check-design` fails while either is
stale or a diagram was hand-edited). Never edit a `.drawio` file by hand.
<!-- adopter-if:design end -->

## How this repo was generated

From the datalab template with — coding agents: **@@AGENTS_LIST@@**; components:
**@@COMPONENTS_LIST@@**. Every answer is recorded in `.datalab-adopter.json`; to
regenerate with a newer template (e.g. to diff in its improvements), run
`make new-adopter ANSWERS=<path-to>/.datalab-adopter.json OUT=<dir>` from a
clone of the datalab template repo.
"""

CHANGELOG_MD = """\
# Changelog

All notable changes to this repo are documented here, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format with
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Releases are cut by the deploy.** Record every change as a bullet under
`## [Unreleased]` (start it `**BREAKING:**` when it breaks something). After
each successful deploy of `main` to dev, CI moves those entries into
`## [X.Y.Z] — YYYY-MM-DD`, sets `pyproject.toml` `[project].version` (and
`uv.lock`) to `X.Y.Z` and pushes a `chore(release): vX.Y.Z` commit — the commit
stage and prod promote (tag `vX.Y.Z-rcN` / `vX.Y.Z`). Never cut a version by
hand; `make release-changelog` previews the next cut.

## [Unreleased]

### Added
- Initial @@CATALOG@@ adopter repo for @@CUSTOMER@@, generated from the datalab
  template (one minimal bronze table to extend). Coding agents: @@AGENTS_LIST@@;
  components: @@COMPONENTS_LIST@@.
"""

# design/ component — the adopter's OWN design package (the template's design/
# describes the template's reference domains, so it is never copied). The
# pipeline inventory (design/PIPELINES.md) is rendered by
# scripts/design_inventory.py from config/, so it tracks the pipelines as they
# grow; this overview is the hand-maintained narrative around it.
DESIGN_OVERVIEW_MD = """\
# @@CUSTOMER@@ — `@@CATALOG@@` lakehouse on Databricks

@@DESCRIPTION@@

> This is the living design package for this repo. The estate map
> [`02_implementation_end_to_end.drawio`](02_implementation_end_to_end.drawio)
> (an overview, one lineage page per domain, and the delivery path) and the
> framework's conceptual design
> [`01_design_config_driven_medallion.drawio`](01_design_config_driven_medallion.drawio)
> are **generated** by `make design` from the repo itself - never edit their XML.
> **[PIPELINES.md](PIPELINES.md) is generated from `config/`** - every table,
> its source, target kind and quality gate. CI fails while any of them is stale.

## At a glance

| | |
|---|---|
| **Customer** | @@CUSTOMER@@ |
| **Domain / base catalog** | `@@CATALOG@@` — config in `config/@@CATALOG@@/`, code in `src/@@CATALOG@@_etl/` |
| **Pipeline** | `@@CATALOG@@_etl` — Lakeflow Spark Declarative Pipeline, serverless |
| **Refresh** | `@@CATALOG@@_etl_refresh` — daily (paused in dev) |
| **Framework** | datalab `@@FRAMEWORK_TAG@@` (git dependency + UC-Volume wheel) |
| **Pipeline inventory** | [PIPELINES.md](PIPELINES.md) (generated — `make design`) |

## Architecture

```mermaid
flowchart LR
  dev["Engineer or coding agent<br/>writes one YAML artifact per table"] --> cfg["config/@@CATALOG@@/&lt;layer&gt;/&lt;table&gt;.yml"]
  cfg --> fw["datalab framework<br/>validates + generates"]
  fw --> sdp["Lakeflow SDP pipeline<br/>@@CATALOG@@_etl"]
  land["landing volume<br/>/Volumes/&lt;catalog&gt;/landing/@@CATALOG@@/"] -->|Auto Loader| sdp
  sdp --> bronze["bronze"] --> silver["silver<br/>dqx gate + quarantine"] --> gold["gold"]
  gold --> use["BI · Genie · apps"]
  gh["GitHub Actions<br/>OIDC, no stored secret"] -->|bundle deploy| sdp
```

The medallion starts with one bronze table; [PIPELINES.md](PIPELINES.md) holds
the live table-by-table lineage.

## Environments and promotion

| Target | Workspace | Catalog | Mode | Deployed by |
|---|---|---|---|---|
| dev | `@@HOST@@` | `@@CATALOG_DEV@@` | development | every push to `main` |
| stage | `@@HOST_STAGE@@` | `@@CATALOG_STAGE@@` | production | a `vX.Y.Z-rcN` tag |
| prod | `@@HOST_PROD@@` | `@@CATALOG_PROD@@` | production | a `vX.Y.Z` tag |

Promotion never edits a config file: catalogs, schemas and paths are bundle
variables resolved per target.

## Keeping this package current

- **Tables** — after adding or changing a `config/@@CATALOG@@/…` artifact, run
  `make design`; it re-renders [PIPELINES.md](PIPELINES.md). CI runs
  `make check-design` and fails while the inventory is stale.
- **Architecture** - new tables, pipelines and jobs appear on the diagrams by
  themselves on the next `make design`. A source system, consumer or edge-job
  read/write that no bundle YAML states goes in [`estate.yml`](estate.yml); then
  `make design`, look at `make design-preview`, and refresh this overview's
  narrative.
"""

GITATTRIBUTES_DESIGN = """\
# GitHub Linguist: design/ is documentation (draw.io sources, their PNG exports,
# the overview and the generated pipeline inventory), not source — keep it out
# of the repository's language statistics.
design/**              linguist-documentation
# Rendered by `make design` (scripts/design_inventory.py) — collapse it in diffs.
design/PIPELINES.md    linguist-generated
# Generated by `make design` (scripts/design_diagram.py) - collapse them in diffs.
design/*.drawio        linguist-generated
"""

# The adopter's starter overlay for the generated diagrams: nothing yet to
# declare - a source system upstream of the landing volume, a consumer of gold,
# or what an edge job reads and writes goes here as the estate grows.
DESIGN_ESTATE_YML = """\
# design/estate.yml - what the diagrams need that no bundle YAML states.
#
# design/*.drawio are GENERATED by scripts/design_diagram.py from config/,
# resources/*.yml, targets/, .github/workflows/ and this file (`make design`;
# `make check-design` fails CI when they drift). Declare only relationships the
# code cannot express. Tables are <domain>.<layer>.<table>; an unknown one
# fails the generator. See the maintain-design-diagram skill.
#
# sources:   [{name, detail?, logo?, feeds: [@@CATALOG@@.bronze.<table>]}]
# consumers: [{name, detail?, logo?, reads: [@@CATALOG@@.gold.<table>]}]
# jobs:      {<job resource key>: {reads: [...], writes: <string>}}
"""

# The framework's conceptual design spec is generic except for a few worked-
# example references; each is repointed at the adopter's own domain.
# The conceptual spec (scripts/design_spec.py, copied with the design component)
# names the template's worked example; repoint the lines that must read true
# for an adopter. Applied to the SCRIPT's text, so the adopter's own
# `make design` / `make check-design` regenerate exactly what the scaffold wrote.
DESIGN_SPEC_EDITS: list[tuple[str, str]] = [
    (
        "• Two reference domains: <tt>projects/customer_sales/</tt> (bronze → silver "
        "(AUTO CDC SCD1) → gold, dqx valid/quarantine, edge jobs + notebook) and "
        "<tt>projects/sales/</tt> (pipeline-only feature showcase)",
        "• This repo's domain <tt>@@CATALOG@@</tt> at the repo root "
        "(<tt>config/@@CATALOG@@/</tt>, <tt>src/@@CATALOG@@_etl/</tt>): one YAML artifact per table",
    ),
    (
        "The customer_sales_etl pipeline runs serverless on Databricks (environment_version 4).",
        "The @@CATALOG@@_etl pipeline runs serverless on Databricks.",
    ),
    (
        "/Volumes/&lt;catalog&gt;/\\u200blanding/sales/customers/",
        "/Volumes/&lt;catalog&gt;/\\u200blanding/@@CATALOG@@/events/",
    ),
    ("customer_sales_etl_refresh", "@@CATALOG@@_etl_refresh"),
    (
        "• <tt>projects/*/resources/*.yml</tt> — 2 SDP pipelines + 3 jobs (refresh / export / quarantine-report)",
        "• <tt>resources/*.yml</tt> — the <tt>@@CATALOG@@_etl</tt> SDP pipeline + its refresh job",
    ),
]


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


def tracked_files() -> list[str]:
    """Every git-TRACKED file of the template. Using `git ls-files` (not a
    filesystem walk) means gitignored files — secrets (.env), .venv,
    .databricks, dist/ build output — can never reach an adopter."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(f"scaffold: `git ls-files` failed ({exc}) — run inside the repo") from exc
    tracked = [p for p in result.stdout.split("\0") if p and (REPO_ROOT / p).is_file()]
    if not tracked:
        raise SystemExit("scaffold: `git ls-files` returned nothing — run inside the repo")
    return tracked


def ensure_template_layout() -> None:
    """Refuse to run anywhere but the template (or a fresh clone of it).

    Inside an already-generated adopter the engine used to overwrite
    pyproject.toml, databricks.yml, targets/, variables/, README and CHANGELOG,
    add a second domain — and only THEN crash on the first missing template
    anchor, leaving a half-rewritten repo. The reference domains under
    projects/ are what every template-only anchor hangs off, so their absence
    means "not a template"."""
    if not (REPO_ROOT / "projects").is_dir():
        raise SystemExit(
            "scaffold: this repo has no projects/ — it looks like an adopter that was already "
            "generated, not the datalab template. The scaffold only runs from the template (or "
            "a fresh clone of it): generate a new repo from the template instead."
        )


def check_rules(tracked: list[str]) -> None:
    """Drift guards for the ownership tables: every tracked top-level entry is
    classified, and every PATH_RULES path still exists in the template."""
    unclassified = sorted({rel.split("/", 1)[0] for rel in tracked} - set(TOP_LEVEL))
    if unclassified:
        raise SystemExit(
            "scaffold: unclassified top-level entr"
            f"{'y' if len(unclassified) == 1 else 'ies'} {', '.join(unclassified)} — decide "
            "whether each ships to adopters and add it to TOP_LEVEL in scripts/scaffold_adopter.py "
            '("keep", "template", or a feature expression).'
        )
    tracked_set = set(tracked)
    for path, _ in PATH_RULES:
        if path not in tracked_set and not any(t.startswith(path + "/") for t in tracked):
            raise SystemExit(
                f"scaffold: PATH_RULES names {path!r}, which the template no longer has — "
                "update the rule in scripts/scaffold_adopter.py."
            )


def ships(rel: str, features: set[str]) -> bool:
    """Does template file `rel` belong in an adopter with these features?"""
    rule = TOP_LEVEL[rel.split("/", 1)[0]]
    if rule == "template" or (rule != "keep" and not evaluate(rule, features, "TOP_LEVEL")):
        return False
    return all(
        evaluate(expr, features, f"PATH_RULES {path}")
        for path, expr in PATH_RULES
        if rel == path or rel.startswith(path + "/")
    )


def copy_selected(stage: Path, tracked: list[str], features: set[str]) -> None:
    for rel in tracked:
        if ships(rel, features):
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / rel, dest)


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
    # `make help` printed "default customer_sales_etl" in every adopter, and the
    # comment pointed at the template's second domain.
    text = require_replace(
        text,
        "# Any deployed pipeline/job resource works: PIPELINE=sales_etl refreshes the\n"
        "# second reference domain (it has no scheduled job — on-demand by design).\n"
        "PIPELINE ?= customer_sales_etl\n",
        "# Any deployed pipeline/job resource works (PIPELINE=<resource key>); the\n"
        "# default is this domain's pipeline.\n"
        f"PIPELINE ?= {catalog}_etl\n",
        "Makefile",
    )
    text = require_replace(
        text,
        "(PIPELINE=<resource>, default customer_sales_etl)",
        f"(PIPELINE=<resource>, default {catalog}_etl)",
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
    # Optional sections (design, skills, local dev, githooks, the scaffold
    # itself …) are fenced `# adopter-if:<feature>` and resolved by apply_markers.
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

ARCH_DESIGN_BANNER = """\
> Generated architecture diagrams (draw.io, built from the estate) and the
> pipeline inventory live in `design/` - see [Editing the design package](#editing-the-design-package).
"""

ARCH_DESIGN_SECTION = """\
## Editing the design package

`design/` is this repo's living picture of its estate: how many jobs,
pipelines, tables and views it deploys and how they connect. Everything in it
except `OVERVIEW.md` and `estate.yml` is GENERATED by `make design` - never edit
a `.drawio` file's XML. `design/` is in the bundle's `sync.exclude`, so none of
it ships to the workspace.

| Path | Kind | Changes when |
|---|---|---|
| `design/02_implementation_end_to_end.drawio` | **Generated** estate map (overview, one lineage page per domain, delivery) from `config/`, `resources/`, `targets/`, `ci-cd.yml` and `estate.yml` (`scripts/design_diagram.py`) | any estate change - `make design` |
| `design/01_design_config_driven_medallion.drawio` | **Generated** conceptual spec from the text in `scripts/design_spec.py` | the design intent changes - edit that text, `make design` |
| `design/estate.yml` | **Hand-written** overlay: source systems, consumers, edge-job reads/writes | a relationship no bundle YAML states |
| `design/PIPELINES.md` | **Generated** pipeline inventory + lineage (mermaid) | every table change - `make design` |
| `design/images/*.png` | **Generated** PNG exports, one per page | never by hand - `make design` (draw.io Desktop, else the HTML twin) |
| `design/OVERVIEW.md` | Customer-facing narrative | the story changes (a new capability, source or consumer) |

The diagrams are laid out through the vendored drawio-architecture-designer
kit (`scripts/drawio_kit/`): cards sized from their text, arrows routed shape to
shape, and a layout audit that must be clean. `make design-preview` renders the
pages to PNG so you can look before committing; `make check-design` (CI) fails
when a diagram is stale, hand-edited, or fails the audit. Opening a `.drawio`
in draw.io to VIEW it is fine - saving it is not.

"""

ARCH_SYSTEM_VIEW = """\
```mermaid
flowchart LR
    subgraph GH["GitHub"]
        DEV["developer / agent<br/>push · PR"] --> CI["Actions: ci-cd.yml (target from the trigger)<br/>common-ci: ruff + pytest + bundle validate"]
        CI -->|"OIDC — no stored secret"| CD["common-cd: bundle deploy"]
    end

    subgraph WS["Databricks workspace"]
        CD --> DAB["Declarative Automation Bundle<br/>databricks.yml + resources/*.yml"]
        DAB --> PL["Lakeflow SDP pipeline: @@CATALOG@@_etl<br/>(serverless)"]
        DAB --> JOB["job: @@CATALOG@@_etl_refresh<br/>daily pipeline_task · paused in dev"]
        JOB --> PL
    end
```
"""

ARCH_LANES_DIAGRAM = """\
```mermaid
flowchart LR
    PL["SDP pipeline @@CATALOG@@_etl<br/>bronze → silver → gold<br/>(owns every medallion table)"]
    PL -->|read-only| EXP["an export job · python-file lane<br/>src/jobs/@@CATALOG@@/&lt;job&gt;.py<br/>→ /Volumes/&lt;catalog&gt;/exports/@@CATALOG@@/"]
    PL -->|read-only| QR["a triage notebook · notebook lane<br/>notebooks/@@CATALOG@@/&lt;notebook&gt;.py"]
    QR -.->|"repaired rows re-enter<br/>via landing"| PL
```
"""


def adopting_bump_changes(sel: Selection) -> str:
    """ADOPTING's "corresponding changes" step, naming only the authoring skill,
    surface gate, skills mirror and schemas this adopter carries."""
    skill, schemas = sel.has("any-agent"), sel.has("schemas")
    notes = [note for note, on in (("`make check-framework-surface` names them", schemas),
                                   ("`make sync-skills` after", sel.has("agent-claude"))) if on]
    touched = ["pyproject", "medallion.yml", "uv.lock", *(["schemas/"] if schemas else []),
               "the re-pinned docs", *(["the skill"] if skill else [])]
    text = (
        "1. Add the release's corresponding changes: read the framework CHANGELOG between "
        + ("the two versions, migrate anything flagged **BREAKING**, and document every new "
           "target/source kind in `.agents/skills/author-ldp-artifact/SKILL.md`"
           + (f" ({'; '.join(notes)})" if notes else "")
           if skill else "the two versions and migrate anything flagged **BREAKING**")
        + f". Commit everything the bump touched (`git status` — {', '.join(touched)})."
    )
    return _wrap(text, "   ") + "\n"


def arch_data_view(sel: Selection) -> str:
    inventory = (
        " The live, table-by-table lineage is generated into\n"
        "[design/PIPELINES.md](../design/PIPELINES.md) by `make design`."
        if sel.has("design") else ""
    )
    return (
        "## Data view (medallion)\n\n"
        "```mermaid\n"
        "flowchart LR\n"
        '    YML[["config/@@CATALOG@@/&lt;layer&gt;/*.yml<br/>Pydantic-validated artifacts<br/>'
        '(datasets + dqx rules)"]] -.->|"datalab.framework.generate"| BR\n'
        '    LAND[("UC volume<br/>landing/@@CATALOG@@/events")] -->|"Auto Loader cloudFiles"| '
        'BR["bronze.events_raw<br/>streaming_table + lineage cols"]\n'
        '    BR -.->|"next: one YAML per table"| SIL["silver.&lt;table&gt;<br/>dqx valid rows · AUTO CDC"]\n'
        '    BR -.->|"dqx error rows"| QUAR["silver.&lt;table&gt;_quarantine<br/>(dqx evidence structs)"]\n'
        '    SIL -.-> GOLD["gold.&lt;table&gt;<br/>materialized_view"]\n'
        "```\n\n"
        "The starter pipeline has the one bronze table; silver and gold arrive one\n"
        f"artifact at a time.{inventory}\n"
    )


ARCH_ENV_TABLE = """\
| Target | Mode | Catalog | Workspace | Trigger state |
|---|---|---|---|---|
| dev | development — resources prefixed `[dev <user>]`, isolated per user | `@@CATALOG_DEV@@` | `@@HOST@@` | paused |
| stage | production | `@@CATALOG_STAGE@@` | `@@HOST_STAGE@@` | live |
| prod | production | `@@CATALOG_PROD@@` | `@@HOST_PROD@@` | live |
"""

ADOPTING_GENERATED = """\
## This repo was generated

This repo was generated by the datalab template repo's configurator
(`scripts/scaffold_adopter.py` there), which recorded every answer — the coding
agents and components it carries, the per-target hosts and catalogs — in
[`.datalab-adopter.json`](../.datalab-adopter.json). The rest of this doc is the
reference behind that conversion; the ordered first-deploy checklist is
[NEW_ADOPTER.md](NEW_ADOPTER.md) (start at step 3). To stand up ANOTHER customer
repo — or to regenerate this one with a newer template, replaying the answers
with `ANSWERS=` — work from the datalab template repo, not from here.
"""

AGENT_MCP_ADOPTER_SETUP = """\
## This repo's MCP setup

The configurator already pointed this repo's MCP config at its SQL warehouse id
+ CLI profile (the table below) — there is nothing to swap unless the warehouse
id is still the `<sql-warehouse-id>` placeholder, in which case fill it now. You
can edit the JSON directly, or (Claude Code) export the env overrides the
defaults already reference:
"""

NEW_ADOPTER_GENERATED = """\
## 1–2. Generate and configure — done

This repo was generated from the datalab template repo and configured by its
configurator; the answers (coding agents, components, hosts, catalogs) are in
[`.datalab-adopter.json`](../.datalab-adopter.json). Start at step 3.
"""


def localize_docs(out: Path, a: Answers) -> None:
    """Re-cast the docs' worked examples (the template's `customer_sales`
    domain) in THIS repo's own catalog and per-target catalogs, so the naming
    contract, the MCP example query and the wheel volume read as facts about
    the customer's repo. Attributed references to the template's real files are
    left alone (they sit in template-only regions or name the template repo)."""
    cat, envs = a.catalog, a.catalogs
    naming = out / "docs" / "NAMING.md"
    if naming.exists():
        text = naming.read_text(encoding="utf-8")
        text = require_replace(
            text,
            "This page is the contract; the\n"
            "`customer_sales` reference domain in the datalab template repo demonstrates it.",
            f"This page is the contract, shown\nhere with this repo's own catalog, `{cat}`.",
            "docs/NAMING.md",
        )
        for env, template_cat in (("stage", "customer_sales_stage"), ("prod", "customer_sales_prod"),
                                  ("dev", "customer_sales")):
            text = require_replace(
                text, f"| {env} | `{template_cat}` |", f"| {env} | `{envs[env]}` |", "docs/NAMING.md"
            )
        naming.write_text(text.replace("customer_sales", cat), encoding="utf-8")
    mcp_doc = out / "docs" / "AGENT_MCP.md"
    if mcp_doc.exists():
        text = require_replace(
            mcp_doc.read_text(encoding="utf-8"),
            "*\"List tables in `customer_sales.silver`, then show 5 rows of\n  `silver.customers`.\"*",
            f"*\"List tables in `{envs['dev']}.bronze`, then show 5 rows of\n  `bronze.events_raw`.\"*",
            "docs/AGENT_MCP.md",
        )
        mcp_doc.write_text(text, encoding="utf-8")
    adopting = out / "docs" / "ADOPTING.md"
    if adopting.exists():
        text = require_replace(
            adopting.read_text(encoding="utf-8"),
            "(`customer_sales.artifacts.wheels`,\n`sales.artifacts.wheels` in this repo)",
            f"(`{envs['dev']}.artifacts.wheels` in dev here)",
            "docs/ADOPTING.md",
        )
        text = require_replace(
            text,
            "(`customer_sales` + `sales` in this repo, resolved\n"
            "  through `scripts/domains.py`; just `<your_catalog>` for a single-domain adopter)",
            f"(`{cat}` here, resolved through `scripts/domains.py`)",
            "docs/ADOPTING.md",
        )
        adopting.write_text(text, encoding="utf-8")


# Template-only regions in docs/, swapped exactly like AGENTS.md's. Markers must
# sit OUTSIDE fenced code blocks — a comment inside ```mermaid breaks rendering.
# A value may be a callable taking the Selection, for selection-dependent text.
DOC_REGIONS: dict[str, dict[str, object]] = {
    "docs/ARCHITECTURE.md": {
        # docs/MIGRATION.md is template history and is deleted from adopters.
        "arch-nav": (
            "[← README](../README.md) · **Architecture** · "
            "[Framework](FRAMEWORK.md) · [CI/CD](CICD.md)\n"
        ),
        # design/ is optional: without it there is no package (or `make
        # design`) to document; with it, the adopter's own package is.
        "arch-design-banner": lambda sel: ARCH_DESIGN_BANNER if sel.has("design") else "",
        "arch-design-section": lambda sel: ARCH_DESIGN_SECTION if sel.has("design") else "",
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
        "arch-system-view": ARCH_SYSTEM_VIEW,
        "arch-lanes-diagram": ARCH_LANES_DIAGRAM,
        "arch-data-view": arch_data_view,
        "arch-env-table": ARCH_ENV_TABLE,
        "arch-layer-rule": """\
2. **The repo root** — this adopter's single domain: the YAML artifacts
   (`config/@@CATALOG@@/`), the domain package (`src/@@CATALOG@@_etl/`), the
   edge-lane entry points (`src/jobs/@@CATALOG@@/`, `notebooks/@@CATALOG@@/`),
   the bundle `resources/`, and `tests/`. The datalab template repo carries the
   same shape nested under `projects/<domain>/`, one folder per reference domain.
""",
    },
    "docs/ADOPTING.md": {
        "adopting-quick-start": ADOPTING_GENERATED,
        "adopting-bump-changes": adopting_bump_changes,
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
    "docs/AGENT_MCP.md": {
        "agent-mcp-adopter-setup": AGENT_MCP_ADOPTER_SETUP,
    },
    "docs/NEW_ADOPTER.md": {
        "new-adopter-generate": NEW_ADOPTER_GENERATED,
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


def patch_doc_regions(out: Path, subst, sel: Selection) -> None:
    """Swap every `<!-- template-only:… -->` region in docs/ for adopter text."""
    for rel, regions in DOC_REGIONS.items():
        path = out / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for name, replacement in regions.items():
            value = replacement(sel) if callable(replacement) else replacement
            text = _replace_template_region(text, name, subst(value), rel)
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


# Mid-sentence mentions of an optional piece, in docs and skills a marker
# cannot cut cleanly: (feature that must be ABSENT, file, old, new). Each anchor
# is require_replace'd, so a template edit that moves one fails loudly.
CONDITIONAL_EDITS: list[tuple[str, str, str, str]] = [
    ("local-dev", ".agents/skills/author-ldp-artifact/SKILL.md",
     "   (or `make validate-connect` against a live cluster) — check valid rows,",
     "   — check valid rows,"),
    ("schemas", ".agents/skills/author-ldp-artifact/SKILL.md",
     'listed under "Source and target kinds" below (CI checks this list against the\n'
     "vendored schema: `make check-framework-surface`).",
     'listed under "Source and target kinds" below.'),
    ("pr-template", "docs/GETTING_STARTED.md",
     'gh pr create --title "Add finance domain" --body-file /tmp/pr-body.md',
     'gh pr create --title "Add finance domain" --fill'),
    ("pr-template", "docs/GETTING_STARTED.md",
     "PR template is enforced (`.github/pull_request_template.md`); CI runs the\nsame",
     "CI runs the same"),
    ("schemas", "docs/ADOPTING.md",
     "`uv sync --frozen` and fails on drift), regenerates the vendored `schemas/*.json`\n"
     "from the newly pinned models (`make sync-schemas`), and asserts the lockstep",
     "`uv sync --frozen` and fails on drift), and asserts the lockstep"),
    ("schemas", "docs/CICD.md", " + `uv.lock` + regenerated `schemas/` + re-pinned", " + `uv.lock` + re-pinned"),
    ("agent-claude", "docs/CICD.md",
     "| document the new kind in the skill, `make sync-skills` |", "| document the new kind in the skill |"),
]


def conditional_edits(out: Path, sel: Selection) -> None:
    for feature, rel, old, new in CONDITIONAL_EDITS:
        path = out / rel
        if sel.has(feature) or not path.exists():
            continue
        path.write_text(require_replace(path.read_text(encoding="utf-8"), old, new, rel),
                        encoding="utf-8")


def narrow_mcp_docs(out: Path, sel: Selection) -> None:
    """The MCP guide and skill are written for Claude Code AND Cursor. With only
    one of them chosen, name only its config file and tool."""
    claude, cursor = sel.has("agent-claude"), sel.has("agent-cursor")
    edits: dict[str, list[tuple[str, str]]] = {"docs/AGENT_MCP.md": [], ".agents/skills/query-databricks/SKILL.md": []}
    if not claude:
        edits["docs/AGENT_MCP.md"].append((
            "| `.agents/skills/query-databricks/SKILL.md` (canonical; generated copy in "
            "`.claude/skills/` via `make sync-skills`) |",
            "| `.agents/skills/query-databricks/SKILL.md` |",
        ))
    if claude != cursor:
        tool, cfg = ("Claude Code", "`.mcp.json`") if claude else ("Cursor", "`.cursor/mcp.json`")
        edits["docs/AGENT_MCP.md"] += [
            ("Let Claude Code / Cursor run **read-only** SQL", f"Let {tool} run **read-only** SQL"),
            ("Claude Code / Cursor ──stdio──▶", f"{tool} ──stdio──▶"),
            ("and point `.mcp.json` / `.cursor/mcp.json` `command`/`args` at it",
             f"and point {cfg} `command`/`args` at it"),
            ("Delete `.mcp.json`, `.cursor/mcp.json`, the two `query-databricks/SKILL.md`\nfiles,",
             "Delete `.mcp.json`, the two `query-databricks/SKILL.md`\nfiles," if claude else
             "Delete `.cursor/mcp.json`, the `query-databricks/SKILL.md`\nfile,"),
        ]
        if cursor:
            edits["docs/AGENT_MCP.md"] += [
                ("— `.mcp.json` is excluded from\nthe deployed bundle via `.databricksignore`",
                 "— `.cursor/` is excluded from\nthe deployed bundle via `.databricksignore`"),
                ("block in `.mcp.json`, rename it,", "block in `.cursor/mcp.json`, rename it,"),
            ]
        edits[".agents/skills/query-databricks/SKILL.md"].append(
            ("(configured in `.mcp.json` / `.cursor/mcp.json`)", f"(configured in {cfg})")
        )
    for rel, pairs in edits.items():
        path = out / rel
        if not path.exists() or not pairs:
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in pairs:
            text = require_replace(text, old, new, rel)
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


def patch_cursor_rules(out: Path, catalog: str, sel: Selection) -> None:
    """.cursor/rules/project.mdc is auto-attached context for every Cursor edit,
    so it must describe the adopter's root-level layout, not projects/ — and
    only the guards this adopter actually has."""
    path = out / ".cursor" / "rules" / "project.mdc"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    guards = (["`.claude/hooks/protected_files_guard.py`"] if sel.has("agent-claude|agent-codex") else []) + (
        ["`.githooks/pre-commit`"] if sel.has("githooks") else []
    )
    protected = (
        f"- Production-sensitive files are protected by {_join(guards)}. Keep "
        f"{'both' if len(guards) == 2 else 'it'} + the AGENTS.md \"Protected file surface\" "
        "table in sync when you change the set."
        if guards else
        '- Production-sensitive files are listed in AGENTS.md\'s "Protected file surface" '
        "table — keep it current when you change the set."
    )
    text = require_replace(
        text,
        "- Production-sensitive files are protected by\n"
        "  `.claude/hooks/protected_files_guard.py` and `.githooks/pre-commit`. Keep\n"
        "  both + the AGENTS.md \"Protected file surface\" table in sync when you change\n"
        "  the set.",
        _wrap(protected, "  "),
        ".cursor/rules/project.mdc",
    )
    if not sel.has("githooks"):
        text = require_replace(
            text,
            "commit/push-to-main are denied on `main`) and `.githooks/pre-commit`.",
            "commit/push-to-main are denied on `main`).",
            ".cursor/rules/project.mdc",
        )
    if not sel.has("pr-template"):
        text, n = re.subn(r"\n- \*\*One PR format for everything\.\*\*.*?CI re-checks every PR body\.",
                          "", text, count=1, flags=re.S)
        if not n:
            raise SystemExit("scaffold: PR-format bullet not found in .cursor/rules/project.mdc")
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
    "maintain-design-diagram/SKILL.md": [
        # The adopter's OVERVIEW.md draws its architecture in mermaid and links
        # the diagrams; it does not embed the PNGs the template's overview does.
        (
            "| EDIT: customer-facing narrative that embeds the images. Refresh when the story changes. |",
            "| EDIT: customer-facing narrative (a mermaid architecture view that links the diagrams). "
            "Refresh when the story changes. |",
        ),
        (
            "`design/OVERVIEW.md` (it embeds `images/01_*` and `images/02_*`, so the\n"
            "regenerated images flow through automatically). A structural change the",
            "`design/OVERVIEW.md`. A structural change the",
        ),
    ],
    "deploy-databricks-bundle/SKILL.md": [
        (
            "make run               # databricks bundle run customer_sales_etl -t dev (refresh)",
            "make run               # databricks bundle run @@CATALOG@@_etl -t dev (refresh)",
        ),
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
    """Edit the CANONICAL skills only; mirror_claude_skills() regenerates the
    .claude/skills copy from them afterwards (byte-identical, so the adopter's
    `make check-skills` passes by construction)."""
    for rel, edits in SKILL_EDITS.items():
        path = out / ".agents" / "skills" / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for old, new in edits:
            text = require_replace(text, subst(old), subst(new), f".agents/skills/{rel}")
        path.write_text(text, encoding="utf-8")


def mirror_claude_skills(out: Path) -> None:
    """The adopter's .claude/skills = an exact copy of its (pruned, patched)
    .agents/skills — same contract as scripts/sync_skills.py --write."""
    mirror, canonical = out / ".claude" / "skills", out / ".agents" / "skills"
    if not mirror.exists():
        return
    shutil.rmtree(mirror)
    if canonical.exists():
        shutil.copytree(canonical, mirror)


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
> [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/@@FRAMEWORK_TAG@@/docs/FRAMEWORK.md);
> first-deploy checklist: [`docs/NEW_ADOPTER.md`](docs/NEW_ADOPTER.md).
"""

# A repo generated without coding agents still cites skills by name (the
# authoring recipes live there) — say where they are rather than implying
# they are local.
ADOPTER_NO_AGENTS_NOTE = """\

> **No coding-agent harness here.** This repo was generated without one, so the
> agent skills this file cites by name (`author-ldp-artifact`,
> `author-sdp-pipeline`, `deploy-databricks-bundle`, …) live in the datalab
> template repo's `.agents/skills/` — they double as step-by-step guides for
> humans.
"""

ADOPTER_OVERVIEW_DOMAINS = """\
- **Single-domain adopter layout**: the domain lives at the repo ROOT —
  `config/@@CATALOG@@/` (one YAML artifact per table), `src/@@CATALOG@@_etl/`
  (the domain package), `resources/*.yml` (bundle resources). Complete worked
  examples of every framework feature (edge jobs, notebooks, AUTO CDC
  SCD1/SCD2, snapshot CDC, config templates, ABAC SQL) live in the datalab
  template repo under `projects/`.
"""

ADOPTER_COMMON_TASK_NEW_DOMAIN = """\
- **Add a second domain**: an adopter repo is deliberately SINGLE-domain
  (root-level layout). For another domain or customer, stand up a separate
  adopter repo (`docs/NEW_ADOPTER.md`); if you truly need several domains in
  one repo, follow the multi-domain layout of the datalab
  template repo (`projects/` + uv-workspace members) rather than grafting on.
"""

ADOPTER_COMMON_TASK_NEW_ADOPTER = """\
- **Stand up another customer repo**: not from here — this repo is already an
  adopter, and the configurator refuses to run in one. Use the datalab template
  repo (`make configure-adopter` in a fresh clone generated from it, or
  `make new-adopter` from a checkout of it); this repo's own answers are in
  `.datalab-adopter.json` if you want the same shape (`ANSWERS=`).
"""


def _join(items: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _wrap(text: str, indent: str, first: str = "") -> str:
    """Re-flow one bullet/step paragraph to ~80 columns under `indent` (the first
    line prefixed with `first`), never breaking inside a `code span`."""
    import textwrap

    glued = re.sub(r"`[^`]*`", lambda m: m.group(0).replace(" ", "\0"), text)
    wrapped = textwrap.fill(glued, width=80, initial_indent=first, subsequent_indent=indent,
                            break_on_hyphens=False, break_long_words=False)
    return wrapped.replace("\0", " ")


def adopter_architecture(sel: Selection) -> str:
    extras = [
        label
        for label, feature in (("framework-bump.yml (bot)", "framework-bot"), ("dependabot", "dependabot"))
        if sel.has(feature)
    ]
    lines = [
        "```",
        "Developer ──push/PR──▶ GitHub Actions ──OIDC──▶ Declarative Automation Bundle",
        "                       ci-cd.yml (ONE workflow;   (databricks.yml + resources/*.yml)",
        "                       target derived from the             │ deploys",
        "                       trigger) → common-ci / common-cd    ▼",
    ]
    if extras:
        lines.append("                       + " + " + ".join(extras))
    lines += [
        "                  ┌──────── Lakeflow SDP pipeline: @@CATALOG@@_etl ─────────┐",
        "landing volume ─▶ │ bronze.events_raw ─▶ silver / gold: add tables with the │",
        "(Auto Loader)     │ author-ldp-artifact skill (dqx quarantine per table)    │",
        "                  └─────────────────────────────────────────────────────────┘",
        "                  refreshed daily by job @@CATALOG@@_etl_refresh (paused in dev)",
        "```",
    ]
    return "\n".join(lines) + "\n"


def adopter_codebase_layout(sel: Selection) -> str:
    rows: list[tuple[str, str]] = [
        ("databricks.yml", "Bundle: name + include only (variables/ + targets/ + rbac + resources merged in)"),
        ("variables/", "Variable declarations + defaults (medallion catalog/schemas/paths)"),
        ("targets/", "One file per environment (dev/stage/prod): mode, host, per-env variable values"),
        ("rbac.yml", "Workspace-resource RBAC: groups + permission levels + per-target overrides"),
        ("config/@@CATALOG@@/", "domain.yml + ONE <schema>/<table>.yml artifact per target table"),
        ("src/@@CATALOG@@_etl/", "Domain package: pipeline entrypoint, @transform fns, custom dqx checks"),
        ("resources/", "This domain's bundle resources (pipeline + refresh job)"),
        ("tests/", "The domain's unit tests (make test)"),
    ]
    if sel.has("local-dev"):
        rows.append(("sample_data/", "Local sample landing files for `make run-local`"))
    rows.append(("scripts/", "bootstrap_uc · publish_wheel · domain registry · repo checks (scripts/README.md)"))
    if sel.has("schemas"):
        rows.append(("schemas/", "GENERATED editor schemas from the pinned framework (make sync-schemas)"))
    if sel.has("docs"):
        guides = ["NEW_ADOPTER (first-deploy checklist)", "ADOPTING", "GETTING_STARTED", "NAMING",
                  "CICD", "ARCHITECTURE"] + (["AGENT_MCP"] if sel.has("mcp") else [])
        rows.append(("docs/", " · ".join(guides)))
    if sel.has("design"):
        rows.append(("design/", "OVERVIEW · estate.yml overlay · *.drawio + images + PIPELINES.md (all GENERATED by make design)"))
    github = "CI/CD workflows (OIDC deploy; framework App token)"
    github += "".join(
        f" + {label}"
        for label, feature in (("PR template", "pr-template"), ("dependabot", "dependabot"),
                               ("framework-bump bot", "framework-bot"))
        if sel.has(feature)
    )
    rows.append((".github/", github))
    if sel.has("any-agent"):
        where = "read natively by Cursor + Codex"
        if sel.has("agent-genie"):
            where += "; make publish-genie-skills pushes them to Genie Code"
        rows.append((".agents/skills/", f"Agent skills, authored ONCE here ({where})"))
    if sel.has("agent-claude"):
        rows.append((".claude/ + CLAUDE.md", "Claude Code: settings, guard hook, GENERATED skills copy (make sync-skills)"))
    elif sel.has("agent-codex"):
        rows.append((".claude/hooks/", "The protected-files guard the Codex hooks run"))
    if sel.has("agent-codex"):
        rows.append((".codex/", "Codex hooks (run the shared guard scripts)"))
    if sel.has("agent-cursor"):
        rows.append((".cursor/", "Cursor rules + hooks; hooks/*.py are the branch/PR guards every agent runs"))
    elif sel.has("hooked-agent"):
        rows.append((".cursor/hooks/", "The shared branch/PR guard scripts the agent hooks run"))
    if sel.has("githooks"):
        rows.append((".githooks/", "Human pre-commit guard (make enable-githooks)"))
    if sel.has("mcp&agent-claude"):
        rows.append((".mcp.json", "Opt-in read-only Databricks MCP grounding"))
    rows += [
        ("Makefile", "Developer + CI entrypoints (run `make help`)"),
        ("pyproject.toml, uv.lock", "Single-package project (uv end to end; CI runs --frozen)"),
        (MANIFEST, "How this repo was generated: the configurator's recorded answers"),
    ]
    body = "\n".join(f"{path:<26}{what}" for path, what in rows)
    return (
        f"```\n{body}\n```\n\n"
        "The folder ↔ UC namespace naming contract is `docs/NAMING.md`. The multi-domain\n"
        "reference layout lives in the datalab template repo (`projects/`).\n"
    )


def adopter_maintenance_design(sel: Selection) -> str:
    if sel.has("design"):
        text = (
            "2. If the architecture moved or a table was added or changed, update the "
            "`design/` package in the same PR: `make design` re-renders "
            "`design/PIPELINES.md` from `config/` (CI's `make check-design` fails "
            "while it is stale) and regenerates the diagrams from the estate - never "
            "edit `design/*.drawio`; declare source systems, consumers and edge-job "
            "reads/writes in `design/estate.yml`, look at `make design-preview`, and "
            "refresh `design/OVERVIEW.md` when the narrative changed"
            + (" - follow the `maintain-design-diagram` skill (and "
               "`drawio-architecture-designer` for any generator/layout change)"
               if sel.has("any-agent") else "")
            + (". Update `docs/ARCHITECTURE.md` too." if sel.has("docs") else ".")
        )
    elif sel.has("docs"):
        text = "2. If the architecture moved, update `docs/ARCHITECTURE.md` in the same PR."
    else:
        text = '2. If the architecture moved, update the "Architecture" section above in the same PR.'
    return _wrap(text, "   ") + "\n"


def adopter_common_task_design(sel: Selection) -> str:
    if not sel.has("design"):
        return ""
    text = (
        "- **Update the design (inventory, diagrams, overview)**: after adding or "
        "changing a table, `make design` re-renders `design/PIPELINES.md` from "
        "`config/`, regenerates `design/*.drawio` from the estate and exports "
        "`design/images/` (CI's `make check-design` fails while any of it is stale, "
        "hand-edited or fails the layout audit). Never edit a `.drawio` file: "
        "declare source systems, consumers and edge-job reads/writes in "
        "`design/estate.yml`, change the spec text in `scripts/design_spec.py`, "
        "look at `make design-preview`, and refresh `design/OVERVIEW.md` when "
        "the narrative changes"
        + (" - follow the `maintain-design-diagram` skill, and the "
           "`drawio-architecture-designer` skill for any generator/layout change"
           if sel.has("any-agent") else "")
        + ". `design/` is excluded from the deployed workspace files via "
        "`sync.exclude` in databricks.yml."
    )
    return _wrap(text, "  ") + "\n"


def adopter_framework_mandate(sel: Selection) -> str:
    """The template's "Framework bumps are mandatory" gotcha as it applies to an
    adopter: the same gates in WARN mode (check_framework_current.mode), and
    only the bot / schemas / skill clauses this repo carries."""
    bot, schemas, skill = sel.has("framework-bot"), sel.has("schemas"), sel.has("any-agent")
    clauses = ["re-pins the framework-doc links (`check-lockstep`)"]
    if schemas:
        clauses.append("regenerates `schemas/` (`check-schemas`)")
    if skill:
        clauses.append("must teach the `author-ldp-artifact` skill every new target/source kind"
                       + (" (`check-framework-surface`)" if schemas else ""))
    clauses.append("must migrate anything the framework CHANGELOG flags **BREAKING**")
    text = (
        "- **Framework bumps: adopt each release, with its corresponding changes.** "
        "`make check-framework-current` (its own CI job) flags every PR and main while "
        "a newer published datalab-framework `vX.Y.Z` exists than the pin — a warning "
        "in this repo; set the repo/org variable `DATALAB_FRAMEWORK_MANDATE=enforce` to "
        "make it fail (the datalab template repo runs it enforced)."
        + (" The `framework-bump.yml` bot (twice daily, or on demand) opens the bump PR; "
           "merge it." if bot else " Bump with `make bump-framework VERSION=x.y.z`.")
        + f" A bump is not just the pin: it {_join(clauses)}."
        + (" When a gate fails on the new version the bot opens the PR as a DRAFT listing "
           "the failing gates and the framework CHANGELOG between the pins — push the "
           "corresponding changes to that branch, then mark it ready. The bot needs "
           'Settings → Actions → General → "Allow GitHub Actions to create and approve '
           'pull requests" ON (otherwise it files a `framework-bump` issue with a '
           "one-click compare link)." if bot else "")
        + (' Details: `docs/CICD.md` "Framework bumps".' if sel.has("docs") else "")
    )
    return _wrap(text, "  ") + "\n"


def agents_md_selection_rewrites(sel: Selection, catalog: str) -> list[tuple[str, str]]:
    """Sentences that ENUMERATE optional pieces (harness configs, guards, the
    schema vendoring, the bump bot), rewritten to name only what this adopter
    has. Whole optional passages are fenced with `adopter-if` markers instead;
    these are the ones a marker cannot cut cleanly (mid-sentence lists)."""
    rewrites: list[tuple[str, str]] = []
    tools = [name for agent, name in (("claude", "Claude Code"), ("codex", "Codex"),
                                      ("cursor", "Cursor"), ("genie", "Genie Code"))
             if agent in sel.agents]
    rewrites.append((
        "# AGENTS.md — datalab\n\n"
        "Shared source of truth for AI coding agents (Cursor, Claude Code, Codex) and humans.",
        f"# AGENTS.md — {catalog}-datalab\n\n"
        + (f"Shared source of truth for AI coding agents ({_join(tools)}) and humans."
           if tools else "Shared source of truth for humans and AI coding agents alike."),
    ))
    configs = [cfg for agent, cfg in (("claude", "`.claude/settings.json`"),
                                      ("cursor", "`.cursor/hooks.json`"),
                                      ("codex", "`.codex/hooks.json`")) if agent in sel.agents]

    # Branching & releases — what enforces branch-first here.
    enforced = []
    if configs:
        enforced.append(
            "`.cursor/hooks/branch_guard.py` denies file edits and `git commit`/"
            f"`git push`-to-main in the agent harness{'es' if len(configs) > 1 else ''} "
            f"(wired in {_join(configs)})"
        )
    if sel.has("githooks"):
        enforced.append("`.githooks/pre-commit` blocks human commits on `main`")
    branch = (
        "This is ENFORCED, not just convention: " + ", and ".join(enforced) + ". If a guard "
        "blocks you mid-task: create the branch (uncommitted edits carry over) and retry."
        if enforced else
        "Nothing in this repo enforces it locally (no agent or git hooks were "
        "generated) — protect `main` with a GitHub branch-protection rule."
    )
    rewrites.append((
        "  and never stack new work on a previous feature branch. This is ENFORCED,\n"
        "  not just convention: `.cursor/hooks/branch_guard.py` denies file edits and\n"
        "  `git commit`/`git push`-to-main in all three agent harnesses (wired in\n"
        "  `.cursor/hooks.json`, `.claude/settings.json` and `.codex/hooks.json`), and\n"
        "  `.githooks/pre-commit` blocks human commits on `main`. If a guard blocks\n"
        "  you mid-task: create the branch (uncommitted edits carry over) and retry.",
        "  and never stack new work on a previous feature branch.\n" + _wrap(branch, "  ", "  "),
    ))
    enforcers = (["`.cursor/hooks/branch_guard.py` (agents)"] if configs else []) + (
        ["`.githooks/pre-commit` (humans)"] if sel.has("githooks") else []
    )
    if enforcers:
        rewrites.append((
            "Separate from the protected-file surface, `.cursor/hooks/branch_guard.py`\n"
            "(agents, all three harnesses) and the same `.githooks/pre-commit` (humans) enforce\n"
            "the branch-first policy — no edits/commits/pushes while `main` is checked out\n"
            '(see "Branching & releases").',
            _wrap(
                f"Separate from the protected-file surface, {_join(enforcers)} "
                f"enforce{'s' if len(enforcers) == 1 else ''} the branch-first policy — "
                'no edits/commits/pushes while `main` is checked out (see "Branching & releases").',
                "",
            ),
        ))
    dont = {
        (True, True): "(enforced by `branch_guard` + the pre-commit hook).",
        (True, False): "(enforced by `branch_guard`).",
        (False, True): "(enforced by the pre-commit hook).",
    }.get((bool(configs), sel.has("githooks")))
    rewrites.append((
        "from a fresh `main`\n  (enforced by `branch_guard` + the pre-commit hook).",
        f"from a fresh `main`\n  {dont}" if dont else "from a fresh `main`.",
    ))

    # Maintenance protocol step 4 — where the protected set lives.
    places = (["`.claude/hooks/protected_files_guard.py`"] if sel.has("agent-claude|agent-codex") else []) + (
        ["`.githooks/pre-commit`"] if sel.has("githooks") else []
    ) + ["the table below"]
    step4 = (
        "4. If you change the protected set itself, update the table below."
        if len(places) == 1 else
        "4. If you change the protected set itself, update "
        f"**all {'two' if len(places) == 2 else 'three'}** in one commit: {_join(places)}."
    )
    rewrites.append((
        "4. If you change the protected set itself, update **all three** in one commit:\n"
        "   `.claude/hooks/protected_files_guard.py`, `.githooks/pre-commit`, and the\n"
        "   table below.",
        _wrap(step4, "   "),
    ))

    # Framework upgrades — schema vendoring, the authoring skill and the bump bot
    # are optional, and the adoption gate runs in WARN mode outside the template.
    schemas, bot, skill = sel.has("schemas"), sel.has("framework-bot"), sel.has("any-agent")
    warn_mode = "a warning here unless `DATALAB_FRAMEWORK_MANDATE=enforce`"
    rewrites.append((
        "that rewrites both, re-pins the framework-doc links, re-locks, regenerates the\n"
        "  vendored `schemas/` and asserts the lockstep; CI enforces the agreement\n"
        "  (`make check-lockstep` + `make check-schemas`), and the `framework-bump.yml`\n"
        "  workflow opens this bump as a bot PR when the framework releases a new tag.\n"
        "  **Adopting every framework release is MANDATORY** — `make\n"
        "  check-framework-current` fails CI on every PR and on main while a newer\n"
        '  release exists (see "Framework bumps are mandatory" below). Then',
        _wrap(
            "that rewrites both, "
            + _join(["re-pins the framework-doc links", "re-locks",
                     *(["regenerates the vendored `schemas/`"] if schemas else []),
                     "asserts the lockstep"])
            + "; CI enforces the agreement (`make check-lockstep`"
            + (" + `make check-schemas`" if schemas else "") + ")"
            + (", and the `framework-bump.yml` workflow opens this bump as a bot PR when "
               "the framework releases a new tag" if bot else "")
            + ". `make check-framework-current` flags a newer framework release on every "
            f'PR and on main ({warn_mode} — see "Framework bumps" below). Then',
            "  ",
        ),
    ))
    rewrites.append((
        "run `make bump-framework VERSION=x.y.z` — it rewrites the `datalab` git tag\n"
        "   in `pyproject.toml` + `var.datalab_version` in lockstep, re-locks, and\n"
        "   REGENERATES `schemas/*.json` from the newly pinned models\n"
        "   (`make sync-schemas` — never hand-copy them; `make check-schemas` +\n"
        "   `make check-lockstep` gate CI). Then add the release's corresponding changes\n"
        "   (new kinds in the `author-ldp-artifact` skill — `make\n"
        "   check-framework-surface`; migrations for BREAKING entries), `make\n"
        "   publish-wheel APPLY=1` and record the bump in `CHANGELOG.md`. The\n"
        "   `framework-bump.yml` workflow opens this bump as a bot PR automatically on\n"
        "   new framework release tags, and adopting it is mandatory (`make\n"
        "   check-framework-current` fails CI while the pin is behind).",
        _wrap(
            "run `make bump-framework VERSION=x.y.z` — it rewrites the `datalab` git tag "
            "in `pyproject.toml` + `var.datalab_version` in lockstep, re-locks"
            + (", and REGENERATES `schemas/*.json` from the newly pinned models "
               "(`make sync-schemas` — never hand-copy them; `make check-schemas` + "
               "`make check-lockstep` gate CI)" if schemas else
               " (`make check-lockstep` gates CI)")
            + ". Then add the release's corresponding changes ("
            + ("new kinds in the `author-ldp-artifact` skill"
               + (" — `make check-framework-surface`" if schemas else "") + "; " if skill else "")
            + "migrations for BREAKING entries), `make publish-wheel APPLY=1` and record "
            "the bump in `CHANGELOG.md`."
            + (" The `framework-bump.yml` workflow opens this bump as a bot PR "
               "automatically on new framework release tags." if bot else "")
            + f" `make check-framework-current` flags a pin that is behind ({warn_mode}).",
            "   ",
        ),
    ))
    if not bot:
        rewrites.append((
            "stale framework pin — see `.github/workflows/framework-bump.yml`.",
            "stale framework pin in the datalab template repo (its bump-bot workflow).",
        ))

    # Claude's tracked-settings gotcha (kept only with Claude Code).
    one = len(configs) <= 1
    rewrites.append((
        "  `.claude/settings.json`, `.cursor/hooks.json` and `.codex/hooks.json` are\n"
        "  TRACKED — every developer gets them, and the scaffold copies them into every\n"
        "  adopter repo. So the tracked files carry only what means the same thing on any\n",
        _wrap(
            f"{_join(configs) if configs else '`.claude/settings.json`'} "
            f"{'is' if one else 'are'} TRACKED — every developer gets {'it' if one else 'them'}. "
            f"So the tracked {'file carries' if one else 'files carry'} only what means the "
            "same thing on any",
            "  ", "  ",
        ) + "\n",
    ))
    rewrites.append((
        "Anything personal or that WRITES — commits, `make new-adopter`, deploys, a",
        "Anything personal or that WRITES — commits, deploys, a",
    ))

    # MCP grounding — which harness configs carry it.
    mcp_files = [f for agent, f in (("claude", "`.mcp.json`"), ("cursor", "`.cursor/mcp.json`")) if agent in sel.agents]
    mcp_tools = [t for agent, t in (("claude", "Claude Code"), ("cursor", "Cursor")) if agent in sel.agents]
    if len(mcp_files) == 1:
        rewrites.append((
            "`.mcp.json` / `.cursor/mcp.json` wire Claude Code / Cursor to the workspace's",
            f"{mcp_files[0]} wires {mcp_tools[0]} to the workspace's",
        ))
        rewrites.append((
            "then in\n"
            "  Claude Code approve the `databricks-sql` server from `.mcp.json` (Cursor:\n"
            "  enable it under Settings → MCP).",
            "then in\n  Claude Code approve the `databricks-sql` server from `.mcp.json`."
            if "claude" in sel.agents else
            "then in\n  Cursor enable the `databricks-sql` server from `.cursor/mcp.json`\n"
            "  under Settings → MCP.",
        ))

    if not sel.has("local-dev"):
        rewrites.append((
            "verify behavior with `run_dataset` or\n  `make validate-connect`.",
            "verify behavior with `run_dataset`.",
        ))
    if not sel.has("docs"):
        rewrites.append((
            "then `make validate` before pushing; update `docs/` if\n  targets or variables moved.",
            "then `make validate` before pushing.",
        ))
        rewrites.append((
            "   session: the reproducible commands go in the matching runbook under\n"
            "   `docs/` (CI/CD + GitHub auth → `docs/CICD.md`; UC/data access →\n"
            "   `docs/ARCHITECTURE.md`; adopter setup → `docs/NEW_ADOPTER.md` /\n"
            "   `docs/ADOPTING.md`), and the why + failure signature goes in \"Critical\n"
            "   knowledge\" here.",
            "   session: the reproducible commands and the why + failure signature go in\n"
            "   \"Critical knowledge\" here (this repo was generated without the docs\n"
            "   guides, so this file is the runbook).",
        ))

    # Template history / second-domain examples that read as facts about THIS repo.
    rewrites += [
        ("(`customer_sales`; stage/prod append", f"(`{catalog}`; stage/prod append"),
        (
            "a renamed pipeline resource (e.g.\n  `sales_etl` → `customer_sales_etl`) self-heals",
            "a renamed pipeline resource\n  self-heals",
        ),
        (
            "The\n  export entry point fails fast if `/Volumes/<catalog>/exports/sales/` is\n"
            "  missing rather than silently creating dev-shaped paths elsewhere.",
            "An\n  export entry point must fail fast if `/Volumes/<catalog>/exports/<volume>/` is\n"
            "  missing rather than silently creating dev-shaped paths elsewhere.",
        ),
        (
            "  the scaffold smoke test now asserts the contract end to end.",
            "  the datalab template repo's scaffold smoke test asserts the contract end to end.",
        ),
        (
            "  The edge-job resources (`projects/customer_sales/resources/customer_sales_*.job.yml`) install\n"
            "  the framework wheel from the customer_sales catalog's artifacts.wheels Volume (`${var.datalab_wheel}`)\n"
            "  plus the `customer_sales_etl` wheel (`../../../dist/customer_sales_etl-*.whl`) into",
            "  Edge-job resources (none yet here; for the shape see the datalab\n"
            "  template repo's `projects/customer_sales/resources/customer_sales_*.job.yml`) install\n"
            "  the framework wheel from this catalog's artifacts.wheels Volume (`${var.datalab_wheel}`)\n"
            "  plus this domain's wheel (`../dist/<catalog>_etl-*.whl`) into",
        ),
        (
            "copy the\n  `customer_sales_quarantine_report` job shape (no trigger).",
            "copy the\n  template repo's `customer_sales_quarantine_report` job shape (no trigger).",
        ),
    ]
    return rewrites


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


def patch_agents_md(out: Path, catalog: str, subst, sel: Selection) -> None:
    path = out / "AGENTS.md"
    text = path.read_text(encoding="utf-8")

    intro = ADOPTER_REPO_INTRO + ("" if sel.has("any-agent") else ADOPTER_NO_AGENTS_NOTE)
    for name, replacement in (
        ("repo-intro", intro),
        ("overview-domains", ADOPTER_OVERVIEW_DOMAINS),
        ("architecture", adopter_architecture(sel)),
        ("codebase-layout", adopter_codebase_layout(sel)),
        ("maintenance-design", adopter_maintenance_design(sel)),
        ("common-task-new-adopter", ADOPTER_COMMON_TASK_NEW_ADOPTER),
        ("common-task-new-domain", ADOPTER_COMMON_TASK_NEW_DOMAIN),
        ("common-task-design", adopter_common_task_design(sel)),
        ("framework-mandate", adopter_framework_mandate(sel)),
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
        *agents_md_selection_rewrites(sel, catalog),
    ):
        text = require_replace(text, old, new, "AGENTS.md")

    # The MCP grounding profile: patch_mcp rewires the JSON, so AGENTS.md must
    # not keep telling the agent to authenticate as the template's profile.
    text = text.replace(TEMPLATE_MCP_PROFILE, subst("@@MCP_PROFILE@@"))
    path.write_text(text, encoding="utf-8")


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


def strip_schema_header(text: str) -> str:
    """Drop the yaml-language-server `$schema` header (and the blank comment line
    after it) — without the `schemas` component there is nothing to point at."""
    return re.sub(r"\A# yaml-language-server: \$schema=\S+\n#\n", "", text)


def write_files(out: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def write_domain(out: Path, ctx: dict[str, str], subst, sel: Selection) -> None:
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
    if sel.has("local-dev"):
        files[f"sample_data/landing/{cat}/events/events.json"] = SAMPLE_EVENTS_JSON
    rendered = {rel: subst(text) for rel, text in files.items()}
    if not sel.has("schemas"):
        for rel in (f"config/{cat}/domain.yml", f"config/{cat}/bronze/events_raw.yml"):
            rendered[rel] = strip_schema_header(rendered[rel])
    write_files(out, rendered)
    # NB: do NOT pre-create empty silver/gold layer dirs — the framework config
    # validator rejects an empty layer dir. The author-ldp-artifact skill creates
    # them when the first silver/gold table is added.


# Directories among the sync-exclude entries (written with a trailing slash in
# .databricksignore, for readability; check_sync_lists normalizes it away).
_EXCLUDE_DIRS = {"tests", "docs", "design", "sample_data", ".github", ".claude", ".cursor",
                 ".codex", ".agents", ".githooks"}


def sync_excludes(sel: Selection) -> list[str]:
    """Dev-only surfaces kept out of the deployed workspace files — ONE list that
    feeds BOTH databricks.yml `sync.exclude` and .databricksignore, and names
    only paths this adopter actually has."""
    entries = ["tests"]
    entries += [p for p, f in (("docs", "docs"), ("design", "design"),
                               ("sample_data", "local-dev")) if sel.has(f)]
    entries.append(".github")
    entries += [p for p, f in ((".claude", "agent-claude|agent-codex"), (".cursor", "hooked-agent"),
                               (".codex", "agent-codex"), (".agents", "any-agent"),
                               (".githooks", "githooks"), (".mcp.json", "mcp&agent-claude"))
                if sel.has(f)]
    return entries + ["Makefile", "uv.lock", ".markdownlint.json", MANIFEST]


def write_repo_level(out: Path, subst, sel: Selection) -> None:
    excludes = sync_excludes(sel)
    files = {
        "databricks.yml": DATABRICKS_YML.replace(
            "@@SYNC_EXCLUDE@@", "\n".join(f"    - {e}" for e in excludes)
        ),
        ".databricksignore": DATABRICKSIGNORE.replace(
            "@@IGNORE_ENTRIES@@",
            "\n".join(f"{e}/" if e in _EXCLUDE_DIRS else e for e in excludes),
        ),
        "pyproject.toml": PYPROJECT_TOML,
        "variables/medallion.yml": VARIABLES_MEDALLION,
        "targets/dev.yml": TARGET_DEV,
        "targets/stage.yml": TARGET_STAGE,
        "targets/prod.yml": TARGET_PROD,
        "README.md": README_MD,
        "CHANGELOG.md": CHANGELOG_MD,
    }
    if sel.has("design"):
        files[".gitattributes"] = GITATTRIBUTES_DESIGN
    write_files(out, {rel: subst(text) for rel, text in files.items()})


# The starter table as the framework loader sees it (only the fields the
# inventory renders). The adopter's `make check-design` re-renders PIPELINES.md
# from the YAML itself, so the smoke test catches any drift from BRONZE_YML.
STARTER_TABLE_SPEC = {
    "name": "events_raw",
    "source": {"kind": "cloud_files", "path_conf": "datalab.landing_path", "format": "json"},
    "target": {"kind": "streaming_table"},
}


def write_design(out: Path, ctx: dict[str, str], subst) -> None:
    """The adopter's own design package: overview, the estate.yml overlay and
    the generated pipeline inventory. The two diagrams are GENERATED last, by
    write_design_diagrams(), once every other file is final."""
    cat = ctx["@@CATALOG@@"]
    import design_inventory as inventory  # same dir; pure render(), no pyyaml needed

    domain = inventory.Domain(name=cat, config_dir=f"config/{cat}", layers=["bronze"])
    inventory.analyze(domain, [("bronze", STARTER_TABLE_SPEC, f"config/{cat}/bronze/events_raw.yml")])
    write_files(out, {
        "design/OVERVIEW.md": subst(DESIGN_OVERVIEW_MD),
        "design/estate.yml": subst(DESIGN_ESTATE_YML),
        "design/PIPELINES.md": inventory.render([domain]),
    })


def patch_design_spec(out: Path, subst) -> None:
    """Repoint the conceptual spec's worked-example lines at this adopter, in the
    adopter's copy of scripts/design_spec.py (its `make design` rebuilds 01_*)."""
    path = out / "scripts" / "design_spec.py"
    text = path.read_text(encoding="utf-8")
    for old, new in DESIGN_SPEC_EDITS:
        text = require_replace(text, old, subst(new), "scripts/design_spec.py")
    path.write_text(text, encoding="utf-8")


def starter_estate(out: Path, cat: str):
    """The estate the scaffold just wrote, WITHOUT parsing YAML (this script is
    stdlib-only): one bronze table, one pipeline, its daily refresh job, an empty
    overlay. It must equal what design_diagram.discover() reads back from the
    generated repo - the adopter's first `make check-design` (CI smoke) proves it,
    and scripts/tests pins it."""
    import design_diagram as dd
    import design_inventory as inventory

    domain = inventory.Domain(name=cat, config_dir=f"config/{cat}", layers=["bronze"])
    inventory.analyze(domain, [("bronze", STARTER_TABLE_SPEC, f"config/{cat}/bronze/events_raw.yml")])
    pipe = dd.Pipeline(key=f"{cat}_etl", file=f"resources/{cat}_etl.pipeline.yml",
                       config_dir=f"config/{cat}", serverless=True, catalog="${var.catalog}")
    job = dd.Job(key=f"{cat}_etl_refresh", file=f"resources/{cat}_etl.job.yml",
                 tasks=[dd.Task(f"refresh_{cat}_etl", "pipeline", f"{cat}_etl")],
                 trigger="every day", alerts=False)
    title = re.search(r"^bundle:\s*\n\s+name:\s*(\S+)",
                      (out / "databricks.yml").read_text(encoding="utf-8"), re.M)
    return dd.Estate(title=title.group(1) if title else out.name, domains=[domain],
                     pipelines={pipe.key: pipe}, jobs={job.key: job}, overlay={},
                     delivery=dd.discover_delivery(out))


def write_design_diagrams(out: Path, cat: str) -> None:
    """Generate design/*.drawio for the finished adopter through the vendored
    drawio-architecture-designer kit - the same generator its `make design` runs,
    so the files are current and audit-clean from the first commit."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import importlib.util

    import design_diagram as dd

    try:
        import yaml  # noqa: F401  - when present, read the repo back exactly
        estate = None
    except ImportError:
        estate = starter_estate(out, cat)
    # the ADOPTER's design_spec.py (patched by patch_design_spec), not this repo's
    spec = importlib.util.spec_from_file_location("design_spec", out / "scripts" / "design_spec.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = sys.modules.get("design_spec")
    sys.modules["design_spec"] = module
    try:
        files, problems = dd.render_files(out, estate=estate)
    finally:
        if saved is not None:
            sys.modules["design_spec"] = saved
        else:
            sys.modules.pop("design_spec", None)
    if problems:
        raise SystemExit("scaffold: the generated design diagrams fail the layout audit:\n  "
                         + "\n  ".join(problems))
    write_files(out, {rel.as_posix(): text for rel, text in files.items()})


# --------------------------------------------------------------------------- #
# Feature markers — `adopter-if:<expr>` regions in the shared template files
# --------------------------------------------------------------------------- #
# Block, markdown:  <!-- adopter-if:<expr> start -->  …  <!-- adopter-if:<expr> end -->
# Block, # files:   # adopter-if:<expr> start         …  # adopter-if:<expr> end
# Line, markdown:   <any line> <!-- adopter-if:<expr> -->   (e.g. one table row)
# In the template they are inert comments (every region is live). In an adopter
# a region survives only when its expression holds; the markers never ship.
# Markdown markers must sit OUTSIDE fenced code blocks (a comment inside a fence
# renders literally) — code-block lines naming a make target the adopter lacks
# are pruned by prune_dead_make_lines instead.

_MD_BLOCK = re.compile(r"^[ \t]*<!--\s*adopter-if:(\S+)\s+(start|end)\s*-->[ \t]*$")
_HASH_BLOCK = re.compile(r"^[ \t]*#\s*adopter-if:(\S+)\s+(start|end)[ \t]*$")
_MD_LINE = re.compile(r"[ \t]*<!--\s*adopter-if:(\S+)\s*-->[ \t]*$")


def apply_markers(text: str, features: set[str], where: str) -> str:
    out: list[str] = []
    stack: list[tuple[str, int, bool]] = []
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        body = line.rstrip("\n")
        block = _MD_BLOCK.match(body) or _HASH_BLOCK.match(body)
        if block:
            expr, edge = block.group(1), block.group(2)
            if edge == "start":
                stack.append((expr, n, evaluate(expr, features, f"{where}:{n}")))
            elif not stack or stack[-1][0] != expr:
                raise SystemExit(f"scaffold: unbalanced `adopter-if:{expr} end` at {where}:{n}")
            else:
                stack.pop()
            continue
        if not all(keep for *_, keep in stack):
            continue
        marker = _MD_LINE.search(body)
        if marker:
            if not evaluate(marker.group(1), features, f"{where}:{n}"):
                continue
            line = body[: marker.start()] + ("\n" if line.endswith("\n") else "")
        out.append(line)
    if stack:
        expr, n, _ = stack[-1]
        raise SystemExit(f"scaffold: `adopter-if:{expr} start` at {where}:{n} is never closed")
    return "".join(out)


def text_files(root: Path):
    """(path, text) for every UTF-8 text file under root (binary files skipped)."""
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue


def process_markers(out: Path, features: set[str]) -> None:
    for path, text in text_files(out):
        if "adopter-if:" in text:
            new = apply_markers(text, features, path.relative_to(out).as_posix())
            if new != text:
                path.write_text(new, encoding="utf-8")


def makefile_targets(out: Path) -> set[str]:
    path = out / "Makefile"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return set(re.findall(r"^([A-Za-z][\w-]*):(?!=)", text, re.M))


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def prune_dead_make_lines(text: str, targets: set[str]) -> str:
    """In fenced code blocks, drop `make <t> …` lines whose targets this adopter
    lacks (a partially-dead line keeps its live targets). HTML-comment markers
    cannot fence lines INSIDE a code block, so command listings — AGENTS.md's
    "Local development" block, the docs' walkthroughs — are pruned here."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        opener = _FENCE.match(line)
        if opener:
            mark = opener.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            out.append(line)
            continue
        command = re.match(r"^(\s*)make\s+(.*)$", line.rstrip("\n")) if fence else None
        if command:
            words = re.split(r"(\s+)", command.group(2))
            head: list[str] = []
            for word in words:
                if word.startswith("#") or word in ("&&", "||", ";", "\\"):
                    break
                head.append(word)
            wanted = [w for w in head if w.strip() and "=" not in w]
            dead = [w for w in wanted if w not in targets]
            if dead and len(dead) == len(wanted):
                continue
            for word in dead:
                line = re.sub(rf"(?<=\s){re.escape(word)}(?=\s|$)\s?", "", line, count=1)
        out.append(line)
    # A fence whose every line was pruned would render as an empty box.
    return re.sub(r"^([ \t]*)(`{3,}|~{3,})[^\n]*\n\1\2[ \t]*\n\n?", "", "".join(out), flags=re.M)


def relink_dropped_docs(out: Path, tracked: list[str], tag: str) -> None:
    """Point references to docs this adopter does NOT carry at the template
    repo's copy (FRAMEWORK.md at the framework repo's reference, at the pinned
    tag), so nothing dangles when `docs` — or the MCP guide — was left out."""
    dropped = sorted(
        rel for rel in tracked
        if rel.startswith("docs/") and rel.endswith(".md") and not (out / rel).exists()
    )
    if not dropped:
        return
    urls = {
        rel: f"https://github.com/dediggibyte/datalab-framework/blob/{tag}/docs/FRAMEWORK.md"
        if rel == "docs/FRAMEWORK.md" else f"{TEMPLATE_URL}/{rel}"
        for rel in dropped
    }
    for path, text in text_files(out):
        rel_file = path.relative_to(out).as_posix()
        markdown = path.suffix in (".md", ".mdc")
        new = text
        for rel, url in urls.items():
            name = rel.removeprefix("docs/")
            esc = re.escape(rel)
            def to_url(m: re.Match, url: str = url) -> str:
                return f"]({url}{m.group(1) or ''})"

            # link targets: ](docs/X.md#a), ](../docs/X.md) — and ](X.md) inside docs/
            new = re.sub(rf"\]\((?:\.\./)?{esc}(#[^)\s]*)?\)", to_url, new)
            if rel_file.startswith("docs/"):
                new = re.sub(rf"\]\({re.escape(name)}(#[^)\s]*)?\)", to_url, new)
            if markdown:
                # a backticked mention that is not already link text becomes a link
                new = re.sub(rf"(?<!\[)`{esc}`(?!\]\()", f"[`{rel}`]({url})", new)
                # ...and so does a plain one (not inside a link, a URL or a code span)
                new = re.sub(rf"(?<![\w/.`\[(-]){esc}(?![\w`\]])", f"[{rel}]({url})", new)
            else:
                new = re.sub(rf"(?<![\w/.`-]){esc}\b", url, new)
        if new != text:
            path.write_text(new, encoding="utf-8")


# Tracked Claude settings carry ONLY read-only verification grants — the policy
# scripts/check_agent_settings.py enforces. They are regenerated from the
# adopter's own Makefile, so a grant for a target it lacks (or a personal /
# write grant that slipped into the template's file) can never ship.
READ_ONLY_TARGET = re.compile(r"^(help|lint|test|validate-configs|dry-run-local|check-[a-z-]+)$")


def _drop_hooks(node, script: str):
    """Remove every hook entry whose command runs `script`; drop matcher groups
    left empty. Works on the Claude, Codex and Cursor hook-config shapes."""
    if isinstance(node, dict):
        return {k: _drop_hooks(v, script) for k, v in node.items()}
    if isinstance(node, list):
        kept = []
        for item in node:
            if isinstance(item, dict) and script in str(item.get("command", "")):
                continue
            item = _drop_hooks(item, script)
            if isinstance(item, dict) and "hooks" in item and not item["hooks"]:
                continue
            kept.append(item)
        return kept
    return node


def rewrite_agent_json(out: Path, sel: Selection, targets: set[str]) -> None:
    order = ["help", "lint", "test", "validate-configs"]
    read_only = order + sorted(t for t in targets if READ_ONLY_TARGET.match(t) and t not in order)
    for rel in (".claude/settings.json", ".codex/hooks.json", ".cursor/hooks.json"):
        path = out / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if rel == ".claude/settings.json":
            data.setdefault("permissions", {})["allow"] = [
                f"Bash(make {t})" for t in read_only if t in targets
            ]
        if not sel.has("pr-template"):
            data = _drop_hooks(data, "pr_template_guard.py")
        if not sel.has("design"):
            data = _drop_hooks(data, "design_drawio_guard.py")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def template_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                              text=True, check=False).stdout.strip()

    sha = git("rev-parse", "--short", "HEAD") or "unknown"
    return sha + ("-dirty" if git("status", "--porcelain", "--untracked-files=no") else "")


def validate_output(out: Path) -> None:
    """Last line of defence before anything touches the destination."""
    for path, text in text_files(out):
        rel = path.relative_to(out).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            if _MD_BLOCK.match(line) or _HASH_BLOCK.match(line) or _MD_LINE.search(line):
                raise SystemExit(f"scaffold: an adopter-if marker survived at {rel}:{n}")
        if path.suffix == ".json" and not rel.startswith("sample_data/"):  # samples are NDJSON
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"scaffold: {rel} is not valid JSON after the conversion: {exc}") from exc
    if shutil.which("make"):
        probe = subprocess.run(["make", "-C", str(out), "-n", "help"], capture_output=True, text=True)
        if probe.returncode:
            raise SystemExit(f"scaffold: the generated Makefile does not parse:\n{probe.stderr}")


# --------------------------------------------------------------------------- #
# Answers — flags, an answers file, and the interactive form
# --------------------------------------------------------------------------- #

@dataclass
class Answers:
    catalog: str
    customer: str
    description: str
    repo: str
    hosts: dict[str, str]
    catalogs: dict[str, str]
    warehouse_id: str
    mcp_profile: str
    deploy_sp: str
    reader_group: str
    engineer_group: str
    admin_group: str
    framework_tag: str
    agents: list[str] = field(default_factory=lambda: list(AGENT_CHOICES))
    components: list[str] = field(default_factory=default_components)

    @property
    def selection(self) -> Selection:
        return Selection(self.agents, self.components)

    def todos(self) -> list[str]:
        values = {
            "dev host": self.hosts["dev"], "stage host": self.hosts["stage"],
            "prod host": self.hosts["prod"], "SQL warehouse id": self.warehouse_id,
            "deploy SP": self.deploy_sp, "GitHub repo (OIDC subject)": self.repo,
        }
        return [label for label, value in values.items() if "<" in value]


def default_description(customer: str) -> str:
    return f"{customer} medallion lakehouse (bronze → silver → gold) on Databricks."


def derived_defaults(catalog: str, repo_default: str, tag: str) -> dict:
    customer = catalog.replace("_", " ").title()
    return {
        "customer": customer,
        "description": default_description(customer),
        "repo": repo_default,
        "host": HOST_PLACEHOLDER,
        "catalog_dev": catalog,
        "catalog_stage": f"{catalog}_stage",
        "catalog_prod": f"{catalog}_prod",
        "warehouse_id": WAREHOUSE_PLACEHOLDER,
        "mcp_profile": f"{catalog}_dev",
        "deploy_sp": DEPLOY_SP_PLACEHOLDER,
        "reader_group": f"{catalog}_readers",
        "engineer_group": f"{catalog}_engineers",
        "admin_group": f"{catalog}_admins",
        "framework_tag": tag,
        "agents": list(AGENT_CHOICES),
        "components": default_components(),
    }


def _ok(value: str, pattern: str, what: str) -> tuple[bool, str]:
    if "<" in value or re.fullmatch(pattern, value):
        return True, ""
    return False, what


VALIDATORS = {
    "host": lambda v: _ok(v, r"https://[^\s/]+(/[^\s]*)?", "use the full https://… workspace URL"),
    "repo": lambda v: _ok(v, r"[\w.-]+/[\w.-]+", "use <owner>/<repo>, e.g. acme-corp/acme-datalab"),
    "warehouse_id": lambda v: _ok(v, r"[A-Za-z0-9]+", "a SQL warehouse id is alphanumeric (e.g. 1a2b3c4d5e6f7a8b)"),
    "deploy_sp": lambda v: _ok(
        v, r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "the deploy SP application id is a UUID"),
    "group": lambda v: _ok(v, r"[\w][\w .@-]*", "letters, digits, spaces, _ . @ - only"),
    "profile": lambda v: _ok(v, r"[\w.-]+", "a CLI profile name: letters, digits, _ . - only"),
    "catalog_env": lambda v: _ok(v, CATALOG_RE.pattern.strip("^$"), "lowercase letters/digits/underscores"),
    "text": lambda v: (bool(v.strip()) and "\n" not in v, "one non-empty line"),
    "tag": lambda v: _ok(v, r"v\d+\.\d+\.\d+", "a vX.Y.Z framework release tag"),
}


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


def ask(label: str, default: str, validator: str) -> str:
    while True:
        value = _prompt(label, default).strip()
        ok, msg = VALIDATORS[validator](value)
        if ok:
            return value.rstrip("/") if validator == "host" else value
        print(f"    ! {msg}")


def toggle(title: str, choices: dict[str, str], selected: list[str], note: str = "") -> list[str]:
    """A numbered checklist: type numbers to flip them, `all` / `none`, Enter to accept."""
    names = list(choices)
    picked = [n for n in names if n in selected]
    while True:
        print(f"\n  {title}" + (f"  ({note})" if note else ""))
        for i, name in enumerate(names, 1):
            print(f"    [{'x' if name in picked else ' '}] {i}. {name:<14} {choices[name]}")
        try:
            raw = input("  Toggle by number (e.g. 2 4), 'all', 'none', or Enter to accept: ").strip().lower()
        except EOFError:
            raw = ""
        if not raw:
            return picked
        if raw in ("all", "none"):
            picked = list(names) if raw == "all" else []
            continue
        for token in re.split(r"[\s,]+", raw):
            if token.isdigit() and 1 <= int(token) <= len(names):
                name = names[int(token) - 1]
                picked = [n for n in names if (n in picked) != (n == name)]
            elif token in names:
                picked = [n for n in names if (n in picked) != (n == token)]
            else:
                print(f"    ! ignored {token!r}")


def walk_form(fixed: dict, given: dict, args, repo_default: str, tag_default: str) -> dict:
    """The interactive form. `fixed` (from flags) skips its question; `given`
    (an answers file, or a previous pass through the form) prefills it."""

    def pick(key: str, label: str, default: str, validator: str) -> str:
        return fixed[key] if key in fixed else ask(label, given.get(key, default), validator)

    print("\n  datalab adopter configurator — press Enter to accept a [default]; nothing is")
    print("  written until you confirm the summary.")

    print("\n  1/6  Customer & repo")
    catalog = fixed.get("catalog") or ""
    while True:
        if not catalog:
            catalog = _prompt("Base catalog / domain name (lowercase, no _dev/_stage/_prod)",
                              given.get("catalog", ""))
        ok, msg = check_catalog(catalog, args.allow_env_suffix)
        if ok:
            break
        print(f"    ! {msg}\n")
        catalog = ""
    d = derived_defaults(catalog, repo_default, tag_default)
    if given.get("catalog") not in (None, catalog):
        given = {}  # a different catalog invalidates catalog-derived answers
    r = {"catalog": catalog}
    r["customer"] = pick("customer", "Customer display name", d["customer"], "text")
    r["description"] = pick("description", "One-line description", default_description(r["customer"]), "text")
    r["repo"] = pick("repo", "GitHub repo <owner>/<name> (the OIDC federation subject)", d["repo"], "repo")

    print("\n  2/6  Workspace & environments  (targets/ · variables/)")
    r["host"] = pick("host", "dev workspace host (https://…; Enter to fill in later)", d["host"], "host")
    same_host = r["host"]
    split = ("host_stage" in fixed or "host_prod" in fixed
             or given.get("host_stage", same_host) != same_host
             or given.get("host_prod", same_host) != same_host)
    if not split and "host_stage" not in fixed:
        split = confirm("  Do stage and prod live in DIFFERENT workspaces?")
    r["host_stage"] = pick("host_stage", "stage workspace host", same_host, "host") if split else fixed.get("host_stage", same_host)
    r["host_prod"] = pick("host_prod", "prod workspace host", same_host, "host") if split else fixed.get("host_prod", same_host)
    envs = {e: given.get(f"catalog_{e}", d[f"catalog_{e}"]) for e in ENVIRONMENTS}
    envs.update({e: fixed[f"catalog_{e}"] for e in ENVIRONMENTS if f"catalog_{e}" in fixed})
    print("  Catalogs per environment: " + " · ".join(f"{e} → {c}" for e, c in envs.items()))
    if confirm("  Change them?"):
        for env in ENVIRONMENTS:
            envs[env] = ask(f"{env} catalog", envs[env], "catalog_env")
    r.update({f"catalog_{e}": c for e, c in envs.items()})
    r["warehouse_id"] = pick("warehouse_id", "SQL warehouse id (UC bootstrap + MCP grounding)", d["warehouse_id"], "warehouse_id")
    r["mcp_profile"] = pick("mcp_profile", "Databricks CLI profile for the dev workspace", d["mcp_profile"], "profile")
    r["deploy_sp"] = pick("deploy_sp", "CI/CD deploy service principal application id", d["deploy_sp"], "deploy_sp")

    print("\n  3/6  Access groups  (rbac.yml — ACCOUNT-level groups)")
    for key, label in (("reader_group", "Reader group"), ("engineer_group", "Engineer group"),
                       ("admin_group", "Admin group")):
        r[key] = pick(key, label, d[key], "group")

    print("\n  4/6  Coding agents  (each brings only its own harness; skills ship with any)")
    r["agents"] = fixed.get("agents") or toggle(
        "Which coding agents will this repo use?", AGENT_CHOICES, given.get("agents", d["agents"]))

    print("\n  5/6  Optional components")
    comps = fixed.get("components") or toggle(
        "Which optional components should the repo carry?",
        {k: v for k, (_, v) in COMPONENT_CHOICES.items()},
        given.get("components", d["components"]),
    )
    if "mcp" in comps and not {"claude", "cursor"} & set(r["agents"]):
        print("    note: mcp needs claude or cursor — it is dropped for this selection")
    r["components"] = comps

    print("\n  6/6  Framework")
    r["framework_tag"] = pick("framework_tag", "datalab framework release tag", d["framework_tag"], "tag")
    return r


def to_answers(values: dict) -> Answers:
    # Record what is actually applied: Selection drops a choice that cannot
    # take effect (mcp without claude/cursor) and fixes the canonical order.
    sel = Selection(list(values["agents"]), list(values["components"]))
    values = {**values, "agents": sel.agents, "components": sel.components}
    return Answers(
        catalog=values["catalog"],
        customer=values["customer"],
        description=values["description"],
        repo=values["repo"],
        hosts={"dev": values["host"], "stage": values["host_stage"], "prod": values["host_prod"]},
        catalogs={e: values[f"catalog_{e}"] for e in ENVIRONMENTS},
        warehouse_id=values["warehouse_id"],
        mcp_profile=values["mcp_profile"],
        deploy_sp=values["deploy_sp"],
        reader_group=values["reader_group"],
        engineer_group=values["engineer_group"],
        admin_group=values["admin_group"],
        framework_tag=values["framework_tag"],
        agents=list(values["agents"]),
        components=list(values["components"]),
    )


def flatten(a: Answers) -> dict:
    """The inverse of to_answers — the form's key space."""
    flat = asdict(a)
    hosts, catalogs = flat.pop("hosts"), flat.pop("catalogs")
    flat.update({"host": hosts["dev"], "host_stage": hosts["stage"], "host_prod": hosts["prod"]})
    flat.update({f"catalog_{e}": catalogs[e] for e in ENVIRONMENTS})
    return flat


def load_answers_file(path: str) -> dict:
    """An answers file: a previous run's .datalab-adopter.json, or a bare
    `answers` object in the same shape (as written by --answers-out)."""
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"scaffold: cannot read answers file {path}: {exc}") from exc
    data = data.get("answers", data)
    known = {f.name for f in Answers.__dataclass_fields__.values()}
    unknown = set(data) - known
    if unknown:
        raise SystemExit(f"scaffold: unknown key(s) in answers file {path}: {', '.join(sorted(unknown))}")
    flat = dict(data)
    for env, host in (flat.pop("hosts", None) or {}).items():
        flat["host" if env == "dev" else f"host_{env}"] = host
    for env, cat in (flat.pop("catalogs", None) or {}).items():
        flat[f"catalog_{env}"] = cat
    return flat


FLAG_KEYS = {
    "catalog": "catalog", "customer": "customer", "description": "description", "repo": "repo",
    "host": "host", "host_stage": "host_stage", "host_prod": "host_prod",
    "catalog_dev": "catalog_dev", "catalog_stage": "catalog_stage", "catalog_prod": "catalog_prod",
    "warehouse_id": "warehouse_id", "mcp_profile": "mcp_profile", "deploy_sp": "deploy_sp",
    "reader_group": "reader_group", "engineer_group": "engineer_group",
    "admin_group": "admin_group", "framework_tag": "framework_tag",
}


def resolve_answers(args, repo_default: str, tag_default: str) -> Answers:
    given = load_answers_file(args.answers) if args.answers else {}
    fixed = {key: getattr(args, attr).strip() for attr, key in FLAG_KEYS.items()
             if getattr(args, attr) not in (None, "")}
    if args.agents is not None:
        fixed["agents"] = parse_choice_list(args.agents, AGENT_CHOICES, list(AGENT_CHOICES), "agent")
    if args.components is not None:
        fixed["components"] = parse_choice_list(
            args.components, COMPONENT_CHOICES, given.get("components", default_components()), "component")

    if args.interactive:
        while True:
            values = walk_form(fixed, given, args, repo_default, tag_default)
            answers = to_answers(values)
            print_summary(answers)
            try:
                choice = input("\nApply this configuration? [y]es / [e]dit answers / [N]o: ").strip().lower()
            except EOFError:
                choice = ""
            if choice in ("y", "yes"):
                return answers
            if choice in ("e", "edit"):
                given = {**flatten(answers)}
                fixed = {k: v for k, v in fixed.items() if k == "catalog"}
                continue
            raise SystemExit("scaffold: aborted at confirmation — nothing was written.")

    catalog = fixed.get("catalog") or given.get("catalog", "")
    ok, msg = check_catalog(catalog, args.allow_env_suffix)
    if not ok:
        raise SystemExit(f"scaffold: --catalog (or the answers file): {msg}")
    values = {**derived_defaults(catalog, repo_default, tag_default), **given, **fixed, "catalog": catalog}
    if "description" not in given and "description" not in fixed:
        values["description"] = default_description(values["customer"])
    values.setdefault("host_stage", values["host"])
    values.setdefault("host_prod", values["host"])
    for key, validator in (("host", "host"), ("host_stage", "host"), ("host_prod", "host"),
                           ("repo", "repo"), ("warehouse_id", "warehouse_id"),
                           ("deploy_sp", "deploy_sp"), ("mcp_profile", "profile"),
                           ("reader_group", "group"), ("engineer_group", "group"),
                           ("admin_group", "group"), ("catalog_dev", "catalog_env"),
                           ("catalog_stage", "catalog_env"), ("catalog_prod", "catalog_env"),
                           ("customer", "text"), ("description", "text")):
        ok, msg = VALIDATORS[validator](str(values[key]))
        if not ok:
            raise SystemExit(f"scaffold: {key} = {values[key]!r}: {msg}")
    for key in ("host", "host_stage", "host_prod"):
        values[key] = values[key].rstrip("/")
    return to_answers(values)


def shipping_plan(sel: Selection, tracked: list[str]) -> tuple[list[str], list[str]]:
    """(kept, left-out) at a glance: top-level entries, plus the finer
    PATH_RULES a selection turns off inside an entry that does ship."""
    feats = sel.features
    kept: list[str] = []
    left: list[str] = []
    for top in sorted({rel.split("/", 1)[0] for rel in tracked}):
        rule = TOP_LEVEL[top]
        if rule == "template":
            continue
        if rule == "keep" or evaluate(rule, feats):
            kept.append(top)
        else:
            left.append(f"{top} [{rule}]")
    if sel.has("design"):
        kept.append("design (generated)")
    for path, expr in PATH_RULES:
        top = path.split("/", 1)[0]
        if expr != "template" and top in kept and not evaluate(expr, feats):
            left.append(f"{path} [{expr}]")
    return kept, left


def print_summary(a: Answers, tracked: list[str] | None = None) -> None:
    sel = a.selection
    rows = [
        ("catalog", f"{a.catalog}  (dev {a.catalogs['dev']} · stage {a.catalogs['stage']} · prod {a.catalogs['prod']})"),
        ("customer", f"{a.customer} — {a.description}"),
        ("GitHub repo", a.repo),
        ("hosts", " · ".join(f"{e} {a.hosts[e]}" for e in ENVIRONMENTS)),
        ("warehouse id", a.warehouse_id),
        ("CLI profile", a.mcp_profile),
        ("deploy SP", a.deploy_sp),
        ("groups", f"{a.reader_group} / {a.engineer_group} / {a.admin_group}"),
        ("framework", a.framework_tag),
        ("coding agents", ", ".join(sel.agents) or "none"),
        ("components", ", ".join(sel.components) or "none"),
    ]
    print("\n  Summary")
    for key, value in rows:
        print(f"    {key:<14} {value}")
    kept, left = shipping_plan(sel, tracked or tracked_files())
    print("\n    ships        " + ", ".join(kept))
    if left:
        print("    left out     " + ", ".join(left))
    print("    never        projects/, omnigent/, the scaffold tooling (template-only)")
    if a.todos():
        print("    TODO         placeholders to fill before deploy: " + ", ".join(a.todos()))


# --------------------------------------------------------------------------- #
# Build + apply
# --------------------------------------------------------------------------- #

def context(a: Answers) -> dict[str, str]:
    sel = a.selection
    return {
        "@@CATALOG_DEV@@": a.catalogs["dev"],
        "@@CATALOG_STAGE@@": a.catalogs["stage"],
        "@@CATALOG_PROD@@": a.catalogs["prod"],
        "@@CATALOG@@": a.catalog,
        "@@CUSTOMER@@": a.customer,
        "@@DESCRIPTION@@": a.description,
        "@@HOST_STAGE@@": a.hosts["stage"],
        "@@HOST_PROD@@": a.hosts["prod"],
        "@@HOST@@": a.hosts["dev"],
        "@@FRAMEWORK_TAG@@": a.framework_tag,
        "@@DATALAB_VERSION@@": a.framework_tag.lstrip("v"),
        "@@READER_GROUP@@": a.reader_group,
        "@@ENGINEER_GROUP@@": a.engineer_group,
        "@@ADMIN_GROUP@@": a.admin_group,
        "@@DEPLOY_SP@@": a.deploy_sp,
        "@@WAREHOUSE_ID@@": a.warehouse_id,
        "@@MCP_PROFILE@@": a.mcp_profile,
        "@@TEMPLATE_URL@@": TEMPLATE_URL,
        "@@AGENTS_LIST@@": ", ".join(sel.agents) or "none",
        "@@COMPONENTS_LIST@@": ", ".join(sel.components) or "none",
    }


def build(stage: Path, tracked: list[str], a: Answers) -> None:
    """Assemble the whole adopter in `stage` (a scratch dir)."""
    sel = a.selection
    ctx = context(a)

    def subst(text: str) -> str:
        for key, value in ctx.items():
            text = text.replace(key, value)
        return text

    copy_selected(stage, tracked, sel.features)
    write_domain(stage, ctx, subst, sel)
    write_repo_level(stage, subst, sel)
    if sel.has("design"):
        write_design(stage, ctx, subst)
        patch_design_spec(stage, subst)
    # Patches run on the COMPLETE template text (every anchor is still there);
    # the adopter-if regions are resolved afterwards.
    patch_makefile(stage, a.catalog)
    patch_bootstrap_uc(stage, a.catalog, ctx)
    patch_domains(stage, a.catalog)
    patch_rbac(stage, ctx)
    patch_ci(stage)
    patch_cd(stage, a.catalog)
    patch_cicd_docs(stage, ctx, a.repo)
    patch_agents_md(stage, a.catalog, subst, sel)
    patch_mcp(stage, ctx)
    patch_doc_regions(stage, subst, sel)
    localize_docs(stage, a)
    patch_agent_mcp(stage, ctx)
    patch_cursor_rules(stage, a.catalog, sel)
    patch_skills(stage, subst)
    conditional_edits(stage, sel)
    if sel.has("mcp"):
        narrow_mcp_docs(stage, sel)
    patch_codeowners(stage)
    patch_dependabot(stage)
    patch_workflow_comments(stage)
    process_markers(stage, sel.features)
    targets = makefile_targets(stage)
    for path, text in text_files(stage):
        if path.suffix in (".md", ".mdc"):
            pruned = prune_dead_make_lines(text, targets)
            if pruned != text:
                path.write_text(pruned, encoding="utf-8")
    relink_dropped_docs(stage, tracked, a.framework_tag)
    pin_framework_doc_links(stage, a.framework_tag)
    rewrite_agent_json(stage, sel, targets)
    mirror_claude_skills(stage)
    if sel.has("design"):
        write_design_diagrams(stage, a.catalog)  # last: reads the finished Makefile/targets/CI
    (stage / MANIFEST).write_text(json.dumps({
        "generated_by": f"{TEMPLATE_SLUG} scripts/scaffold_adopter.py",
        "template_commit": template_commit(),
        "answers": asdict(a),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    validate_output(stage)


def pin_framework_doc_links(out: Path, tag: str) -> None:
    """Point every framework-repo link in the generated repo at ITS pinned tag
    (check_lockstep fails otherwise). The copied docs carry the template's pin,
    which differs when --framework-tag chose another release."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bump_framework import pin_framework_links, tracked_text_files

    pin_framework_links(tracked_text_files(out), tag)


def staged_files(stage: Path) -> list[str]:
    return sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())


def apply_in_place(stage: Path, tracked: list[str]) -> None:
    """Make the clone match the staged adopter. Only runs after build() fully
    succeeded, so a failure can never leave a half-converted clone."""
    staged = set(staged_files(stage))
    for rel in tracked:
        if rel not in staged:
            (REPO_ROOT / rel).unlink(missing_ok=True)
    for top, rule in TOP_LEVEL.items():  # template-only entries go wholesale
        target = REPO_ROOT / top
        if rule == "template" and target.is_dir():
            shutil.rmtree(target)
        elif rule == "template" and target.exists():
            target.unlink()
    for rel in sorted(staged):
        dest = REPO_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / rel, dest)
    for rel in tracked:  # prune directories the dropped files leave empty
        parent = (REPO_ROOT / rel).parent
        while parent != REPO_ROOT and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_argument_group("mode")
    mode.add_argument("--in-place", action="store_true", help="convert THIS repo (a template clone) in place")
    mode.add_argument("--out", default="", help="output dir for a fresh sibling repo")
    mode.add_argument("--interactive", action="store_true", help="walk the form (flags skip their questions) and confirm a summary")
    mode.add_argument("--yes", "-y", action="store_true", help="non-interactive: no prompts, no confirmation (agent/CI)")
    mode.add_argument("--answers", default="", help="replay answers from a .datalab-adopter.json (flags override)")
    mode.add_argument("--force", action="store_true", help="overwrite a non-empty --out; or bypass the in-place template guard")
    mode.add_argument("--no-doc-check", action="store_true", help="report dangling doc references as warnings instead of failing")
    ident = parser.add_argument_group("identity")
    ident.add_argument("--catalog", default=None, help="base catalog / domain name (lowercase, no env suffix)")
    ident.add_argument("--customer", default=None, help="customer display name (default: from the catalog)")
    ident.add_argument("--description", default=None, help="one-line description of this repo's data product")
    ident.add_argument("--repo", default=None, help="GitHub <owner>/<repo> for the OIDC subject (default: git origin)")
    ident.add_argument("--allow-env-suffix", action="store_true", help="permit a catalog ending in _dev/_stage/_prod")
    ws = parser.add_argument_group("workspace & environments")
    ws.add_argument("--host", default=None, help="dev Databricks workspace URL")
    ws.add_argument("--host-stage", default=None, help="stage workspace URL (default: the dev host)")
    ws.add_argument("--host-prod", default=None, help="prod workspace URL (default: the dev host)")
    ws.add_argument("--catalog-dev", default=None, help="dev catalog (default: <catalog>)")
    ws.add_argument("--catalog-stage", default=None, help="stage catalog (default: <catalog>_stage)")
    ws.add_argument("--catalog-prod", default=None, help="prod catalog (default: <catalog>_prod)")
    ws.add_argument("--warehouse-id", default=None, help="SQL warehouse id (UC bootstrap + MCP grounding)")
    ws.add_argument("--mcp-profile", default=None, help="Databricks CLI profile for dev (default: <catalog>_dev)")
    ws.add_argument("--deploy-sp", default=None, help="CI/CD deploy SP application id")
    acc = parser.add_argument_group("access")
    acc.add_argument("--reader-group", default=None, help="reader group (default: <catalog>_readers)")
    acc.add_argument("--engineer-group", default=None, help="engineer group (default: <catalog>_engineers)")
    acc.add_argument("--admin-group", default=None, help="admin group (default: <catalog>_admins)")
    sel = parser.add_argument_group("selection")
    sel.add_argument("--agents", default=None,
                     help=f"coding agents: {','.join(AGENT_CHOICES)} | all | none (default: all)")
    sel.add_argument("--components", default=None,
                     help=f"components: {','.join(COMPONENT_CHOICES)} | all | none | default, or "
                          "+x/-x edits of the defaults (default: " + ",".join(default_components()) + ")")
    sel.add_argument("--framework-tag", default=None, help="datalab framework tag (default: this repo's pin)")
    args = parser.parse_args(argv)
    if args.in_place and args.out:
        parser.error("--in-place and --out are mutually exclusive")
    if not args.in_place and not args.out:
        parser.error("pass --out <dir> for a fresh sibling repo, or --in-place to convert this clone")
    if args.interactive and args.yes:
        parser.error("--interactive and --yes are mutually exclusive")
    if args.interactive and not sys.stdin.isatty():
        parser.error("--interactive needs a terminal; pass values as flags (or --answers) with --yes")
    return parser, args


def main(argv: list[str] | None = None) -> int:
    parser, args = parse_args(argv)
    ensure_template_layout()
    tracked = tracked_files()
    check_rules(tracked)

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
        if out.exists() and any(out.iterdir()) and not args.force:
            parser.error(f"{out} exists and is not empty (use --force to overwrite)")
        slug = ""
    repo_default = slug if slug and slug != TEMPLATE_SLUG else REPO_PLACEHOLDER

    answers = resolve_answers(args, repo_default, args.framework_tag or framework_tag())
    if not re.fullmatch(r"v\d+\.\d+\.\d+", answers.framework_tag):
        raise SystemExit(
            f"scaffold: framework tag {answers.framework_tag!r} is not a vX.Y.Z release tag. "
            "var.datalab_version becomes the Volume wheel FILENAME "
            "(datalab-<version>-py3-none-any.whl), so a branch/rev pin (e.g. 'main') would "
            "never match the wheel publish_wheel builds. Pass --framework-tag v<x.y.z>."
        )
    if not args.interactive:
        print_summary(answers, tracked)
        if args.in_place and not args.yes:
            if not sys.stdin.isatty():
                parser.error("--in-place needs --yes (or --interactive) for non-interactive use")
            if not confirm("\nProceed? This rewrites the current repo in place."):
                raise SystemExit("scaffold: aborted — nothing was written.")

    with tempfile.TemporaryDirectory(prefix="datalab-adopter-") as tmp:
        stage = Path(tmp) / "repo"
        stage.mkdir()
        print(f"\nscaffold: building the '{answers.catalog}' adopter in a scratch dir …")
        build(stage, tracked, answers)
        import check_adopter_docs  # template-only checker, same scripts/ dir

        problems = check_adopter_docs.collect_problems(stage, template_root=REPO_ROOT)
        if problems:
            print("\nscaffold: the generated docs still point at material this repo does not have:",
                  file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            if not args.no_doc_check:
                raise SystemExit(
                    "scaffold: nothing was written. This is a template gap — please report it; "
                    "--no-doc-check downgrades it to this warning."
                )
        if args.in_place:
            print(f"scaffold: converting {out} in place")
            apply_in_place(stage, tracked)
        else:
            if out.exists():
                shutil.rmtree(out)
            shutil.copytree(stage, out)
            print(f"scaffold: generated {out}")

    print("scaffold: done. Next:")
    if args.in_place:
        print("  make lock install && make validate-configs lint test")
    else:
        print(f"  cd {args.out} && git init -b main && make lock install")
        print("  make validate-configs lint test")
    print("  # then follow docs/NEW_ADOPTER.md — the ordered first-deploy checklist")
    print("  # (GitHub wiring, account-level groups, bootstrap-uc, publish-wheel, deploy)")
    if answers.todos():
        print(f"  NOTE: still placeholders — fill before deploy: {', '.join(answers.todos())}.")
    print(f"  Answers recorded in {MANIFEST} (replay: make new-adopter OUT=<dir> ANSWERS=<it>).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
