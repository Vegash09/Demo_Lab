# AGENTS.md — datalab

Shared source of truth for AI coding agents (Cursor, Claude Code, Codex) and humans.
Read this before editing. Keep it accurate when you change the system.

<!-- template-only:repo-intro start (scaffold_adopter.py swaps this block in generated adopters) -->
> **Repo split (done).** The reusable framework lives in its OWN repo,
> **[dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework)** —
> there is no `src/datalab` in this repo. THIS repo is the reference **domains +
> deploy bundle** that CONSUMES `datalab` two ways: a **git dependency** for local
> dev/CI (pinned in `pyproject.toml` `[tool.uv.sources]` to a release tag) and a
> versioned **UC-Volume wheel** for serverless (`var.datalab_wheel`) that this repo
> **builds from the pinned git dep and publishes on every deploy** (`make
> publish-wheel` / the `deploy-dab` action). Keep the git tag and
> `var.datalab_version` in lockstep. The framework **reference** (artifact anatomy,
> target kinds, dqx, the SDP capability matrix) lives in that repo's
> [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md);
> to stand up your own repo on the framework, see [`docs/ADOPTING.md`](docs/ADOPTING.md).
<!-- template-only:repo-intro end -->

## Overview

datalab is a medallion (bronze → silver → gold) lakehouse framework built on
**Lakeflow Spark Declarative Pipelines** (SDP, the successor of DLT) and
shipped as a **Declarative Automation Bundle** (DAB, formerly Databricks Asset
Bundle).

- **Pipelines are config-driven (flowspec)**: every target table is ONE YAML
 artifact at `config/<catalog>/<schema>/<table>.yml` (columns with
  source→target names + data types, per-column dqx rules, target kind —
  plus fan-in `sources:`, one-time `backfill:` flows, AUTO CDC and snapshot
  CDC), authored from natural language via the `author-ldp-artifact` skill,
  validated by Pydantic models and generated into LDP datasets by
  `datalab.framework.generate` — see the framework repo's
  [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md)
  (the full reference, including the SDP capability matrix). The per-domain
  `transformations/pipeline.py` is 3 lines. Never `import dlt` (deprecated).
- **Framework vs domain — strict separation**: the REUSABLE framework (models,
  adapters, dqx engine, devtools, param helpers) is an **external dependency**
  (the `datalab-framework` repo), consumed here as a git dep + UC-Volume wheel —
  it has zero domain code and lifts into any project untouched. Domain code is
  declared to the framework via `domain.yml`'s `imports:` list — never by editing
  the framework (which lives in its own repo).
<!-- template-only:overview-domains start -->
- **projects/ holds the reference domains**: `projects/customer_sales/` is a
  complete worked adoption (config + domain package + edge jobs + notebook +
  resources + tests + ABAC SQL) laid out to MIRROR an adopter repo root —
  copy it to start a real domain (`docs/GETTING_STARTED.md`). The bundle
  deploys it, so it doubles as the framework's integration test; the framework
  does not depend on it. A second domain, `projects/sales/`, is a
  pipeline-only adoption over pre-existing `sales.bronze.*` tables (no edge
  jobs/notebooks) that doubles as the FEATURE SHOWCASE: AUTO CDC SCD1 + SCD2
  (`customers_history`), snapshot CDC (`product_catalog`,
  `cdc_from_snapshot`), domain-wide `operational_metadata:` stamps, config
  templates + `sql`-source gold rollups (`revenue_by_state`/`_country`) and
  dqx built-ins (`is_valid_email`) — and deploys from the same bundle.
  Fan-in `sources:` and `backfill:` deliberately have NO deployed example
  (they need second physical sources this demo workspace lacks; shapes live
  in the framework repo's FRAMEWORK.md).
<!-- template-only:overview-domains end -->
- **Folder names mirror the UC namespace** (`docs/NAMING.md`): the domain
  folder is the BASE CATALOG name (`customer_sales`; stage/prod append
  `_stage`/`_prod` via bundle variables), config subfolders are the SCHEMA
  names (`config/<catalog>/<schema>/<table>.yml` ⇒
  `<catalog>.<schema>.<table>`), the domain package is `<catalog>_etl`, and
  jobs/notebooks/resources are catalog-prefixed (`src/jobs/<catalog>/`,
  `<catalog>_etl` pipeline, `<catalog>_<purpose>` jobs).
- **Data quality**: databrickslabs/dqx end to end — checks in YAML (dqx
  metadata format), valid/quarantine split per dataset, optional metrics MV.
- **Three authoring lanes**: SDP pipelines (all medallion tables), python-file
  job tasks (headless side-effectful edge work) and notebook job tasks
  (human-gated runs). Route with the 3-question router in "Authoring rules".
- **Deploy**: `databricks.yml` + `projects/*/resources/*.yml` (adopters:
  root-level `resources/*.yml`), deployed via GitHub OIDC CI/CD to targets
  `dev` / `stage` / `prod`.
- **Dependencies**: `uv` end to end (`pyproject.toml` + committed `uv.lock`).
  No poetry, no pip requirements files.

## Architecture

<!-- template-only:architecture start -->
```
Developer ──push/PR──▶ GitHub Actions ──OIDC──▶ Declarative Automation Bundle
                       ci-cd.yml (ONE workflow;  (databricks.yml + projects/*/resources/*.yml)
                       target derived from the              │ deploys
                       trigger) → common-ci / common-cd     ▼
                       + framework-bump.yml (bot) + dependabot
                  ┌──────────── Lakeflow SDP pipeline: customer_sales_etl ──────────┐
landing volume ─▶ │ bronze.customers_raw ─▶ silver.customers (AUTO CDC, SCD1) ─▶ gold │
(Auto Loader)     │        dqx checks ────▶ silver.customers_quarantine              │
                  └───────────────────────────────────────────────────────────────┘
                  refreshed daily by job customer_sales_etl_refresh (pipeline_task)

                  ┌──────────── Lakeflow SDP pipeline: sales_etl (pipeline-only showcase) ─┐
sales.bronze.*  ─▶│ orders · order_items · customers · products                            │
(pre-existing)    │   ─▶ silver (AUTO CDC SCD1 + dqx, per-table _quarantine)               │
                  │      + customers_history (SCD2) · product_catalog (snapshot CDC)       │
                  │   ─▶ gold MVs: daily_sales · revenue_per_customer · sales_by_category  │
                  │      + templated (sql source): revenue_by_state · revenue_by_country   │
                  │   domain-wide operational_metadata stamps (_loaded_at, _record_source) │
                  └────────────────────────────────────────────────────────────────────────┘
                  on-demand (no scheduled refresh job yet; make run PIPELINE=sales_etl)

  edge jobs (read-only on pipeline tables): customer_sales_export ─▶ exports volume (weekly CSV)
                                            customer_sales_quarantine_report (on-demand triage notebook)
```
<!-- template-only:architecture end -->

## Codebase layout

<!-- template-only:codebase-layout start -->
```
databricks.yml            Bundle: name + include only (variables/ + targets/ + rbac + resources merged in)
variables/                Variable declarations + defaults (medallion catalog/schemas/paths); include'd, deep-merged
targets/                  One file per environment (dev/stage/prod): mode, host, per-env variable values; include'd
rbac.yml                  Workspace-resource RBAC: group + permission-level string vars + complex
                          pipeline_permissions/job_permissions + per-target overrides (include'd by databricks.yml)
(THE FRAMEWORK — src/datalab — now lives in its OWN repo: dediggibyte/datalab-framework.
 It is consumed here as a git dependency (local dev/CI, pinned in pyproject.toml
 [tool.uv.sources] datalab) and a versioned UC-Volume wheel (serverless,
 var.datalab_wheel). It moved there WITH history; there is no src/ in this repo.)
projects/                 REFERENCE domains — each named after its base UC catalog and mirroring
                          an adopter repo root (projects/README.md, docs/NAMING.md)
  customer_sales/
    README.md             File-by-file tour of the complete worked example
    config/customer_sales/  domain.yml + ONE <schema>/<table>.yml artifact per target table
                          (path mirrors <catalog>.<schema>.<table>)
    src/customer_sales_etl/ Domain package (<catalog>_etl): pipeline entrypoint, @transform fns, custom dqx checks
    src/jobs/customer_sales/ Python-file lane: spark_python_task entry points (side effects live here)
    notebooks/customer_sales/ Notebook lane: human-gated triage (source-format .py)
    sample_data/          Local sample landing files for `make run-local` (OSS spark-pipelines)
    resources/            This domain's bundle resources (pipeline + 3 jobs; relative paths move as is)
    tests/                The domain's own unit + contract tests (run with make test)
    sql/abac/             Display-only column-mask/row-filter SQL — admin-applied, never run by CI/agents
  sales/                  Second reference domain (pipeline-only, the feature showcase): config/sales/
                          (incl. templates/) + src/sales_etl + resources + tests; silver (AUTO CDC SCD1 +
                          SCD2 + snapshot CDC + dqx) → gold MVs (incl. templated sql-source rollups) over
                          pre-existing sales.bronze.* tables; domain-wide operational_metadata stamps
scripts/validate_connect.py  Databricks Connect validation entry (make validate-connect; out-of-lock)
schemas/                  JSON schemas for editor validation (all 4: domain / table / template / template-instance) —
                          GENERATED from the PINNED framework's Pydantic models by scripts/sync_schemas.py
                          (make sync-schemas; make check-schemas gates CI — never hand-edit or hand-copy)
scripts/domains.py        THE domain registry: which domains this repo deploys; per-target catalogs/groups are
                          RESOLVED from variables/ + targets/ + rbac.yml (make check-domains gates CI).
                          Adding a domain = one DOMAINS entry here (+ the usual config/src/resources/vars)
scripts/bootstrap_uc.py   One-time UC bootstrap per target: every registry domain catalog's schemas/volumes/GRANTs, incl. its artifacts.wheels Volume holding the framework wheel (make bootstrap-uc; catalogs/groups come from scripts/domains.py)
scripts/publish_wheel.py  Build the FRAMEWORK wheel for the TARGET's resolved datalab_version + upload it into EACH registry catalog's artifacts.wheels UC Volume (make publish-wheel; CI runs it in deploy-dab before bundle deploy; --catalog-for <domain>=<catalog> mirrors --var catalog overrides)
scripts/check_lockstep.py  Assert the framework pin agrees everywhere: pyproject git tag == var.datalab_version == uv.lock tag == uv.lock package version; notes any per-target datalab_version override (make check-lockstep; CI gate)
scripts/bump_framework.py  Rewrite the pin at every site — driven by `make bump-framework VERSION=x.y.z` (edits + lock + schema regen + lockstep check); the framework-bump workflow opens this as a bot PR on new framework tags
scripts/check_sync_lists.py  Assert databricks.yml sync.exclude == .databricksignore (make check-sync-lists; CI gate)
pyproject.toml            PEP 621 + [dependency-groups].dev + [tool.uv.sources] (datalab → git tag) + [tool.uv.workspace]; root is package=false (builds nothing); each projects/<domain> is a workspace member building its own <catalog>_etl wheel
uv.lock                   Committed lockfile; CI uses `uv sync --frozen`
Makefile                  Developer + CI entrypoints (run `make help`)
.github/                  Workflows (ci-cd — one workflow, target from trigger; framework-bump bot;
                          common-*; pr-template-check) + dependabot.yml + composite actions
.claude/ .cursor/ .codex/  Agent harness (3): hooks, skills, rules. Skills authored ONCE in .agents/skills/
.agents/skills/            (the cross-tool standard, read natively by Cursor + Codex); .claude/skills is a
                           GENERATED copy for Claude Code (make sync-skills; check-skills guards drift). Genie
                           Code loads the same skills from the Workspace .assistant/skills/ via
                           make publish-genie-skills. .codex/hooks.json references the canonical .claude guards
.githooks/pre-commit      Human-side protected-files guard (enable: make enable-githooks)
docs/                     GETTING_STARTED, FRAMEWORK (reference), NAMING (folder↔UC convention),
                          ARCHITECTURE, CICD, MIGRATION
design/                   Customer-facing OVERVIEW.md + architecture diagrams (drawio):
                          01_*=multi-page design spec, 02_*=living end-to-end implementation,
                          images/=PNG exports (make design), datalab-customer-overview.html
                          (standalone share). Kept in sync via the maintain-design-diagram
                          skill; excluded from the deployed workspace files via databricks.yml sync.exclude
omnigent/                 Opt-in, dev-time pilot: an Omnigent agent spec (datalab-author.yaml,
                          instructions: ../AGENTS.md) to run the authoring workflow on any
                          harness; no policies ported, excluded from deploy (omnigent/README.md)
.mcp.json                 Opt-in, dev-time MCP (with .cursor/mcp.json): a uvx stdio proxy
                          (uc-mcp-proxy) to the workspace's MANAGED Databricks SQL MCP endpoint
                          so Claude Code/Cursor run READ-ONLY UC queries that ground authoring.
                          CLI-profile auth (no token), not in uv.lock, excluded from deploy.
                          See docs/AGENT_MCP.md + the query-databricks skill.
```

Adopter repos use the same shape with the domain at the ROOT instead of under
projects/: `config/<catalog>/`, `src/<catalog>_etl/`, `src/jobs/<catalog>/`,
`notebooks/<catalog>/`, `resources/*.yml` (see `projects/README.md`; naming
contract: `docs/NAMING.md`).
<!-- template-only:codebase-layout end -->

## Local development

```bash
make install          # uv sync → .venv from uv.lock (incl. the datalab git dep)
make lint             # ruff check scripts and projects
make test             # pytest (the example domain suites; needs Java 17+)
make validate-configs # validate every domain's artifacts (pydantic + dqx)
make validate         # databricks bundle validate -t dev
make deploy           # validate + bundle deploy -t dev
make publish-wheel    # build the framework wheel from the pinned git dep + upload into each project catalog's artifacts.wheels Volume (APPLY=1)
make run              # databricks bundle run customer_sales_etl -t dev (dev refresh)
make run-local        # materialize the medallion on sample data via OSS spark-pipelines
make dry-run-local    # spark-pipelines dry-run (graph validation, no data)
make validate-connect # run one dataset on a LIVE cluster via isolated Databricks Connect
make design           # re-export design/*.drawio diagrams to design/images/*.png (needs draw.io Desktop)
```

Python: 3.12+ (serverless environment v4 ships 3.12). Java 17+ locally for the
unit-test Spark and the OSS `spark-pipelines` local run. Databricks CLI ≥
v0.294.0 (pipeline `environment_version` support).

**Three execution profiles** (same configs, one codebase; `datalab.profile`
selects the graph — default `databricks`): the Databricks deploy path; a
**local** OSS `spark-pipelines` run (`make run-local`, a batch
materialized-view downgrade — no AUTO CDC dedup, no dqx, no Auto Loader/sinks);
and **Databricks Connect** validation from local (`make validate-connect`, an
isolated out-of-lock overlay). Full reference: the framework repo's FRAMEWORK.md "Run anywhere".

## Authoring rules

Three lanes. Route every new target with the **3-question router**:

1. *Is the output a managed Delta table in the medallion, derivable from
   upstream datasets?* → **SDP**, mandatory. Backfills included — declare
   them as `backfill:` entries in the table's artifact (generated as
   one-time `once` flows), never as a job writing the table.
2. *Is it a side-effectful action — export to a volume/external system, API
   pull into landing, maintenance of non-SDP tables — running headless on a
   schedule?* → **python-file** (`spark_python_task`, `src/jobs/<domain>/`).
3. *Must a human read the run output and decide?* → **notebook**
   (`notebook_task`, `notebooks/<domain>/`, on-demand only — no trigger).

When in doubt: SDP. Exploratory analysis with no managed target stays out of
the bundle entirely (workspace user folders), never in resource files.

| Target type | Lane |
|---|---|
| Streaming ingest from cloud storage into bronze (Auto Loader) | SDP (mandatory) |
| Streaming ingest from Kafka/Event Hubs/MSK | SDP (`source.kind: kafka`) |
| Incremental silver with CDC/SCD + quality gating + quarantine | SDP (mandatory) |
| SCD from periodic FULL snapshots (nightly dumps, JDBC extracts) | SDP (`target.cdc_from_snapshot`) |
| Multi-region/multi-topic fan-in into one streaming table | SDP (`sources:` list — replaces UNION) |
| Any managed Delta table / aggregate in the medallion (gold MVs) | SDP (mandatory) |
| Backfill / historical load into an SDP-owned table | SDP (`backfill:` once-flows) |
| Streaming publish to Kafka / external Delta destination | SDP (`kafka_sink` / `delta_sink`) |
| Headless export / API pull / non-SDP table maintenance | python-file |
| Reusable versioned CLI needing an immutable prod artifact | python-file as `python_wheel_task` (opt-in, `uv build --wheel`) |
| Human-gated runs: quarantine triage, supervised repair, demos | notebook (on-demand) |
| Exploration with no managed target | out of the bundle |

**Single-writer invariant**: every UC table has exactly one owning lane. Jobs
and notebooks may READ SDP-owned tables, never write them — repaired/backfill
data re-enters via the landing volume or a `backfill:` flow. A job calling
`.saveAsTable` on an SDP streaming table corrupts pipeline state.

### SDP lane (config-driven — `config/<catalog>/<schema>/<table>.yml`)

- **Add/change a table = author its artifact**, not python: ONE YAML per
  target table in its layer folder (file name == table name) declaring
  source(s) (cloud_files / files / table / view / kafka — single `source:`
  or fan-in `sources:`), `columns:` (source→target names, data types,
  per-column dqx rules), transform steps (registry name + `args:` + `tables:`), table-level
  quality, optional `backfill:` once-flows, and target (streaming_table
  [+cdc | +cdc_from_snapshot] / materialized_view / temporary_view /
  delta_sink / kafka_sink). NL→artifact recipe: `author-ldp-artifact` skill;
  full reference incl. the SDP capability matrix: the framework repo's
  [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md).
- Business logic stays in `src/<catalog>_etl/transforms/` as pure functions
  registered with `@transform("<domain>.<name>")`. **A transform never names a
  catalog/schema and never reads `spark.conf` itself** — everything it needs comes
  from its artifact step as keyword arguments: scalars via `args:` (where
  `${conf:<key>}` resolves), and any EXTRA TABLE it reads via `tables:`, which the
  framework resolves to a per-environment name through the same lane
  `source: {kind: table}` uses:

  ```yaml
  transform:
    - function: sales.sales_by_category
      tables:
        products_table: {name: products, layer: silver}   # -> "cat.silver.products"
      args: {min_qty: 1}
  ```

  ```python
  @transform("sales.sales_by_category")
  def sales_by_category(df, products_table: str, min_qty: int = 0):
      return category_rollup(df, df.sparkSession.read.table(products_table))
  ```

  This keeps the artifact the single declaration of every table a dataset touches,
  lets `run_dataset(inputs={"cat.silver.products": df})` substitute the dimension
  in tests, and makes a wrong/missing kwarg fail `make validate-configs` (the step's
  args+tables are bound against the function signature at load). Note the declared
  table is still a batch read OUTSIDE the SDP graph — it adds no pipeline
  dependency edge; use `source.kind: sql` when you need a real in-graph join.
  Custom dqx checks live in
  `src/<catalog>_etl/checks/` with `@check_function`; snapshot walkers with
  `@snapshot_source`. `domain.yml`'s `imports:` list names these modules —
  the framework hardcodes none.
- Validate early: `make validate-configs` (same loader as CI, pytest and the
  pipeline); verify behavior with `datalab.framework.run_dataset` (call it from
  a test or a notebook/REPL) or `make validate-connect` — no deploy needed.
- Hand-written `dp.*` wiring in transformation files is reserved for cases the
  framework genuinely cannot express (see the capability matrix in the
  framework repo's `docs/FRAMEWORK.md` for what's deliberately out) — extend the framework
  first. The rules below then still apply. Import:
  `from pyspark import pipelines as dp`. The `dlt` module is the old name and
  must not be used.
- Datasets: `@dp.table` (streaming), `@dp.materialized_view` (batch),
  `@dp.temporary_view` (pipeline-scoped). Dataset functions **return a
  DataFrame** — never call `.write`, `.saveAsTable`, `.start()`, or
  `.collect()` inside one; the engine owns materialization.
- Upserts/CDC: `dp.create_streaming_table(...)` +
  `dp.create_auto_cdc_flow(target=..., source=..., keys=[...], sequence_by=...)`
  — in YAML: `target.cdc`. Snapshot diffing:
  `dp.create_auto_cdc_from_snapshot_flow` — in YAML:
  `target.cdc_from_snapshot`. This replaces hand-written `MERGE` logic (and
  the old `apply_changes`).
- Data quality: databrickslabs/dqx via the framework (`quality.checks` in the
  artifact) — `dp.expect_*` is retired in this repo; even hand-written
  datasets should route quality through `datalab.framework.dq`.
- Parameters: never hardcode catalogs/schemas/paths. Declare them in the
  pipeline resource `configuration:` mapping and read with
  `datalab.config.pipeline_conf(spark, "datalab.<key>")`.
- `spark` is injected by the SDP runtime at module scope in pipeline files
  (ruff allows it there, see `per-file-ignores`). The example entrypoint
  instead binds `spark = SparkSession.getActiveSession() or
  SparkSession.builder.getOrCreate()` so the SAME file works on Databricks AND
  under the OSS `spark-pipelines` CLI (which does not inject `spark`).

### Python-file lane (`src/jobs/<domain>/`)

- Entry points: argparse-style flags resolved via
  `datalab.params.cli_params(argv, names)` (snake_case names ↔ kebab-case
  flags), `SparkSession.builder.getOrCreate()`, explicit `main()` +
  `if __name__ == "__main__":` — see
  `projects/customer_sales/src/jobs/customer_sales/export_customer_summary.py`.
- Wire as `spark_python_task` in a `*.job.yml` resource with job
  `parameters:` defaulted from bundle variables; the task `parameters:` list
  maps them to flags via `{{job.parameters.<name>}}`.
- Serverless `environments:` block installs the framework wheel from THIS
  domain's catalog artifacts.wheels Volume (`${var.datalab_wheel}` /
  `${var.sales_datalab_wheel}`) plus this domain's wheel
  (`../../../dist/<catalog>_etl-*.whl`) — the same mechanism as the pipeline
  (serverless does not honor `--editable`; see the Critical-knowledge gotcha).
- Any valid/invalid split belongs upstream in the SDP lane (dqx rules in the
  table's artifact — quarantine evidence included); jobs consume the already
  gated tables. If you find yourself wanting upsert semantics, the target
  should have been SDP — never reintroduce `MERGE`.
- No per-file ruff ignores here: entry points own their SparkSession, so an
  undefined name is a real bug.

### Notebook lane (`notebooks/<domain>/`)

- Source-format `.py` notebooks (`# Databricks notebook source`). Widgets are
  named identically to the job parameters and resolved via
  `datalab.params.notebook_params(dbutils, names)` — see
  `projects/customer_sales/notebooks/customer_sales/quarantine_report.py`.
- Wire as `notebook_task` with `base_parameters:` mapping
  `{{job.parameters.<name>}}`; **no trigger** — this lane is human-gated by
  definition, run via `databricks bundle run <job> -t dev`.
- No business logic in cells: call pure functions from the domain package
  (`src/<catalog>_etl`) or the installed `datalab` framework. Writes
  are allowed only to tables/volumes the notebook owns (e.g. its report
  snapshot table), never to SDP-owned tables.

## Branching & releases

- **MANDATORY — branch before you touch anything.** Every change (agent or
  human) starts from `main`: `git switch main && git pull`, then a fresh
  branch named `feature/<slug>`, `fix/<slug>`, or `debug/<slug>` depending on
  the work. Never edit files, commit, or push while `main` is checked out,
  and never stack new work on a previous feature branch. This is ENFORCED,
  not just convention: `.cursor/hooks/branch_guard.py` denies file edits and
  `git commit`/`git push`-to-main in all three agent harnesses (wired in
  `.cursor/hooks.json`, `.claude/settings.json` and `.codex/hooks.json`), and
  `.githooks/pre-commit` blocks human commits on `main`. If a guard blocks
  you mid-task: create the branch (uncommitted edits carry over) and retry.
- One PR per branch into `main` (unified template, see "Open a pull
  request"). CI (lint + test + validate-configs + bundle validate) must be
  green; merge via the GitHub UI.
- **Head branches are deleted on merge** — the repo setting
  "Automatically delete head branches" is ON (re-apply with
  `gh repo edit --delete-branch-on-merge` if the repo is recreated). After a
  merge, prune locally: `git switch main && git pull && git fetch --prune`.
- Releases: merge to `main` auto-deploys dev; tag `vX.Y.Z-rcN` → stage;
  tag `vX.Y.Z` → prod (`docs/CICD.md`).

## Critical knowledge (gotchas)

- **DLT → SDP rename.** `import dlt` still works on Databricks but is
  deprecated; this repo standardizes on `pyspark.pipelines` (available in
  Apache Spark 4.1+ and all current DBR channels). `@dlt.view` is now
  `@dp.temporary_view`; `dlt.apply_changes` is `dp.create_auto_cdc_flow`;
  `dlt.apply_changes_from_snapshot` is `dp.create_auto_cdc_from_snapshot_flow`.
- **DABs rename.** "Databricks Asset Bundles" became "Declarative Automation
  Bundles" (CLI v0.295.0, March 2026) — non-breaking, the `databricks bundle`
  commands are unchanged.
- **Flow names are checkpoint identities.** SDP keys each streaming flow's
  checkpoint on the FLOW NAME: renaming a fan-in `sources[].name` or
  `backfill[].name` (or converting single-source ↔ fan-in, which changes the
  generated flow names) abandons state and reprocesses from scratch — pair
  such changes with a deliberate full refresh.
- **Streaming FROM a CDC/SCD table** needs
  `options: {skipChangeCommits: "true"}` on the table source (or read the
  change feed with `readChangeFeed`); otherwise the downstream stream fails
  on the first UPDATE/DELETE commit.
- **Sinks are never cleared by full refresh** (SDP): reprocessed rows are
  APPENDED to delta/kafka sinks — design consumers for duplicates, and
  that's why `backfill:` is rejected on sink targets.
- **Backfills re-run on full refresh.** A completed `backfill:` once-flow
  idles in the graph and re-runs automatically when the pipeline/table is
  fully refreshed — leave it in the config (it's the recreation path and the
  audit trail).
- **Wheel delivery: the FRAMEWORK installs from a UC Volume; the example domains
  build their OWN wheels — never `--editable`.** Serverless pipeline (and job)
  environments do **not** honor an `--editable` install of the synced workspace
  files: the package never lands on the runtime path and the pipeline fails at
  import with `ModuleNotFoundError: No module named 'datalab'` (verified June 2026
  — the editable form the DAB templates suggest silently installs nothing here).
  So the framework ships as a versioned wheel (`datalab-<ver>-py3-none-any.whl`):
  this repo BUILDS it FROM the pinned git dep (`pip wheel "datalab @ git+…@<tag>"
  --no-deps`, NOT `uv build` at the root — the root is package-less) and publishes
  it into an `artifacts.wheels` UC Volume INSIDE EACH project's own catalog
  (`customer_sales.artifacts.wheels`, `sales.artifacts.wheels` — one upload per
  project catalog, NOT a separate shared catalog) — `make publish-wheel` locally,
  and CI publishes it in the `deploy-dab` action BEFORE `bundle deploy` (the
  referenced version must exist on each catalog's volume before a pipeline runs,
  or the env install fails). Each pipeline/job environment lists TWO deps: the
  framework wheel from THIS domain's catalog — `${var.datalab_wheel}`
  (customer_sales: `/Volumes/${var.catalog}/artifacts/wheels/...`) or
  `${var.sales_datalab_wheel}` (sales: `/Volumes/${var.sales_catalog}/...`) — and
  `../../../dist/<catalog>_etl-*.whl` (this domain's own wheel, built by the
  bundle's `artifacts:` — `uv build --package <catalog>_etl`, relative to the
  resource file). **CI/CD must have `uv` on PATH for `bundle deploy`** (it builds
  the example wheels) and for the publish step — the `deploy-dab` action installs
  it via `astral-sh/setup-uv` (`bundle validate` builds nothing, so the
  validate-only CI job doesn't need it). Each project catalog's `artifacts.wheels`
  volume must be readable by that domain's pipeline/job run-as identity
  (`make bootstrap-uc` provisions + grants it) or the install fails. The framework version lives in TWO
  lockstep places HERE — the `datalab` git tag in `pyproject.toml`
  `[tool.uv.sources]` and `variables/medallion.yml` `datalab_version` (the Volume
  filename). **Upgrade with `make bump-framework VERSION=x.y.z`** — one command
  that rewrites both, re-locks, regenerates the vendored `schemas/` and asserts
  the lockstep; CI enforces the agreement (`make check-lockstep` +
  `make check-schemas`), and the scheduled `framework-bump.yml` workflow opens
  this bump as a bot PR when the framework releases a new tag. Then
  `make publish-wheel APPLY=1` (record it in CHANGELOG.md; the framework's own
  `__version__` lives in the datalab-framework repo). A target can soak-test a
  newer framework by overriding `datalab_version` in its `targets/<env>.yml`
  (publish to that target first). That override is honored END TO END:
  `publish-wheel --target <t>` resolves the target's `datalab_version` — NOT the
  repo-wide pyproject pin — and builds/uploads that release, and
  `check-lockstep` prints a note naming any target whose override differs so it
  can never be invisible. `check-lockstep` also asserts uv.lock's resolved
  PACKAGE VERSION equals `var.datalab_version`: the wheel filename
  `var.datalab_wheel` points at is composed from the package version, not the
  tag, so a tag whose package version disagreed would pass every gate and fail
  only when a serverless environment tried to install a wheel that is not on the
  Volume.
  `environment_version: "4"` pins Python 3.12 + preinstalled libs. Extra framework
  runtime libs are declared in the framework repo (folded into its wheel) — but
  environments cache dependencies; trigger a full restart (or publish a new
  version) if a new dep doesn't show up.
- **Never install `databricks-connect` into the dev venv / `uv.lock`.** It
  conflicts with the `pyspark` dev dependency (both own the `pyspark`
  namespace). The sanctioned way to drive a live cluster from local is
  `make validate-connect`, which installs it into a THROWAWAY overlay (`uv run
  --no-project` with the framework git dep + the editable domain package + `--with
  databricks-connect`, mirroring the `--with databricks-sdk` bootstrap pattern) —
  never the project venv. This works because neither the domain package nor the
  framework git dep pulls `pyspark`, so the overlay has no
  conflict; and `datalab.framework.__init__` imports `generate` lazily so
  `run_dataset` loads without `pyspark.pipelines` (which databricks-connect may
  lack). Full integration still = deploy + `make run` against dev. Corollary:
  the VS Code/Cursor Databricks extension's "set up Python environment for
  Databricks Connect" step errors against `.venv` (`databricks-connect package
  is not installed`) — expected and advisory (it powers only interactive cell
  run/debug, never sync/deploy/run); keep `.venv` as the interpreter and use
  `make validate-connect` (see the framework repo's FRAMEWORK.md "Run anywhere").
- **Dev target uses `mode: development`**: resources get a `[dev <user>]`
  prefix and the daily trigger is paused. Stage/prod use `mode: production`
  with explicit `root_path`s.
- **CI deploy auto-approves destructive changes on DEV only.** A non-interactive
  `databricks bundle deploy` refuses destructive actions — deleting a
  renamed/removed pipeline and its STs/MVs — unless given `--auto-approve`. The
  `deploy-dab` action takes an `auto-approve` input (default `false`);
  `ci-cd.yml`'s params job sets it `true` only for dev because dev is disposable
  (`mode: development` —
  a full refresh restores every ST/MV), while `stage`/`prod` omit it so a human
  reviews any deletion. That is why a renamed pipeline resource (e.g.
  `sales_etl` → `customer_sales_etl`) self-heals on the next dev deploy but
  would block a `stage`/`prod` deploy until reviewed (`--auto-approve` is a
  deploy-only flag; `bundle validate` rejects it).
- **`uv.lock` is the contract.** CI runs `uv sync --frozen` and fails on
  drift. After editing `pyproject.toml`, run `make lock` and commit both.
- **A workspace git command CANNOT reach the private framework repo.**
  `actions/checkout` (with the default `persist-credentials: true`) writes
  `http.https://github.com/.extraheader = AUTHORIZATION: basic <GITHUB_TOKEN>`
  into the repo-LOCAL git config, and an explicit Authorization header BEATS the
  credentials in the URL that our `url."https://x-access-token:$TOKEN@…".insteadOf`
  rewrite supplies. So any `git` command run from the workspace (`git ls-remote`,
  `git fetch`, `git clone` of the framework) authenticates as the GITHUB_TOKEN,
  which cannot see `dediggibyte/datalab-framework`, and fails with the misleading
  `remote: Repository not found`. **uv is unaffected** — it clones into
  `~/.cache/uv`, outside the workspace, so the gitdir-scoped header never applies.
  That asymmetry is why `uv sync --frozen` succeeds in CI while a hand-written
  `git ls-remote` in the same job fails. Fix: prefix the command with
  `git -c http.https://github.com/.extraheader= …` (leave the header intact
  elsewhere, or the bot's own `git push` breaks). This cost six weeks of a silently
  stale framework pin — see `.github/workflows/framework-bump.yml`.
- **A version/staleness check that finds NOTHING must fail, not warn.** The bump
  bot read its tag list through a pipeline (`$(git ls-remote … | grep … | tail -1)`);
  when the git call failed, the pipeline's status came from `tail` (success), the
  variable was empty, and an empty result was treated as "nothing to do" — green
  job, no PR, for six weeks while the framework moved 0.6.0 → 0.9.0. Any gate that
  cannot determine an answer must `exit 1` with `::error::`, never `::warning::`
  plus a skip. Use `set -euo pipefail` in such steps.
- **Dependabot runs live in a separate, initially EMPTY secret store.** Workflow
  runs triggered by `dependabot[bot]` resolve `secrets.*` from Settings →
  Secrets and variables → **Dependabot**, not the Actions store (Actions
  **variables** still resolve normally). Until
  `DATALAB_FRAMEWORK_APP_PRIVATE_KEY` was mirrored into the Dependabot store,
  every dependabot PR failed `ci / lint + unit test` at the App-token mint
  (six weeks of red dependency PRs, July–Aug 2026). Do **not** mirror the
  Databricks environment secrets there: dependabot runs get a read-only
  `GITHUB_TOKEN` with no `id-token: write`, so the OIDC steps would fail
  instead of skipping gracefully. Two adjacent facts in the same failure
  class: (a) Dependabot's own updater has no repo credentials either — it
  needs explicit access to the private framework repo (org Settings → Code
  security → Dependabot) or every `uv` update dies with
  `git_dependencies_not_reachable`; (b) Dependabot cannot use the PR
  template (GitHub writes its bodies server-side), so
  `pr-template-check.yml` holds its PRs to a separate verifiable bot
  contract — title prefix (pinned via `commit-message.prefix` in
  `dependabot.yml`), body shape, `dependabot/*` branch — never a silent
  skip. See `docs/CICD.md` "Private framework dependency".
- **GitHub OIDC** auth (no stored client secret). The federation policy
  subject must match `repo:<owner>/<repo>:environment:<target>` because the
  CI/CD jobs declare `environment: <target>`. See `docs/CICD.md`.
- **CI/CD retention = the log/artifact setting, nothing else.** Actions logs +
  artifacts auto-expire on the repo retention setting (Settings → Actions →
  "Artifact and log retention", set to **30 days**) — there is no workflow-YAML
  or REST knob for log retention. Everything else is deliberately NOT pruned:
  artifacts (none uploaded), caches (free, 10 GB/repo cap, 7-day auto-evict),
  deployment records (metadata), and commits (source of truth — deleting them
  is a forbidden history rewrite that breaks the `v*` release tags). Measured
  sizes + rationale: `docs/CICD.md` "Retention & storage".
- **Quarantine pattern (dqx)**: `criticality: error` rows are dropped from
  the target and land in `<dataset>_quarantine` with `_errors` evidence
  structs; `warn` rows flow through flagged. Default
  `quarantine.include_warnings: false` keeps quarantine == exactly the
  dropped rows. One YAML rules list drives both sides — and with fan-in
  `sources:`, every flow feeds the same quarantine.
- **dqx runs with a mocked WorkspaceClient locally** (only DataFrame-in/out
  methods are used — never `*_save_in_table` inside dataset functions), and
  with static `run_time`/`run_id` overwrites ALWAYS — removing them silently
  breaks materialized-view incrementalization. Pinned by
  `tests/unit/framework/test_dq.py`.
- **dqx list-membership values are SQL expressions, not literals (dqx >= 0.16.0).**
  A BARE string in `is_in_list` / `is_not_in_list` / `is_not_null_and_is_in_list`
  (`allowed:` / `forbidden:`) resolves as a COLUMN reference / SQL expression, so
  string literals must carry their own quotes — `allowed: ["'completed'"]`, not
  `allowed: [completed]`. Numbers, booleans and ISO-8601 dates are safe as plain
  YAML scalars. A `DQCheck` validator rejects bare strings at config load, so
  `make validate-configs` catches it; set `allow_column_arguments: true` on the
  check when a column/expression genuinely IS intended. Live example:
  `projects/sales/config/sales/silver/orders.yml`.
- **Never install the dqx `[cli]` extra** — it pulls databricks-connect,
  which conflicts with the local pyspark dev dependency. dqx is pinned exact
  (Beta library); upgrade only after reading its changelog.
- **dp.expect_\* is retired in this repo** — dqx owns data quality. Pipeline
  event-log expectation metrics are replaced by quarantine tables, optional
  `*_dq_metrics` MVs and the quarantine-report notebook.
- **Local OSS `pyspark.pipelines` lacks Databricks-only symbols/knobs**
  (AUTO CDC functions, `once`, `cluster_by_auto`, MV `refresh_policy`).
  `datalab.framework.compat` guards them: graph capture drops the knobs
  locally (shape-only inspection), anything else raises an actionable error.
  Tests/capture run fine locally; CDC/once semantics verify via dev refresh.
- **`make run-local` runs the medallion off-Databricks (local profile).**
  `datalab.framework.local` emits a `spark-pipeline.yml` + a batch
  materialized-view graph for the OSS `spark-pipelines` CLI (selected by
  `datalab.profile: local`; the Databricks path is untouched). Deliberate
  fidelity gaps, each because OSS SDP can't express the Databricks feature:
  **no AUTO CDC dedup** (a window over an in-graph dataset triggers eager
  analysis and fails graph registration — and the SCD merge is engine-owned),
  **no dqx gate** (dqx reads `df.columns`/`df.isStreaming`, which OSS SDP
  forbids inside a query function), **no Auto Loader/sinks**. Datasets register
  under their SHORT name so OSS SDP resolves cross-dataset reads via the
  pipeline default catalog/db. Validate CDC/quality via `make test` /
  `run_dataset` / `make validate-connect` / dev refresh. The dev dep is
  `pyspark[pipelines]` (the extra ships the `spark-pipelines` CLI + Connect
  deps). CI runs `make dry-run-local` (advisory).
- **The "no writes" rule is scoped to SDP dataset functions.** The notebook
  and python-file lanes own their writes — that is the point of those lanes —
  constrained by the single-writer invariant (never write SDP-owned tables).
  Don't block legitimate `.write` calls there in review.
- **Job environments share the pipeline's dependency mechanism and gotcha.**
  The edge-job resources (`projects/customer_sales/resources/customer_sales_*.job.yml`) install
  the framework wheel from the customer_sales catalog's artifacts.wheels Volume (`${var.datalab_wheel}`)
  plus the `customer_sales_etl` wheel (`../../../dist/customer_sales_etl-*.whl`) into
  serverless job environments — same as pipelines, and for the same reason
  (serverless does not honor `--editable` of synced workspace files); like
  pipeline environments they cache dependencies, so a changed `datalab` package
  may not appear until the environment rebuilds or a new version is published.
- **Spark 4 ANSI mode**: serverless/SDP runs with ANSI SQL on, so a plain
  `.cast()` on malformed data **fails the stream** instead of yielding NULL.
  The framework's `columns:` mapping always casts with `try_cast` so bad
  values become NULLs that the quality rules then catch.
- **`python_wheel_task` is opt-in only.** The framework already ships to every
  environment as the versioned wheel from each project catalog's artifacts.wheels Volume;
  `python_wheel_task` is only for a target that additionally needs an immutable,
  versioned CLI entrypoint
  (`[project.scripts]` console script invoked by the wheel-task). Until then
  `spark_python_task` running a `.py` file is the default — zero extra build
  steps. Never poetry.
- **Export/landing volumes are out-of-band UC setup per environment.** The
  export entry point fails fast if `/Volumes/<catalog>/exports/sales/` is
  missing rather than silently creating dev-shaped paths elsewhere.
  `make bootstrap-uc TARGET=<t>` creates them (plus schemas and grants).
- **The edge-volume NAME is a registry field — bootstrap and the path variables
  must agree.** `scripts/domains.py` `DOMAINS[<domain>]["edge_volume"]` names
  the `landing`/`exports` UC volume bootstrap creates, and it must equal the
  volume segment of that domain's landing/export path variables
  (`/Volumes/<catalog>/landing/<edge_volume>/…`). bootstrap_uc used to hardcode
  `sales` while the adopter scaffold wrote `<catalog>` paths, so a fresh
  adopter's first `make run` failed on a volume that was never provisioned —
  the scaffold smoke test now asserts the contract end to end.
<!-- template-only:agents-conversion-gotcha start -->
- **AGENTS.md is converted for adopters via template-only markers.** Regions
  fenced `<!-- template-only:<name> start/end -->` are swapped for adopter text
  by `scaffold_adopter.py` (`patch_agents_md`), which then FAILS if any
  `projects/` / `design/` / `omnigent` reference survives outside a line that
  names the "template repo". Adding template-only material to this file? Fence
  it with markers (or handle it in `patch_agents_md`), or the CI scaffold
  smoke test fails loudly.
<!-- template-only:agents-conversion-gotcha end -->
- **Permission groups are string variables on purpose — and so are the
  levels.** All access control lives in `rbac.yml` (include'd by
  `databricks.yml` next to `variables/` and `targets/`; `databricks.yml` itself
  is just bundle name + includes). Complex variables
  (`pipeline_permissions`, `job_permissions`) cannot be overridden with
  `--var`, so the WHO (`reader_group`/`engineer_group`/`admin_group`) and the
  WHAT (`*_pipeline_level`/`*_job_level`) are plain strings the complex
  defaults only reference — that's what lets CI override them per GitHub
  Environment and lets a target change one group/level in a single line.
  Per-env divergence goes in `rbac.yml`'s `targets:`: same shape → override a
  string (prod readers drop to `CAN_VIEW`); a different shape (an extra group)
  → restate the complex var (prod adds `admin_group`). Never inline a group
  name or level back into the complex defaults.
- **ABAC SQL is display-only.** Nothing in this repo (CI, agents, scripts)
  executes the `sql/abac/*.sql` files (in this repo:
  `projects/customer_sales/sql/abac/`); an admin reviews and applies them manually.
  Keep it that way — auto-applying access policies from a code repo is the
  failure mode the convention exists to prevent.
- **Databricks MCP is read-only grounding, never a write path.** The opt-in
  `.mcp.json` / `.cursor/mcp.json` wire Claude Code / Cursor to the workspace's
  MANAGED Databricks SQL MCP endpoint (`/api/2.0/mcp/sql`) through a `uvx` stdio
  proxy (`uc-mcp-proxy`) that authenticates with the `diggi_dev_aws` CLI profile
  (OAuth U2M — no token in the repo). UC grants govern every read; the
  single-writer invariant still holds (the agent may SELECT/DESCRIBE SDP-owned
  tables, never write them — repaired data re-enters via the landing volume or a
  `backfill:` flow). The proxy runs via `uvx` (ephemeral) and is NEVER added to
  `pyproject.toml` / `uv.lock` (same rule as omnigent). The proxy resolves the
  workspace host from the CLI profile (`--url` is the relative `/api/2.0/mcp/sql`)
  and takes the warehouse via `--meta warehouse_id=<id>`. A profile name +
  warehouse id are config, not secrets — never put a token in the committed JSON.
  Managed MCP may be Beta/region-gated; the fallback (a local SQL MCP server) and
  the full setup live in `docs/AGENT_MCP.md`; the `query-databricks` skill governs
  when/how the agent reaches for it.
- **Agent skills are authored once in `.agents/skills/`, projected per tool.** No
  single folder is read by every coding agent, so the canonical authored source is
  `.agents/skills/` — the cross-tool `agentskills.io` standard, read natively by
  Cursor and Codex. Claude Code reads only `.claude/skills/` and does NOT reliably
  follow symlinked skills (upstream bugs; auto-updates can delete symlinks), so
  `make sync-skills` keeps a GENERATED byte-copy there (CI + pre-commit guard drift
  via `scripts/sync_skills.py --check`). Databricks Genie Code loads skills from the
  Workspace `.assistant/skills/` (NOT the repo) — publish the same skills with
  `make publish-genie-skills` (`scripts/publish_genie_skills.py` wraps
  `databricks workspace import-dir`); Genie additionally auto-discovers `AGENTS.md`,
  which the bundle already syncs to the workspace. Never hand-edit `.claude/skills/`.

## Coding-agent maintenance protocol

When you change anything in the **protected file surface** below, in the same
change:

1. Capture the *why* in this file (Common tasks or Critical knowledge).
<!-- template-only:maintenance-design start -->
2. If the architecture moved, update `docs/ARCHITECTURE.md` **and** the `design/`
   package: edit `design/02_implementation_end_to_end.drawio` (the living
   diagram), run `make design` to re-export `design/images/`, and refresh
   `design/OVERVIEW.md` if the customer narrative changed — all in the same PR.
   Follow the `maintain-design-diagram` skill (`design/01_*` only when the design
   intent changes).
<!-- template-only:maintenance-design end -->
3. **The framework is an external dependency — change it in the
   `datalab-framework` repo, not here** (its `docs/FRAMEWORK.md` is the doc of
   record for framework behavior). To BUMP the framework version in this repo,
   run `make bump-framework VERSION=x.y.z` — it rewrites the `datalab` git tag
   in `pyproject.toml` + `var.datalab_version` in lockstep, re-locks, and
   REGENERATES `schemas/*.json` from the newly pinned models
   (`make sync-schemas` — never hand-copy them; `make check-schemas` +
   `make check-lockstep` gate CI). Then `make publish-wheel APPLY=1` and record
   the bump in `CHANGELOG.md`. The scheduled `framework-bump.yml` workflow opens
   this bump as a bot PR automatically on new framework release tags.
4. If you change the protected set itself, update **all three** in one commit:
   `.claude/hooks/protected_files_guard.py`, `.githooks/pre-commit`, and the
   table below.
5. **Editing an agent skill?** Author it ONCE under `.agents/skills/<name>/SKILL.md`
   (read natively by Cursor + Codex), then run `make sync-skills` to regenerate the
   `.claude/skills` copy for Claude Code — never hand-edit it. The `check-skills` CI
   step + pre-commit reject drift (`scripts/sync_skills.py`). To reach Databricks
   Genie Code, run `make publish-genie-skills` (pushes the skills to the Workspace
   `.assistant/skills/`).

### Protected file surface

| Path (regex) | Why it's protected |
|---|---|
| `^databricks\.yml$`, `^rbac\.yml$`, `^(variables\|targets)/.*\.ya?ml$`, `^(resources\|projects/[^/]+/resources)/.*\.yml$` | Declarative Automation Bundle + variables/targets + RBAC (deploy surface) |
| `^pyproject\.toml$`, `^uv\.lock$` | dependency manifests (uv-managed, CI `--frozen`) |
| `^\.databricksignore$` | `databricks sync` / IDE-extension exclusions (bundle deploy excludes via `sync.exclude` in databricks.yml) |
| `^(config\|projects/[^/]+/config)/.*\.ya?ml$` | dataset configs — the deployed pipeline definition |
| `^\.github/(workflows\|actions)/.*` | CI/CD (OIDC, bundle deploy) |
| `^\.github/pull_request_template\.md$` | unified PR template |
| `^\.claude/(settings\.json\|hooks/.*\|skills/.*)` | Claude agent harness (hooks, settings, + the generated `.claude/skills` copy) |
| `^\.cursor/(rules\|hooks)/.*`, `^\.cursor/hooks\.json$` | Cursor rules + hooks (skills are read from `.agents/skills`) |
| `^\.codex/hooks\.json$`, `^\.agents/skills/.*` | Codex hooks.json + `.agents/skills` (the canonical authored agent-skills source) |
| `^scripts/sync_skills\.py$` | agent-skills sync generator (canonical `.agents/skills` → `.claude/skills` copy) |
| `^scripts/(sync_schemas\|check_lockstep\|bump_framework\|domains\|check_sync_lists)\.py$` | repo-integrity tooling: schema vendoring, framework-version lockstep, domain registry, sync-list check |
| `^schemas/.*\.json$` | vendored editor schemas — GENERATED from the pinned framework (`make sync-schemas`), never hand-edited |
| `^\.mcp\.json$`, `^\.cursor/mcp\.json$` | opt-in MCP server config (agent↔Databricks read-only query connection) |
| `^\.githooks/.*` | git pre-commit guard |
| `^Makefile$` | developer + CI entrypoints |
| `^\.env(\..*)?$` | secrets — never commit |
| `^(AGENTS\|CLAUDE\|README)\.md$`, `^docs/(ARCHITECTURE\|CICD\|MIGRATION\|GETTING_STARTED\|NAMING)\.md$` | documents of record |

The guards emit a *warn/ask* (agents) or *block-until-acknowledged* (git):

- Agents: `.claude/hooks/protected_files_guard.py` (PreToolUse).
- Humans: `.githooks/pre-commit` — enable with `make enable-githooks`; bypass a
  single commit with `make commit-protected MSG="..."` (`PROTECTED_EDIT_OK=1`).

Separate from the protected-file surface, `.cursor/hooks/branch_guard.py`
(agents, all three harnesses) and the same `.githooks/pre-commit` (humans) enforce
the branch-first policy — no edits/commits/pushes while `main` is checked out
(see "Branching & releases").

## Common tasks

- **Add a table to an existing pipeline**: create ONE artifact
  `config/<catalog>/<schema>/<table>.yml` (file name == table name; in this
  repo: `projects/customer_sales/config/customer_sales/...`) with the columns/types/DQ rules —
  follow the `author-ldp-artifact` skill; if new logic is needed, add a pure
  `@transform`-registered function in `src/<catalog>_etl/transforms/` with a
  unit test (and the module in `domain.yml` `imports:`).
  `make validate-configs lint test validate`. Reference: the framework repo's FRAMEWORK.md.
- **Backfill an SDP table**: add a `backfill:` entry (name + batch source;
  streaming source when the target has `cdc:`) to the table's artifact —
  never a job write. Names are checkpoint identities; the flow re-runs on
  full refresh by design. See "Backfills" in the framework repo's FRAMEWORK.md.
- **Stand up a new adopter repo for a customer**: one deterministic engine
  (`scripts/scaffold_adopter.py`) produces a minimal, root-level single-domain
  adopter repo two ways — (A) **in place**, `make configure-adopter` inside a
  clone made from this **GitHub template repository** (the
  `bootstrap-adopter-repo` skill drives this; interactive mode prompts ONLY for
  catalog + host, defaults the rest with a fill-before-deploy TODO list, and
  confirms a summary before converting the clone; `YES=1` runs it scripted), or (B) **fresh
  sibling**, `make new-adopter CATALOG=<c> OUT=../<c>-datalab` (copies only
  git-tracked files into a new dir). Same engine, same result: drops the
  reference domains, writes the minimal domain, rewrites every repo-level file,
  and **repoints the workspace-specific surfaces** — host/targets, RBAC groups,
  deploy SP, AND the read-only MCP grounding config (`.mcp.json` +
  `.cursor/mcp.json`: SQL warehouse id + CLI profile, which the old flow left
  pointing at the template's workspace). The engine **rejects** a `<catalog>` that
  carries an env suffix (`_dev`/`_stage`/`_prod`) — the base name only, since the
  bundle appends the env per target (`docs/NAMING.md`); that guard is what
  prevents the `config/<catalog>_databricks_prod` drift. Never hand-edit the
  conversion — drift is what hand-editing causes; `references/templates.md` is the
  manual fallback. Then extend with `author-ldp-artifact`. Wiring reference:
  `docs/ADOPTING.md`; the single ordered onboarding checklist (prereqs → first
  deploy) is `docs/NEW_ADOPTER.md`. **Cross-org:** both paths
  are org-agnostic, but the new repo reads the PRIVATE framework via the shared
  **datalab-framework reader GitHub App** — set `DATALAB_FRAMEWORK_APP_CLIENT_ID`
  (repo/org **variable**) + `DATALAB_FRAMEWORK_APP_PRIVATE_KEY` (repo/org **secret**),
  both repo/org-scoped, NOT per-environment; CI mints a short-lived token from it
  (`actions/create-github-app-token`, works across orgs since the App is installed
  on `datalab-framework`), and developers need their own read access to clone it
  locally. GitHub OIDC is NOT this — it federates Actions→Databricks only, never
  repo→repo git reads — so it cannot pull the framework into the wheel. Mechanics +
  alternatives (PAT / vendored wheel): `docs/ADOPTING.md` → "Accessing the private
  framework repo".
<!-- template-only:common-task-new-domain start -->
- **Add a new domain pipeline** (e.g. finance): follow
  `docs/GETTING_STARTED.md` end to end — copy the `projects/customer_sales/` shape
  (config + `src/<catalog>_etl` + resources + `pyproject.toml`), register the
  domain as a `[tool.uv.workspace]` member (it builds its own `<catalog>_etl`
  wheel), declare its catalog variables in `variables/medallion.yml` +
  `targets/*.yml`, add ONE entry to `scripts/domains.py` `DOMAINS` (bootstrap +
  wheel publish resolve catalogs/groups through the registry — `make
  check-domains` verifies), point `datalab.config_dir` at the new config dir, and
  list the domain's `<catalog>_datalab_wheel` + its own wheel in the resource
  `environment.dependencies`. The framework (the external `datalab` dependency) is not touched.
<!-- template-only:common-task-new-domain end -->
- **Change quality rules**: edit the column's `quality:` list (or the
  table-level `quality.checks`) in the table's artifact — dqx metadata,
  NL→function mapping in the `author-ldp-artifact` skill (full dqx catalog;
  pick the most specific function — `sql_expression` is a last resort;
  conventions follow the `databricks_dqx_agent` rule generator). Target
  filtering and quarantine stay in sync automatically. `make validate-configs`
  catches invalid rules statically; verify behavior with `run_dataset` or
  `make validate-connect`.
- **Add a python-file task**: run the 3-question router first. Entry point in
  `src/jobs/<domain>/` (argparse via `datalab.params.cli_params`, pure logic
  in the domain package `src/<catalog>_etl` with a unit test), copy the `customer_sales_export` job shape from
  `projects/customer_sales/resources/customer_sales_export.job.yml` (parameters from bundle
  variables, `environments` block, `permissions: ${var.job_permissions}`).
  `make lint test validate`.
- **Add a notebook task**: router first — only if a human must read the run.
  Source-format `.py` under `notebooks/<domain>/`, widgets named after the job
  parameters, resolved via `datalab.params.notebook_params`; copy the
  `customer_sales_quarantine_report` job shape (no trigger). `make lint test validate`.
- **Add or change an agent skill**: edit the canonical copy under
  `.agents/skills/<name>/SKILL.md` (create the dir for a new skill) — Cursor and
  Codex read it directly. Then run `make sync-skills` to regenerate the
  `.claude/skills` copy for Claude Code (symlinks are unreliable there) — never
  hand-edit it. `make check-skills lint` (CI runs `check-skills` and fails on
  drift). To make the skill available in Databricks Genie Code, run
  `make publish-genie-skills` (APPLY=1) to push it to the Workspace
  `.assistant/skills/`; Genie also auto-reads `AGENTS.md`.
- **Run / validate locally without Databricks**: `make run-local` materializes
  the medallion on sample data via OSS `spark-pipelines` (local profile —
  mind the fidelity gaps: no AUTO CDC dedup / dqx / Auto Loader); `make
  dry-run-local` just validates the graph. To check mapping/transforms/dqx on a
  LIVE cluster, `make validate-connect LAYER=<l> TABLE=<t> CONNECT_ARGS="--param
  datalab.catalog=… --param datalab.bronze_schema=…"` (isolated Databricks
  Connect overlay). Reference: the framework repo's FRAMEWORK.md "Run anywhere".
- **Add a dependency**: edit `pyproject.toml`, `make lock`, commit both files.
  For pipeline-runtime deps, remember the environment caching gotcha above.
- **Change deploy config**: edit `databricks.yml` / the domain's
  `resources/*.yml`, then `make validate` before pushing; update `docs/` if
  targets or variables moved.
- **Change access (RBAC/ABAC)**: workspace-resource permissions → `rbac.yml`
  (group + permission-level string vars; per-target overrides in its own
  `targets:` block, per-environment via `DATALAB_*_GROUP` repo variables → the
  `deploy-dab` `--var`); data grants → `scripts/bootstrap_uc.py` (provisions
  every registry domain catalog, each with its artifacts.wheels Volume for the
  framework wheel; catalogs/groups are RESOLVED from targets/ + rbac.yml via
  `scripts/domains.py` — nothing to keep in sync by hand), re-run
  `make bootstrap-uc`; row/column
  policies → add display-only SQL under the domain's `sql/abac/` following
  the conventions in `docs/ARCHITECTURE.md` — never execute them from CI or
  an agent session.
<!-- template-only:common-task-design start -->
- **Update the design (diagrams, images, overview)**: edit the diagrams.net
  (draw.io) source in `design/` — `02_implementation_end_to_end.drawio` when the
  implemented architecture moves (same PR), `01_design_config_driven_medallion.drawio`
  only when the design intent changes — then `make design` to re-export
  `design/images/*.png`, and refresh the customer-facing `design/OVERVIEW.md` if
  the narrative changed (flag `datalab-customer-overview.html` for out-of-band
  regeneration). Follow the `maintain-design-diagram` skill for band/colour
  conventions + the geometry check; full how-to in `docs/ARCHITECTURE.md`
  ("Editing the design diagrams"). `design/` is excluded from the deployed
  workspace files via the `sync.exclude` block in databricks.yml.
<!-- template-only:common-task-design end -->
- **Query Databricks from the agent (MCP)**: opt-in, dev-time. Authenticate the
  CLI (`databricks auth login --host <host>` → profile `diggi_dev_aws`), then in
  Claude Code approve the `databricks-sql` server from `.mcp.json` (Cursor:
  enable it under Settings → MCP). Ask the agent to preview a UC table before
  authoring its downstream artifact — the `query-databricks` skill governs
  when/how (READ-ONLY only; UC grants govern; single-writer invariant holds).
  Don't `uv add` the proxy (uvx-ephemeral). Full setup + adopter swaps +
  verification + fallback: `docs/AGENT_MCP.md`.
- **Open a pull request**: fill `.github/pull_request_template.md` into a body
  file and `gh pr create --body-file <file>` (or `--web`). Keep the
  `datalab-pr-template` marker and the `##` section headings — the hook + CI
  enforce them for every human/agent PR (dependabot PRs are the one
  exception: CI holds them to a separate verifiable bot contract instead —
  see Critical knowledge). Branch from `main`; the head branch is
  auto-deleted on merge (see "Branching & releases").

## Agent don'ts

- Don't use `import dlt`, `dlt.*` APIs, or hand-written MERGE/upsert logic in
  pipelines — use `pyspark.pipelines` + AUTO CDC (via `target.cdc` /
  `target.cdc_from_snapshot` in the artifact).
- Don't perform writes or actions inside dataset functions.
- Don't hardcode catalogs, schemas, hosts, or volume paths in pipeline code —
  use bundle variables + pipeline `configuration`.
- Don't rename fan-in/backfill flow names (or convert single-source ↔ fan-in)
  casually — flow names are streaming-checkpoint identities.
- Don't introduce poetry/pip-requirements workflows — deps are uv-only.
- Don't edit `uv.lock` by hand.
- Don't commit `.env`, workspace state (`.databricks/`), or `.venv`.
- Don't open a PR that bypasses the unified template.
- Don't make ANY change while `main` is checked out — first action of every
  task is `git switch -c <feature|fix|debug>/<slug>` from a fresh `main`
  (enforced by `branch_guard` + the pre-commit hook).
- Don't branch off a feature branch — new work branches from `main`.

## Security

- Secrets stay in `.env` (local) / GitHub Environment secrets (CI). Never
  commit them; `.gitignore` + the guards back this up.
- CI/CD uses GitHub OIDC — there is no long-lived Databricks secret in GitHub.
- Production data access is governed by Unity Catalog grants plus the bundle
  `permissions` variables (`pipeline_permissions`, `job_permissions`) defined
  in `rbac.yml`.
