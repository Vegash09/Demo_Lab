# Adopt the datalab framework in your own repo

This is the repo/bundle/framework-consumption setup the old monorepo used to
hide. It covers standing up a **repo** on the framework — pinning the framework,
publishing its wheel, provisioning Unity Catalog, and laying out a domain. To
author your first **table** once the repo stands, follow
[GETTING_STARTED.md](GETTING_STARTED.md); this doc wires your repo to the
framework.

## Quick start: stand up a new customer repo

This repo doubles as the starting point for a new single-customer repo. Both
paths produce the same thing — a clean **root-level single-domain** adopter repo
(`config/<catalog>/`, `src/<catalog>_etl/`, `resources/*.yml`) with one minimal
Auto Loader bronze table — then you extend it with the `author-ldp-artifact`
skill. The rest of this doc is the reference for what that conversion does.

**Option A — deterministic generator (one command).** Run from a clone of THIS
repo; it copies only git-tracked files (never secrets/state/build output), drops
the reference domains, writes the minimal domain, and rewrites every repo-level
file:

```bash
make new-adopter CATALOG=<catalog> OUT=../<catalog>-datalab \
    HOST=https://<workspace> DEPLOY_SP=<app-id>
cd ../<catalog>-datalab && git init -b main && make lock install \
    && make validate-configs lint test
# then publish it:  gh repo create <owner>/<catalog>-datalab --source=. --private --push
```

**Option B — GitHub template + the `bootstrap-adopter-repo` skill.** This repo is
a **GitHub template repository**; generate from it, then run the skill in the
clone to do the same conversion (handy when you want an agent to customize as it
goes):

```bash
gh repo create <owner>/<customer>-datalab --template <owner>/datalab --private --clone ../<customer>-datalab
cd ../<customer>-datalab    # then run the bootstrap-adopter-repo skill
```

(One-time, repo admin: `gh repo edit <owner>/datalab --template` enables the
template flag.)

## What this is / how the pieces relate

The reusable framework was split out of this repo. Two repos now collaborate:

| Repo | What it is | You edit it to… |
|---|---|---|
| [`dediggibyte/datalab-framework`](https://github.com/dediggibyte/datalab-framework) | the **library** (`datalab`): Pydantic models, SDP adapters, dqx engine, devtools, param helpers — zero domain code | change framework behavior (rare); reference is its `docs/FRAMEWORK.md` |
| this repo (`datalab`, internally the `datalab-projects` uv project) | the **domains + deploy bundle** that CONSUMES the framework — `databricks.yml` + reference domains under `projects/` | add/change tables, jobs, notebooks; deploy |

This repo has **no `src/datalab`** — the framework is a dependency, consumed two
ways (below). Your adopter repo has the same shape, with your domain at the
**root** (`config/<catalog>/`, `src/<catalog>_etl/`, `resources/`) instead of
under `projects/`.

## The two consumption paths

| Path | Used by | Mechanism |
|---|---|---|
| **git dependency** | local dev + CI | `[tool.uv.sources] datalab = { git=…, tag=vX.Y.Z }` in the root `pyproject.toml`; uv resolves it into the shared `.venv` so `make lint/test/validate-configs` exercise the framework |
| **UC-Volume wheel** | Databricks serverless | `var.datalab_wheel` — an absolute `/Volumes/<your_catalog>/artifacts/wheels/datalab-<ver>-py3-none-any.whl` (the wheel lives in **your own catalog**, no separate catalog to provision), listed in every pipeline/job `environment.dependencies` |

**Why a wheel and not `--editable`:** serverless pipeline/job environments do
**not** honor an `--editable` install of the synced workspace files — the package
never lands on the runtime path and the pipeline fails at import with
`ModuleNotFoundError: No module named 'datalab'`. A versioned wheel from a UC
Volume is the delivery mechanism. This repo BUILDS that wheel **from the pinned
git dep** and PUBLISHES it into each project catalog's own `artifacts.wheels`
volume on every deploy (see below).

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
     default: "0.3.0"        # → datalab-0.3.0-py3-none-any.whl on each project catalog's artifacts.wheels volume
   ```

`var.datalab_wheel` derives the full path from `var.catalog` +
`var.datalab_version`, so you never hand-write the wheel path (this repo's second
domain mirrors the split: `var.sales_datalab_wheel` derives from
`var.sales_catalog`). **Upgrading the framework = bump the git tag AND
`datalab_version`, then `make lock` + `make publish-wheel`** (see "Upgrading the
framework later").

## Publish the framework wheel from your repo

`make publish-wheel` builds the framework wheel **from the pinned git dep** (via
`pip wheel "datalab @ git+…@<tag>" --no-deps`) and uploads it into **each project
catalog's** `artifacts.wheels` UC Volume (`customer_sales.artifacts.wheels`,
`sales.artifacts.wheels` in this repo) — **one upload per project catalog** (the
wheel rides in the same catalog as the domain it serves, not a separate shared
catalog):

```bash
make publish-wheel TARGET=dev            # dry run — builds + prints what it would upload
make publish-wheel TARGET=dev APPLY=1    # actually uploads into each project catalog's volume
```

**Ordering constraint:** the wheel the version references must exist in the
project catalog's `artifacts.wheels` volume **before** any pipeline first runs
(or the env install fails). CI enforces
this — the `deploy-dab` action runs the publish step **before** `bundle deploy`
on every deploy. `bundle deploy` (and CI) needs `uv` on PATH for this.

## Provision Unity Catalog once

`make bootstrap-uc` is **out-of-band of the bundle** by design, so
`bundle destroy` never touches catalogs/schemas/volumes/grants. It is
idempotent (`CREATE … IF NOT EXISTS` / re-runnable `GRANT`) and run once per
target before the first deploy:

```bash
make bootstrap-uc TARGET=dev                                          # dry run — prints the SQL
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<id> PROFILE=<cli-profile>  # applies it
```

`PROFILE=<cli-profile>` picks the workspace (the SDK otherwise uses your DEFAULT
profile — set it to the one the bundle target deploys to). If your domain
catalogs already exist, or your metastore uses **Default Storage** (where SQL
`CREATE CATALOG` needs an explicit location), create the catalogs in the UI first
and add `SKIP_CATALOGS=1` — bootstrap then just ensures the schemas, the
`artifacts.wheels` volume, and grants.

It creates, per target — **no separate artifacts catalog**; the framework wheel
rides in each domain's own catalog:

- each **domain catalog** (`customer_sales` + `sales` in this repo →
  `CATALOGS`; just `<your_catalog>` for a single-domain adopter):
  `bronze`/`silver`/`gold` schemas, the edge-lane `landing`/`exports` volumes
  (volume catalogs only), persona grants, **and an `artifacts.wheels` UC Volume**
  for the framework wheel — the deploy SP writes to it via its catalog-level ALL,
  and the domain's pipeline/job run-as gets **READ VOLUME** so it can install the
  wheel (the install fails if that read grant is missing).

Keep the script's `CATALOGS` / `GROUPS` dicts in sync with the catalog vars in
`targets/` and the group names in `rbac.yml` (see AGENTS.md "Change access").

## Lay out / copy a reference domain

Copy a reference domain to your repo **root** and rename every `customer_sales`
token to your catalog name. Two starting points:

- `projects/customer_sales/` — the **full** adoption: pipeline + edge jobs +
  triage notebook + tests + ABAC SQL.
- `projects/sales/` — **pipeline-only**: silver (AUTO CDC SCD1 + dqx) + gold MVs
  over pre-existing bronze tables; no edge jobs/notebooks.

The layout transfers 1:1 (`projects/README.md` has the full mapping table;
naming contract: [NAMING.md](NAMING.md)). Adopters put these at the repo ROOT;
this reference repo keeps them under `projects/<catalog>/`:

| In `projects/customer_sales/` | In your repo |
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
   members = ["projects/customer_sales", "projects/sales"]   # → add your domain dir

   [tool.uv.sources]
   <catalog>_etl = { workspace = true }
   ```

   The domain's own `pyproject.toml` builds a hatchling wheel from
   `src/<catalog>_etl` and declares `dependencies = []` — `datalab` is **not** a
   runtime dep (serverless has no index to resolve it; the framework is
   environment-provided via the Volume wheel). Add it to `[dependency-groups].dev`
   too so the local gates import it.

2. **Wire each `resources/*.yml` environment** to install both wheels — the
   framework wheel from this project's own catalog volume + this domain's wheel
   (paths relative to the resource file):

   ```yaml
   environment:
     environment_version: "4"
     dependencies:
       - ${var.datalab_wheel}                       # framework wheel from THIS project's catalog volume
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
framework wheel before its deploy — so the first run finds both wheels in the
project catalog's `artifacts.wheels` volume.

## Upgrading the framework later

1. Bump the git **tag** in `pyproject.toml` `[tool.uv.sources] datalab` **and**
   `var.datalab_version` in `variables/medallion.yml` — **in lockstep**.
2. `make lock` (refreshes `uv.lock` — CI runs `uv sync --frozen` and fails on
   drift; commit both files).
3. `make publish-wheel TARGET=<t> APPLY=1` — build the new version from the new
   tag and upload it into each project catalog's `artifacts.wheels` volume.
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
