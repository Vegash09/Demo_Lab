# AGENTS.md — datalab

Shared source of truth for AI coding agents (Cursor, Claude Code) and humans.
Read this before editing. Keep it accurate when you change the system.

## Overview

datalab is a medallion (bronze → silver → gold) lakehouse framework built on
**Lakeflow Spark Declarative Pipelines** (SDP, the successor of DLT) and
shipped as a **Declarative Automation Bundle** (DAB, formerly Databricks Asset
Bundle).

- **Pipelines**: Python files under `src/<pipeline>/transformations/` using
  `from pyspark import pipelines as dp` — never `import dlt` (deprecated).
- **Shared library**: `src/datalab/` — pure, unit-testable DataFrame functions
  and helpers. Pipeline files only wire these into datasets.
- **Three authoring lanes**: SDP pipelines (all medallion tables), python-file
  job tasks (`src/jobs/`, headless side-effectful edge work) and notebook job
  tasks (`notebooks/`, human-gated runs). Route with the 3-question router in
  "Authoring rules" below.
- **Deploy**: `databricks.yml` + `resources/*.yml`, deployed via GitHub OIDC
  CI/CD to targets `dev` / `stage` / `prod`.
- **Dependencies**: `uv` end to end (`pyproject.toml` + committed `uv.lock`).
  No poetry, no pip requirements files.

## Architecture

```
Developer ──push/PR──▶ GitHub Actions ──OIDC──▶ Declarative Automation Bundle
                       ci-cd-{dev,stage,prod}    (databricks.yml + resources/*.yml)
                       common-ci / common-cd                │ deploys
                                                            ▼
                  ┌──────────────── Lakeflow SDP pipeline: sales_etl ───────────────┐
landing volume ─▶ │ bronze.customers_raw ─▶ silver.customers (AUTO CDC, SCD1) ─▶ gold │
(Auto Loader)     │        expectations ──▶ silver.customers_quarantine              │
                  └───────────────────────────────────────────────────────────────┘
                       refreshed daily by job sales_etl_refresh (pipeline_task)

  edge jobs (read-only on pipeline tables): sales_export ─▶ exports volume (weekly CSV)
                                            sales_quarantine_report (on-demand triage notebook)
```

## Codebase layout

```
databricks.yml            Bundle: variables (catalog/schemas/paths/permissions), targets dev/stage/prod
resources/
  sales_etl.pipeline.yml  SDP pipeline (serverless, environment_version, configuration params)
  sales_etl.job.yml       Daily refresh job (pipeline_task; paused in dev mode)
  sales_ops.job.yml       Edge jobs: sales_export (spark_python_task, weekly) +
                          sales_quarantine_report (notebook_task, on-demand, no trigger)
notebooks/                Notebook lane ONLY (human-gated job tasks; source-format .py)
  sales/quarantine_report.py
src/
  datalab/                Shared python package (installed editable into pipeline + job envs)
    config.py             pipeline_conf() (read pipeline configuration), fqn()
    params.py             notebook_params() / cli_params() — job-lane parameter contract
    quality.py            rule-dict helpers (violation_predicate for quarantine)
    transforms/sales.py   pure transforms + QUARANTINE_RULES / WARN_RULES
  sales_etl/              Pipeline root_path
    transformations/      bronze_customers.py, silver_customers.py, gold_customers.py
  jobs/                   Python-file lane: spark_python_task entry points (side effects live here)
    sales/export_customer_summary.py
tests/                    Unit tests (local Spark) for src/datalab — no workspace needed
scripts/bootstrap_uc.py   One-time UC bootstrap per target: schemas/volumes/GRANTs (make bootstrap-uc)
sql/abac/                 Column-mask / row-filter SQL — display-only, admin-applied (never run by CI/agents)
pyproject.toml            PEP 621 + [dependency-groups].dev; hatchling builds src/datalab
uv.lock                   Committed lockfile; CI uses `uv sync --frozen`
Makefile                  Developer + CI entrypoints (run `make help`)
.github/                  Workflows (ci-cd-*, common-*, pr-template-check) + composite actions
.claude/ .cursor/         Agent harness: settings, hooks, skills, rules
.githooks/pre-commit      Human-side protected-files guard (enable: make enable-githooks)
docs/                     ARCHITECTURE.md, CICD.md, MIGRATION.md
```

## Local development

```bash
make install          # uv sync → .venv from uv.lock
make lint             # ruff check src tests notebooks scripts
make test             # pytest (local Spark; needs Java 17+)
make validate         # databricks bundle validate -t dev
make deploy           # validate + bundle deploy -t dev
make run              # databricks bundle run sales_etl -t dev (dev refresh)
```

Python: 3.12+ (serverless environment v4 ships 3.12). Java 17+ locally for the
unit-test Spark. Databricks CLI ≥ v0.294.0 (pipeline `environment_version`
support).

## Authoring rules

Three lanes. Route every new target with the **3-question router**:

1. *Is the output a managed Delta table in the medallion, derivable from
   upstream datasets?* → **SDP**, mandatory. Backfills included — author them
   as a one-time `@dp.append_flow(target=..., once=True)` in the owning
   pipeline, never as a job writing the table.
2. *Is it a side-effectful action — export to a volume/external system, API
   pull into landing, maintenance of non-SDP tables — running headless on a
   schedule?* → **python-file** (`spark_python_task`, `src/jobs/<domain>/`).
3. *Must a human read the run output and decide?* → **notebook**
   (`notebook_task`, `notebooks/<domain>/`, on-demand only — no trigger).

When in doubt: SDP. Exploratory analysis with no managed target stays out of
the bundle entirely (workspace user folders), never in `resources/*.yml`.

| Target type | Lane |
|---|---|
| Streaming ingest from cloud storage into bronze (Auto Loader) | SDP (mandatory) |
| Incremental silver with CDC/SCD + quality gating + quarantine | SDP (mandatory) |
| Any managed Delta table / aggregate in the medallion (gold MVs) | SDP (mandatory) |
| Backfill / historical load into an SDP-owned table | SDP `@dp.append_flow(once=True)` |
| Headless export / API pull / non-SDP table maintenance | python-file |
| Reusable versioned CLI needing an immutable prod artifact | python-file as `python_wheel_task` (opt-in, `uv build --wheel`) |
| Human-gated runs: quarantine triage, supervised repair, demos | notebook (on-demand) |
| Exploration with no managed target | out of the bundle |

**Single-writer invariant**: every UC table has exactly one owning lane. Jobs
and notebooks may READ SDP-owned tables, never write them — repaired/backfill
data re-enters via the landing volume or a once-flow. A job calling
`.saveAsTable` on an SDP streaming table corrupts pipeline state.

### SDP lane (`src/<pipeline>/transformations/`)

- Import: `from pyspark import pipelines as dp`. The `dlt` module is the old
  name and must not be used.
- Datasets: `@dp.table` (streaming), `@dp.materialized_view` (batch),
  `@dp.temporary_view` (pipeline-scoped). Dataset functions **return a
  DataFrame** — never call `.write`, `.saveAsTable`, `.start()`, or
  `.collect()` inside one; the engine owns materialization.
- Upserts/CDC: `dp.create_streaming_table(...)` +
  `dp.create_auto_cdc_flow(target=..., source=..., keys=[...], sequence_by=...)`.
  This replaces hand-written `MERGE` logic (and the old `apply_changes`).
- Data quality: expectation decorators (`@dp.expect_all`,
  `@dp.expect_all_or_drop`, `@dp.expect_or_fail`, ...). Rules live as
  `{name: sql_expr}` dicts in `src/datalab/transforms/` so the quarantine
  tables can reuse them via `datalab.quality.violation_predicate`.
- Parameters: never hardcode catalogs/schemas/paths. Declare them in the
  pipeline resource `configuration:` mapping and read with
  `datalab.config.pipeline_conf(spark, "datalab.<key>")`.
- Business logic goes in `src/datalab/transforms/` as pure functions with unit
  tests; transformation files stay thin wiring.
- `spark` is injected by the SDP runtime at module scope in pipeline files
  (ruff is configured to allow it there, see `per-file-ignores`).

### Python-file lane (`src/jobs/<domain>/`)

- Entry points: argparse-style flags resolved via
  `datalab.params.cli_params(argv, names)` (snake_case names ↔ kebab-case
  flags), `SparkSession.builder.getOrCreate()`, explicit `main()` +
  `if __name__ == "__main__":` — see `src/jobs/sales/export_customer_summary.py`.
- Wire as `spark_python_task` in a `resources/*.job.yml` with job
  `parameters:` defaulted from bundle variables; the task `parameters:` list
  maps them to flags via `{{job.parameters.<name>}}`.
- Serverless `environments:` block installs the repo with
  `--editable ${workspace.file_path}` — the same mechanism as the pipeline,
  one dependency-delivery path.
- Reuse `datalab.quality.all_rules_predicate` / `violation_predicate` for any
  valid/invalid split. If you find yourself wanting upsert semantics, the
  target should have been SDP — never reintroduce `MERGE`.
- No per-file ruff ignores here: entry points own their SparkSession, so an
  undefined name is a real bug.

### Notebook lane (`notebooks/<domain>/`)

- Source-format `.py` notebooks (`# Databricks notebook source`). Widgets are
  named identically to the job parameters and resolved via
  `datalab.params.notebook_params(dbutils, names)` — see
  `notebooks/sales/quarantine_report.py`.
- Wire as `notebook_task` with `base_parameters:` mapping
  `{{job.parameters.<name>}}`; **no trigger** — this lane is human-gated by
  definition, run via `databricks bundle run <job> -t dev`.
- No business logic in cells: call pure functions from `src/datalab`. Writes
  are allowed only to tables/volumes the notebook owns (e.g. its report
  snapshot table), never to SDP-owned tables.

## Critical knowledge (gotchas)

- **DLT → SDP rename.** `import dlt` still works on Databricks but is
  deprecated; this repo standardizes on `pyspark.pipelines` (available in
  Apache Spark 4.1+ and all current DBR channels). `@dlt.view` is now
  `@dp.temporary_view`; `dlt.apply_changes` is `dp.create_auto_cdc_flow`.
- **DABs rename.** "Databricks Asset Bundles" became "Declarative Automation
  Bundles" (CLI v0.295.0, March 2026) — non-breaking, the `databricks bundle`
  commands are unchanged.
- **Pipeline deps are NOT `[project].dependencies` at dev time.** The pipeline
  environment installs this repo with `--editable ${workspace.file_path}`
  (see `resources/sales_etl.pipeline.yml`); `environment_version: "4"` pins
  Python 3.12 + preinstalled libs. Extra runtime libs go in
  `[project].dependencies` (picked up by the editable install) — but pipeline
  environments cache dependencies during development; trigger a full restart
  if a new dep doesn't show up.
- **Never install `databricks-connect` into this venv.** It conflicts with the
  `pyspark` dev dependency (both own the `pyspark` namespace). Integration
  testing = deploy + `make run` against dev, not databricks-connect.
- **Dev target uses `mode: development`**: resources get a `[dev <user>]`
  prefix and the daily trigger is paused. Stage/prod use `mode: production`
  with explicit `root_path`s.
- **`uv.lock` is the contract.** CI runs `uv sync --frozen` and fails on
  drift. After editing `pyproject.toml`, run `make lock` and commit both.
- **GitHub OIDC** auth (no stored client secret). The federation policy
  subject must match `repo:<owner>/<repo>:environment:<target>` because the
  CI/CD jobs declare `environment: <target>`. See `docs/CICD.md`.
- **Quarantine pattern**: silver drops rows violating `QUARANTINE_RULES`
  (expectations) while `customers_quarantine` captures exactly those rows by
  filtering with the inverse predicate — change the rules dict, both sides
  follow.
- **The "no writes" rule is scoped to SDP dataset functions.** `notebooks/`
  and `src/jobs/` own their writes — that is the point of those lanes —
  constrained by the single-writer invariant (never write SDP-owned tables).
  Don't block legitimate `.write` calls there in review.
- **Job environments share the pipeline's dependency mechanism and gotcha.**
  `resources/sales_ops.job.yml` installs the repo with
  `--editable ${workspace.file_path}` into serverless job environments;
  like pipeline environments they cache dependencies, so a changed `datalab`
  package may not appear until the environment rebuilds.
- **Spark 4 ANSI mode**: serverless/SDP runs with ANSI SQL on, so a plain
  `.cast()` on malformed data **fails the stream** instead of yielding NULL.
  Cleaning transforms use `try_cast` / `try_to_date` so bad values become
  NULLs that the quality rules then catch (see `clean_customers`).
- **`python_wheel_task` is opt-in only.** When a target genuinely demands an
  immutable artifact: `artifacts: {type: whl, build: uv build --wheel}` +
  `[project.scripts]` entry + environment dependency `../dist/*.whl` instead
  of `--editable`. Until then `spark_python_task` is the default — one
  delivery path, zero build steps. Never poetry.
- **Export/landing volumes are out-of-band UC setup per environment.** The
  export entry point fails fast if `/Volumes/<catalog>/exports/sales/` is
  missing rather than silently creating dev-shaped paths elsewhere.
  `make bootstrap-uc TARGET=<t>` creates them (plus schemas and grants).
- **Permission groups are string variables on purpose.** Complex variables
  (`pipeline_permissions`) cannot be overridden with `--var`; the
  `reader_group`/`engineer_group` strings can, which is what lets CI override
  groups per GitHub Environment. Don't inline group names back into the
  complex defaults.
- **ABAC SQL is display-only.** Nothing in this repo (CI, agents, scripts)
  executes `sql/abac/*.sql`; an admin reviews and applies it manually. Keep
  it that way — auto-applying access policies from a code repo is the
  failure mode the convention exists to prevent.

## Coding-agent maintenance protocol

When you change anything in the **protected file surface** below, in the same
change:

1. Capture the *why* in this file (Common tasks or Critical knowledge).
2. If the architecture moved, update `docs/ARCHITECTURE.md`.
3. If you change the protected set itself, update **all three** in one commit:
   `.claude/hooks/protected_files_guard.py`, `.githooks/pre-commit`, and the
   table below.

### Protected file surface

| Path (regex) | Why it's protected |
|---|---|
| `^databricks\.yml$`, `^resources/.*\.yml$` | Declarative Automation Bundle (deploy surface) |
| `^pyproject\.toml$`, `^uv\.lock$` | dependency manifests (uv-managed, CI `--frozen`) |
| `^\.databricksignore$` | controls what ships to the workspace |
| `^src/datalab/(config|quality|params)\.py$` | parameterization + quality contracts used by every pipeline and job lane |
| `^\.github/(workflows\|actions)/.*` | CI/CD (OIDC, bundle deploy) |
| `^\.github/pull_request_template\.md$` | unified PR template |
| `^\.claude/(settings\.json\|hooks/.*\|skills/.*)` | Claude agent harness |
| `^\.cursor/(rules\|hooks\|skills)/.*`, `^\.cursor/hooks\.json$` | Cursor rules + hooks + skills |
| `^\.githooks/.*` | git pre-commit guard |
| `^Makefile$` | developer + CI entrypoints |
| `^\.env(\..*)?$` | secrets — never commit |
| `^(AGENTS\|CLAUDE\|README)\.md$`, `^docs/(ARCHITECTURE\|CICD\|MIGRATION)\.md$` | documents of record |

The guards emit a *warn/ask* (agents) or *block-until-acknowledged* (git):

- Agents: `.claude/hooks/protected_files_guard.py` (PreToolUse).
- Humans: `.githooks/pre-commit` — enable with `make enable-githooks`; bypass a
  single commit with `make commit-protected MSG="..."` (`PROTECTED_EDIT_OK=1`).

## Common tasks

- **Add a table to an existing pipeline**: add/extend a file under
  `src/sales_etl/transformations/`, put the logic in
  `src/datalab/transforms/` with a unit test, follow the
  `author-sdp-pipeline` skill. `make lint test validate`.
- **Add a new domain pipeline** (e.g. finance): create
  `src/finance_etl/transformations/`, copy `resources/sales_etl.pipeline.yml`
  + `resources/sales_etl.job.yml` and rename keys/paths, reuse the shared
  variables. The skill has the full checklist.
- **Change quality rules**: edit the rules dicts in
  `src/datalab/transforms/<domain>.py` — expectations and quarantine stay in
  sync automatically. Add a unit test for the new rule.
- **Add a python-file task**: run the 3-question router first. Entry point in
  `src/jobs/<domain>/` (argparse via `datalab.params.cli_params`, pure logic
  in `src/datalab` with a unit test), copy the `sales_export` job shape from
  `resources/sales_ops.job.yml` (parameters from bundle variables,
  `environments` block, `permissions: ${var.job_permissions}`).
  `make lint test validate`.
- **Add a notebook task**: router first — only if a human must read the run.
  Source-format `.py` under `notebooks/<domain>/`, widgets named after the job
  parameters, resolved via `datalab.params.notebook_params`; copy the
  `sales_quarantine_report` job shape (no trigger). `make lint test validate`.
- **Add a dependency**: edit `pyproject.toml`, `make lock`, commit both files.
  For pipeline-runtime deps, remember the environment caching gotcha above.
- **Change deploy config**: edit `databricks.yml` / `resources/*.yml`, then
  `make validate` before pushing; update `docs/` if targets or variables moved.
- **Change access (RBAC/ABAC)**: workspace-resource permissions → the
  `reader_group`/`engineer_group` variables (per-target overrides in
  `databricks.yml`, per-environment via `DATALAB_*_GROUP` repo variables);
  data grants → `scripts/bootstrap_uc.py` (keep its CATALOGS/GROUPS dicts in
  sync with `databricks.yml`), re-run `make bootstrap-uc`; row/column
  policies → add display-only SQL under `sql/abac/` following the conventions
  in `docs/ARCHITECTURE.md` — never execute them from CI or an agent session.
- **Open a pull request**: fill `.github/pull_request_template.md` into a body
  file and `gh pr create --body-file <file>` (or `--web`). Keep the
  `datalab-pr-template` marker and the `##` section headings — the hook + CI
  enforce them.

## Agent don'ts

- Don't use `import dlt`, `dlt.*` APIs, or hand-written MERGE/upsert logic in
  pipelines — use `pyspark.pipelines` + AUTO CDC.
- Don't perform writes or actions inside dataset functions.
- Don't hardcode catalogs, schemas, hosts, or volume paths in pipeline code —
  use bundle variables + pipeline `configuration`.
- Don't introduce poetry/pip-requirements workflows — deps are uv-only.
- Don't edit `uv.lock` by hand.
- Don't commit `.env`, workspace state (`.databricks/`), or `.venv`.
- Don't open a PR that bypasses the unified template.

## Security

- Secrets stay in `.env` (local) / GitHub Environment secrets (CI). Never
  commit them; `.gitignore` + the guards back this up.
- CI/CD uses GitHub OIDC — there is no long-lived Databricks secret in GitHub.
- Production data access is governed by Unity Catalog grants plus the bundle
  `permissions` variables (`pipeline_permissions`, `job_permissions`).
