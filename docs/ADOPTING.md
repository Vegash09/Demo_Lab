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

**Creating it in another organization?** Both paths are org-agnostic — point them
at any `<owner>` you can push to (`make new-adopter … OUT=…` then push, or
`gh repo create <other-org>/<customer>-datalab --template <owner>/datalab`). Two
things to know up front:

1. **Generating needs read access to this template repo** (it is private). The
   person running "Use this template" / `--template` must be able to read it.
2. **Generating copies FILES only.** Actions secrets, GitHub Environments, the
   OIDC federation policy, the **framework deploy key**, branch-protection rules,
   and the "template" flag itself do **not** carry over — you set them up fresh in
   the new repo (the checklist covers each). The new repo reads the private
   framework across the org boundary with its own credential — see
   [Accessing the private framework repo](#accessing-the-private-framework-repo-local--ci-cross-org).

## Adopter onboarding checklist

Copy this into the tracking issue for a new repo and fill the blanks. It covers
both the generator inputs and the post-generation environment facts the generator
cannot fill (those are the real gaps a first-timer hits). Step details are in the
sections below.

**Values to decide first**

| Value | Used for | Default / where |
|---|---|---|
| `<catalog>` | package `<catalog>_etl`, pipeline, folders, catalog name (lowercase) | — (required) |
| `<owner>/<repo>` | the new GitHub repo (any org you can push to) | — (required) |
| `<host>` (+ stage/prod hosts if different) | Databricks workspace URL per target | — (one host fills all three targets) |
| `<deploy-sp-app-id>` | CI/CD deploy service-principal application id (OIDC → Databricks) | — |
| `<reader>/<engineer>/<admin>` groups | RBAC + UC grants | default `<catalog>_readers/_engineers/_admins` |
| `<framework-tag>` | the `datalab` framework release to pin | default: this template's current pin |
| `<warehouse-id>`, `<cli-profile>` | one-time UC bootstrap | — |
| framework read-access credential | how this repo's CI **and** your devs clone the private framework | deploy key (default) / PAT / vendored wheel |

**Steps**

- [ ] **0. Prereqs** — read access to `dediggibyte/datalab-framework`; a Databricks
  workspace + a deploy SP; `gh` + `databricks` CLI authenticated; `uv`; Java 17+.
- [ ] **1. Generate** — `make new-adopter CATALOG=<catalog> OUT=../<catalog>-datalab
  HOST=<host> DEPLOY_SP=<deploy-sp-app-id>` (add `*_GROUP=` / `FRAMEWORK_TAG=` to
  override defaults). Leaving `HOST`/`DEPLOY_SP` blank writes clearly-marked
  placeholders — fill them before deploy.
- [ ] **2. Local gates** — `cd ../<catalog>-datalab && git init -b main && make lock
  install && make validate-configs lint test`. *(`make lock install` clones the
  private framework — your machine needs framework read access; see below.)*
- [ ] **3. Stage/prod hosts** — if stage/prod are **different** workspaces, edit
  `targets/stage.yml` / `targets/prod.yml` (the generator writes one `--host` into
  all three).
- [ ] **4. Create the GitHub repo** — `gh repo create <owner>/<repo> --source=.
  --private --push` (or generate from the template in the target org).
- [ ] **5. Framework access for CI** — the framework-repo admin adds a **per-adopter
  read-only deploy key**; store its private half as the `DATALAB_FRAMEWORK_DEPLOY_KEY`
  **repo-/org-level** secret (NOT per-environment).
- [ ] **6. Databricks auth (OIDC)** — GitHub Environments `dev`/`stage`/`prod` with
  `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID`; an OIDC federation policy on the SP
  with subject `repo:<owner>/<repo>:environment:<target>` (one per target).
- [ ] **7. UC bootstrap** — ensure the groups exist, then `make bootstrap-uc
  TARGET=dev WAREHOUSE_ID=<warehouse-id> PROFILE=<cli-profile>` (`SKIP_CATALOGS=1`
  if catalogs exist or the metastore uses Default Storage).
- [ ] **8. Publish the framework wheel** — `make publish-wheel TARGET=dev APPLY=1`
  (uploads into `<catalog>.artifacts.wheels`).
- [ ] **9. Deploy + run** — `make deploy && make run`; confirm `bronze.events_raw`
  materializes.
- [ ] **10. Extend** — add real tables with the `author-ldp-artifact` skill.

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

## Accessing the private framework repo (local + CI, cross-org)

`datalab` lives in the **private** `dediggibyte/datalab-framework` repo. **Every**
place that resolves the git dep needs read access to that repo:

| Where | Command | Why it clones the framework |
|---|---|---|
| your laptop | `make lock install` | `uv` resolves the git dep into `.venv` |
| your laptop | `make publish-wheel` | builds the wheel via `pip wheel "datalab @ git+…"` |
| CI | `uv sync --frozen` | lint/test/validate-configs import `datalab` |
| CD | publish-wheel step **+** `bundle deploy` | builds + resolves the framework wheel |

### Two different credentials — don't conflate them

This is the crux of "can GitHub OIDC pull the framework into the wheel?" — **no.**
Two unrelated auth concerns are in play:

| Concern | Mechanism | Direction | Owned by |
|---|---|---|---|
| Read the framework **source** | read-only SSH **deploy key** (or PAT / GitHub App) | GitHub Actions **or a dev** → `github.com/dediggibyte/datalab-framework` | framework-repo admin mints one per adopter |
| **Deploy** to Databricks | GitHub **OIDC** federation | GitHub Actions → **your own** Databricks workspace | each adopter (their own SP) |

> **GitHub OIDC authenticates Actions to _Databricks_, not to GitHub.** It is a
> cloud workload-identity federation — it cannot grant one GitHub repo read access
> to another **private** GitHub repo. The built-in `GITHUB_TOKEN` is likewise
> scoped to the adopter's own repo only. So neither OIDC nor `GITHUB_TOKEN` can
> "take the framework from our repo and add it to the wheel" — the wheel build
> (`pip wheel "datalab @ git+…"`) and `uv sync` both need a **git** credential:
> a deploy key, a PAT, or a GitHub App token.

### CI/CD access — works across orgs (deploy key)

A deploy key is **repo-scoped, not org-scoped**, so the same mechanism this
template uses works from any adopter org. Per adopter repo (the framework-repo
admin does the first two):

1. Generate a read-only keypair: `ssh-keygen -t ed25519 -f adopter_key -N "" -C "<repo> framework read"`.
2. Add the **public** half (`adopter_key.pub`) as a **read-only deploy key** on
   `dediggibyte/datalab-framework` (Settings → Deploy keys). GitHub requires each
   deploy-key public key to be unique across repos, so **mint a fresh key per
   adopter** — one repo can hold many deploy keys.
3. In the adopter repo, store the **private** half as the
   `DATALAB_FRAMEWORK_DEPLOY_KEY` Actions secret — **repo- or org-level, not
   per-environment** (the CI `lint + test` job declares no `environment:`, so it
   only sees repo/org secrets).

The CI/CD workflows already carry the "Auth for the private datalab-framework git
dependency" step (`common-ci-steps.yml` / `common-cd-steps.yml`): it loads the
key and rewrites just that repo's HTTPS URL to SSH
(`git config url."git@github.com:…".insteadOf "https://github.com/…"`) so `uv` and
`pip wheel` clone over the key. Nothing to author — generating the repo copies
these workflows; you only supply the secret. (Full mechanics + rotation:
[CICD.md → Private framework dependency](CICD.md#private-framework-dependency-git-auth).)

**Alternatives** when a deploy key doesn't fit the org's policy:

- **Fine-grained PAT / machine user** with read on `datalab-framework`, stored as
  the same secret and used by a credential-helper step instead of the SSH rewrite.
- **GitHub App** installed on both orgs, minting short-lived tokens — best at
  scale (no key to rotate per adopter).
- **Decouple from source entirely** (below) if you can't grant any read access.

### Local developer machines — yes, every dev

`make lock install` (and `make publish-wheel`) clone the framework, so **each
developer needs read access** to `dediggibyte/datalab-framework`. The clean way is
to grant the dev team **Read** on that repo and let normal git auth handle it — no
shared keys:

- **HTTPS (simplest):** `gh auth login` + `gh auth setup-git` (or any credential
  helper) authenticates the pinned `https://github.com/dediggibyte/datalab-framework.git`
  URL directly.
- **SSH:** add the same rewrite locally —
  `git config --global url."git@github.com:dediggibyte/datalab-framework".insteadOf "https://github.com/dediggibyte/datalab-framework"` — with your own SSH key.

Deploy keys are for machines/CI, not people; don't hand them to developers. A
per-dev fine-grained PAT in the credential store also works.

### If you can't share source access (decouple)

To avoid giving an adopter org any read access to the framework source, deliver
the framework as an **artifact** instead of a git dep:

- hand them the built `datalab-<ver>-py3-none-any.whl` to upload into their
  `<catalog>.artifacts.wheels` Volume (serverless already installs from there —
  `var.datalab_wheel`), and
- publish the same wheel to an index they can read (GitHub Packages / a private
  PyPI) and point `[tool.uv.sources] datalab` at that index instead of git for
  local dev + CI.

Or, simplest of all, make `datalab-framework` **public** — then no credential is
needed anywhere. These are policy choices; the deploy-key path above is the
established default.

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
