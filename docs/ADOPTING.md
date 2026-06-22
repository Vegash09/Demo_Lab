# Adopt the datalab framework in your own repo

This is the repo/bundle/framework-consumption setup the old monorepo used to
hide. It covers standing up a **repo** on the framework — pinning the framework,
publishing its wheel, provisioning Unity Catalog, and laying out a domain. To
author your first **table** once the repo stands, follow
[GETTING_STARTED.md](GETTING_STARTED.md); this doc wires your repo to the
framework.

## What this is / how the pieces relate

The reusable framework was split out of this repo. Two repos now collaborate:

| Repo | What it is | You edit it to… |
|---|---|---|
| [`dediggibyte/datalab-framework`](https://github.com/dediggibyte/datalab-framework) | the **library** (`datalab`): Pydantic models, SDP adapters, dqx engine, devtools, param helpers — zero domain code | change framework behavior (rare); reference is its `docs/FRAMEWORK.md` |
| this repo (`datalab`, internally the `datalab-examples` uv project) | the **domains + deploy bundle** that CONSUMES the framework — `databricks.yml` + reference domains under `examples/` | add/change tables, jobs, notebooks; deploy |

This repo has **no `src/datalab`** — the framework is a dependency, consumed two
ways (below). Your adopter repo has the same shape, with your domain at the
**root** (`config/<catalog>/`, `src/<catalog>_etl/`, `resources/`) instead of
under `examples/`.

## The two consumption paths

| Path | Used by | Mechanism |
|---|---|---|
| **git dependency** | local dev + CI | `[tool.uv.sources] datalab = { git=…, tag=vX.Y.Z }` in the root `pyproject.toml`; uv resolves it into the shared `.venv` so `make lint/test/validate-configs` exercise the framework |
| **UC-Volume wheel** | Databricks serverless | `var.datalab_wheel` — an absolute `/Volumes/<datalab_artifacts_catalog>/framework/wheels/datalab-<ver>-py3-none-any.whl`, listed in every pipeline/job `environment.dependencies` |

**Why a wheel and not `--editable`:** serverless pipeline/job environments do
**not** honor an `--editable` install of the synced workspace files — the package
never lands on the runtime path and the pipeline fails at import with
`ModuleNotFoundError: No module named 'datalab'`. A versioned wheel from a UC
Volume is the delivery mechanism. This repo BUILDS that wheel **from the pinned
git dep** and PUBLISHES it to a shared `datalab_artifacts` catalog on every
deploy (see below).

## Pin the framework version

Two places must reference the **same** framework release — keep them in lockstep:

1. `pyproject.toml` → `[tool.uv.sources] datalab` git **tag** (the git dep):

   ```toml
   [tool.uv.sources]
   datalab = { git = "https://github.com/dediggibyte/datalab-framework.git", tag = "v0.3.0" }
   ```

   (`datalab` is listed under `[dependency-groups].dev`; the root project itself
   is `package = false` — a uv workspace + dev-env, not a built package.)

2. `variables/medallion.yml` → `var.datalab_version` (the wheel filename):

   ```yaml
   datalab_version:
     default: "0.3.0"        # → datalab-0.3.0-py3-none-any.whl on the shared Volume
   ```

`var.datalab_wheel` derives the full path from `var.datalab_artifacts_catalog` +
`var.datalab_version`, so you never hand-write the wheel path. **Upgrading the
framework = bump the git tag AND `datalab_version`, then `make lock` +
`make publish-wheel`** (see "Upgrading the framework later").

## Publish the framework wheel from your repo

`make publish-wheel` builds the framework wheel **from the pinned git dep** (via
`pip wheel "datalab @ git+…@<tag>" --no-deps`) and uploads it to this target's
shared `datalab_artifacts` catalog `framework.wheels` UC Volume — **one upload
serves every domain** (one source of truth, not per-domain):

```bash
make publish-wheel TARGET=dev            # dry run — builds + prints what it would upload
make publish-wheel TARGET=dev APPLY=1    # actually uploads to the shared Volume
```

**Ordering constraint:** the wheel the version references must exist on the
Volume **before** any pipeline first runs (or the env install fails). CI enforces
this — the `deploy-dab` action runs the publish step **before** `bundle deploy`
on every deploy. `bundle deploy` (and CI) needs `uv` on PATH for this.

## Provision Unity Catalog once

`make bootstrap-uc` is **out-of-band of the bundle** by design, so
`bundle destroy` never touches catalogs/schemas/volumes/grants. It is
idempotent (`CREATE … IF NOT EXISTS` / re-runnable `GRANT`) and run once per
target before the first deploy:

```bash
make bootstrap-uc TARGET=dev                                    # dry run — prints the SQL
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<sql-warehouse-id>    # applies it
```

It creates, per target:

- the **shared `datalab_artifacts` catalog** + `framework.wheels` UC Volume
  (`scripts/bootstrap_uc.py` → `ARTIFACTS_CATALOGS`), granting **READ VOLUME** to
  every pipeline/job run-as identity so they can install the wheel — the Volume
  must be readable by every run across all domains or the install fails;
- each **domain catalog** (`customer_sales` + `sales` in this repo →
  `CATALOGS`): `bronze`/`silver`/`gold` schemas, the edge-lane
  `landing`/`exports` volumes (volume catalogs only), and persona grants.

Keep the script's `CATALOGS` / `ARTIFACTS_CATALOGS` / `GROUPS` dicts in sync with
the catalog vars in `targets/` and the group names in `rbac.yml` (see AGENTS.md
"Change access").

## Lay out / copy a reference domain

Copy a reference domain to your repo **root** and rename every `customer_sales`
token to your catalog name. Two starting points:

- `examples/customer_sales/` — the **full** adoption: pipeline + edge jobs +
  triage notebook + tests + ABAC SQL.
- `examples/sales/` — **pipeline-only**: silver (AUTO CDC SCD1 + dqx) + gold MVs
  over pre-existing bronze tables; no edge jobs/notebooks.

The layout transfers 1:1 (`examples/README.md` has the full mapping table;
naming contract: [NAMING.md](NAMING.md)). Adopters put these at the repo ROOT;
this reference repo keeps them under `examples/<catalog>/`:

| In `examples/customer_sales/` | In your repo |
|---|---|
| `config/customer_sales/` | `config/<catalog>/` (`domain.yml` + one `<schema>/<table>.yml` per table) |
| `src/customer_sales_etl/` | `src/<catalog>_etl/` (3-line entrypoint, `@transform` fns, dqx checks) |
| `src/jobs/customer_sales/` | `src/jobs/<catalog>/` (python-file lane) |
| `notebooks/customer_sales/` | `notebooks/<catalog>/` (notebook lane) |
| `resources/*.yml` | `resources/*.yml` (paths inside are relative — they move as is) |

Then wire the domain up in two places outside the copied folder:

1. **Register it as a uv-workspace member** so it builds its own `<catalog>_etl`
   wheel. In the root `pyproject.toml`:

   ```toml
   [tool.uv.workspace]
   members = ["examples/customer_sales", "examples/sales"]   # → add your domain dir

   [tool.uv.sources]
   <catalog>_etl = { workspace = true }
   ```

   The domain's own `pyproject.toml` builds a hatchling wheel from
   `src/<catalog>_etl` and declares `dependencies = []` — `datalab` is **not** a
   runtime dep (serverless has no index to resolve it; the framework is
   environment-provided via the Volume wheel). Add it to `[dependency-groups].dev`
   too so the local gates import it.

2. **Wire each `resources/*.yml` environment** to install both wheels — the
   shared framework wheel + this domain's wheel (paths relative to the resource
   file):

   ```yaml
   environment:
     environment_version: "4"
     dependencies:
       - ${var.datalab_wheel}                       # shared framework wheel (UC Volume)
       - ../../../dist/<catalog>_etl-*.whl          # this domain's wheel (bundle-built)
   ```

   Point the pipeline's `configuration:` `datalab.config_dir` at your config dir
   (`${workspace.file_path}/config/<catalog>` in an adopter repo). `databricks.yml`'s
   `include:` glob already picks up `resources/*.yml`.

## Validate → deploy → run

Same gates CI runs:

```bash
make install                          # uv sync → .venv (resolves the framework git dep)
make validate-configs lint test       # pydantic + dqx · ruff · pytest (local Spark, Java 17+)
make validate                         # databricks bundle validate -t dev
make deploy                           # validate + bundle deploy -t dev
make run                              # refresh the customer_sales_etl pipeline on dev
```

`make deploy` builds the domain wheels (needs `uv` on PATH) and CI publishes the
framework wheel before its deploy — so the first run finds both wheels on the
Volume.

## Upgrading the framework later

1. Bump the git **tag** in `pyproject.toml` `[tool.uv.sources] datalab` **and**
   `var.datalab_version` in `variables/medallion.yml` — **in lockstep**.
2. `make lock` (refreshes `uv.lock` — CI runs `uv sync --frozen` and fails on
   drift; commit both files).
3. `make publish-wheel TARGET=<t> APPLY=1` — build the new version from the new
   tag and upload it to the shared Volume.
4. Refresh the vendored `schemas/*.json` if the framework's models changed —
   they are generated **in the framework repo** (its
   `scripts/export_config_schema.py`) and copied here for editor/config
   validation; regenerate there and copy the JSON over.
5. Redeploy (`make deploy`, or merge → CI).

**Caching gotcha:** pipeline/job environments cache dependencies. A new framework
version may not appear until the environment rebuilds — trigger a full pipeline
restart (publishing a new version filename forces this) if a change doesn't show
up.

## Where to go next

- [GETTING_STARTED.md](GETTING_STARTED.md) — author your first table end to end.
- [NAMING.md](NAMING.md) — the folder ↔ UC namespace convention.
- [CICD.md](CICD.md) — GitHub OIDC CI/CD, dev/stage/prod promotion.
- Framework reference (authoring fields, SDP capability matrix):
  [`datalab-framework/docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md).
  The local `docs/FRAMEWORK.md` is a thin pointer to it.
- [AGENTS.md](../AGENTS.md) — conventions, gotchas, protected-file protocol.
