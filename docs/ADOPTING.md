# Adopt the datalab framework in your own repo

This is the repo/bundle/framework-consumption setup the old monorepo used to
hide. It covers standing up a **repo** on the framework — pinning the framework,
publishing its wheel, provisioning Unity Catalog, and laying out a domain.

> **Just want the ordered checklist?** [NEW_ADOPTER.md](NEW_ADOPTER.md) is the
> step-by-step path (prerequisites → generate → convert → wire → deploy) — this
> doc is the *reference* behind it. To author your first **table** once the
> repo stands, follow [GETTING_STARTED.md](GETTING_STARTED.md).

<!-- template-only:adopting-quick-start start -->
## Quick start: stand up a new customer repo

This repo doubles as the starting point for a new single-customer repo. Both
paths produce the same thing — a clean **root-level single-domain** adopter repo
(`config/<catalog>/`, `src/<catalog>_etl/`, `resources/*.yml`) with one minimal
Auto Loader bronze table — then you extend it with the `author-ldp-artifact`
skill. The rest of this doc is the reference for what that conversion does.

Both options run the SAME deterministic engine (`scripts/scaffold_adopter.py`),
so the adopter always matches the template structure and **every**
workspace-specific surface is repointed in one shot — per-target hosts and
catalogs, RBAC groups, deploy SP, and the read-only MCP grounding config
(`.mcp.json` / `.cursor/mcp.json`: SQL warehouse id + CLI profile). Never
hand-edit the conversion — that is what drifts (a `config/<catalog>_databricks_prod`
folder, an `.mcp.json` still on the template's warehouse). `<catalog>` is the
**base** name — no `_dev`/`_stage`/`_prod` suffix (the bundle appends the env per
target); the engine rejects a suffixed name.

**What the new repo carries is a choice.** The configurator's form asks, and the
flags / make variables set:

| Choice | Flag · make variable | Options (default) |
|---|---|---|
| Coding agents | `--agents` · `AGENTS=` | `claude`, `codex`, `cursor`, `genie` — any subset, `all` or `none` (all four) |
| Components | `--components` · `COMPONENTS=` | `docs`, `design`, `schemas`, `local-dev`, `githooks`, `pr-template`, `dependabot`, `framework-bot`, `mcp` — a list, `all`, `none`, or `+x`/`-x` edits of the defaults (all but `design`) |
| Environments | `--host`, `--host-stage`, `--host-prod` · `HOST=`, `HOST_STAGE=`, `HOST_PROD=`; `--catalog-{dev,stage,prod}` · `CATALOG_DEV=` … | one workspace for all three targets; `<catalog>`, `<catalog>_stage`, `<catalog>_prod` |
| Customer | `--customer`, `--description`, `--repo` · `CUSTOMER=`, `DESCRIPTION=`, `REPO=` | derived from the catalog; the repo's git origin |

Each agent brings only its own harness (`.agents/skills` ships with any of
them), and a component that is left out takes its files, make targets, CI steps
and doc passages with it — see [What each choice ships](#what-each-choice-ships).
Every answer is recorded in the new repo's `.datalab-adopter.json`, and
`ANSWERS=<file>` replays it (e.g. to regenerate with a newer template and diff).

**Option A — GitHub template + `make configure-adopter` (convert in place).** This
repo is a **GitHub template repository**; generate from it, then convert the clone
in place. `configure-adopter` walks the form (identity → workspace & environments
→ access → coding agents → components → framework), shows what will ship and what
is left out, and asks you to confirm; placeholders you leave are printed as
fill-before-deploy TODOs. Prefill any value to skip its question; `YES=1` (with
`CATALOG=` or `ANSWERS=`) runs it fully non-interactive — or let the
`bootstrap-adopter-repo` skill drive it:

```bash
gh repo create <owner>/<customer>-datalab --template dediggibyte/datalab --private --clone
cd <customer>-datalab                  # --clone is a boolean flag: it clones into ./<customer>-datalab
make configure-adopter             # the form; prefill e.g. CATALOG=<catalog> AGENTS=claude,cursor COMPONENTS=+design
make lock install && make validate-configs lint test
```

(One-time, template admin: `gh repo edit dediggibyte/datalab --template` enables
the template flag.)

**Option B — `make new-adopter` (fresh sibling repo).** Run from a clone of THIS
repo; copies only git-tracked files (never secrets/state/build output) into a new
sibling dir. With `CATALOG=` (or `ANSWERS=`) it runs non-interactively; with
neither it walks the same form:

```bash
make new-adopter CATALOG=<catalog> OUT=../<catalog>-datalab \
    HOST=https://<workspace> WAREHOUSE_ID=<id> DEPLOY_SP=<app-id> AGENTS=claude,genie
cd ../<catalog>-datalab && git init -b main && make lock install \
    && make validate-configs lint test
# then publish it:  gh repo create <owner>/<catalog>-datalab --source=. --private --push
```

Both build the adopter in a scratch directory and write it only after every
patch and doc check passed — a failure never leaves a half-converted clone — and
both refuse to run inside an already-generated adopter.

**Creating it in another organization?** Both paths are org-agnostic — point them
at any `<owner>` you can push to (`make new-adopter … OUT=…` then push, or
`gh repo create <other-org>/<customer>-datalab --template <owner>/datalab`). Two
things to know up front:

1. **Generating needs read access to this template repo** (it is private). The
   person running "Use this template" / `--template` must be able to read it.
2. **Generating copies FILES only.** Actions secrets, GitHub Environments, the
   OIDC federation policy, the **framework App id/key**, branch-protection rules,
   and the "template" flag itself do **not** carry over — you set them up fresh in
   the new repo (the checklist covers each). The new repo reads the private
   framework across the org boundary with its own credential — see
   [Accessing the private framework repo](#accessing-the-private-framework-repo-local--ci-cross-org).

## What each choice ships

| Choice | Ships only when chosen |
|---|---|
| `claude` | `CLAUDE.md`; `.claude/` — settings (read-only `make` grants, regenerated per repo), the protected-files hook, the generated `.claude/skills` copy; `scripts/sync_skills.py` + `make sync-skills` / `check-skills` |
| `codex` | `.codex/hooks.json` (it runs the shared guard scripts) |
| `cursor` | `.cursor/` rules and hooks (and `mcp.json` with `mcp`) |
| `genie` | `scripts/publish_genie_skills.py` + `make publish-genie-skills` |
| any agent | `.agents/skills/` (the canonical skills); with claude/codex/cursor also the shared guards in `.cursor/hooks/` and `scripts/check_agent_settings.py` |
| `docs` | `docs/` — NEW_ADOPTER, ADOPTING, GETTING_STARTED, NAMING, CICD, ARCHITECTURE (+ AGENT_MCP with `mcp`); without it, references point at this template repo's copies |
| `design` | a `design/` package generated for the customer - OVERVIEW.md, the estate map + design-spec diagrams GENERATED from the repo through the drawio-architecture-designer kit, and `design/PIPELINES.md` rendered from `config/` (`make design`; CI runs `make check-design`, which also fails on a hand-edited diagram) |
| `schemas` | `schemas/` + `make sync-schemas` / `check-schemas`, and the `$schema` editor header in each config file |
| `local-dev` | `sample_data/`, `make run-local` / `dry-run-local` / `validate-connect`, `scripts/validate_connect.py` |
| `githooks` | `.githooks/pre-commit` + `make enable-githooks` / `commit-protected` |
| `pr-template` | `.github/pull_request_template.md`, its CI check, and the agents' PR-creation guard |
| `dependabot` | `.github/dependabot.yml` |
| `framework-bot` | `.github/workflows/framework-bump.yml` |
| `mcp` | `.mcp.json` / `.cursor/mcp.json`, `docs/AGENT_MCP.md`, the `query-databricks` skill — needs `claude` or `cursor` |

Always shipped: the domain (`config/`, `src/`, `resources/`, `tests/`), the
bundle (`databricks.yml`, `variables/`, `targets/`, `rbac.yml`),
`pyproject.toml`, the `Makefile`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, the
CI/CD workflows, and the operational scripts (`bootstrap_uc`, `publish_wheel`,
`domains`, `check_lockstep`, `bump_framework`, `check_sync_lists`). Never
shipped: the reference domains, `omnigent/`, and the scaffold tooling itself
(`scaffold_adopter.py`, its doc checks, the `bootstrap-adopter-repo` skill) —
an adopter is not a template.

## Adopter onboarding checklist

Moved: **[NEW_ADOPTER.md](NEW_ADOPTER.md)** is the single ordered checklist
(prerequisites with who-provides-what, one command per step, success signals,
failure pointers). This doc used to carry a second copy; two competing
checklists is how first-timers got lost. Everything below is the *reference*
the checklist links into.

One checklist step worth restating here because the generator cannot do it: on
Option B (`make new-adopter` into a sibling dir) the repo does not exist on
GitHub yet — publish it with `gh repo create <owner>/<repo> --source=. --private
--push` (Option A's template generation already created it). A workspace that
changes later (stage or prod moving to its own workspace) is a one-line edit of
`targets/stage.yml` / `targets/prod.yml`.
<!-- template-only:adopting-quick-start end -->

## What this is / how the pieces relate

The reusable framework was split out of this repo. Two repos now collaborate:

| Repo | What it is | You edit it to… |
|---|---|---|
| [`dediggibyte/datalab-framework`](https://github.com/dediggibyte/datalab-framework) | the **library** (`datalab`): Pydantic models, SDP adapters, dqx engine, devtools, param helpers — zero domain code | change framework behavior (rare); reference is its `docs/FRAMEWORK.md` |
<!-- template-only:adopting-repo-row start -->
| this repo (`datalab`, internally the `datalab-projects` uv project) | the **domains + deploy bundle** that CONSUMES the framework — `databricks.yml` + reference domains under `projects/` | add/change tables, jobs, notebooks; deploy |
<!-- template-only:adopting-repo-row end -->

<!-- template-only:adopting-no-src start -->
This repo has **no `src/datalab`** — the framework is a dependency, consumed two
ways (below). Your adopter repo has the same shape, with your domain at the
**root** (`config/<catalog>/`, `src/<catalog>_etl/`, `resources/`) instead of
under `projects/`.
<!-- template-only:adopting-no-src end -->

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
| your laptop | `make publish-wheel` | shallow-clones the pinned tag to build the wheel |
| CI | `uv sync --frozen` | lint/test/validate-configs import `datalab` |
| CD | publish-wheel step **+** `bundle deploy` | builds + resolves the framework wheel |

### Two different credentials — don't conflate them

This is the crux of "can GitHub OIDC pull the framework into the wheel?" — **no.**
Two unrelated auth concerns are in play:

| Concern | Mechanism | Direction | Owned by |
|---|---|---|---|
| Read the framework **source** | read-only **GitHub App** token (or PAT / vendored wheel) | GitHub Actions **or a dev** → `github.com/dediggibyte/datalab-framework` | framework-repo admin runs one App; adopters store its id/key |
| **Deploy** to Databricks | GitHub **OIDC** federation | GitHub Actions → **your own** Databricks workspace | each adopter (their own SP) |

> **GitHub OIDC authenticates Actions to _Databricks_, not to GitHub.** It is a
> cloud workload-identity federation — it cannot grant one GitHub repo read access
> to another **private** GitHub repo. The built-in `GITHUB_TOKEN` is likewise
> scoped to the adopter's own repo only. So neither OIDC nor `GITHUB_TOKEN` can
> "take the framework from our repo and add it to the wheel" — the wheel build
> (a shallow `git clone` of the pinned tag) and `uv sync` both need a **git**
> credential: a GitHub App token, a PAT, or a vendored wheel.

### CI/CD access — works across orgs (GitHub App)

One **GitHub App** ("datalab-framework reader"), owned by the framework's org and
installed on `dediggibyte/datalab-framework` with **Contents: read-only**, serves
**every** adopter — its short-lived tokens are minted for that installation no
matter which repo or org the workflow runs in. The framework-repo admin sets the
App up once (Create App → Contents: read-only → Install on `datalab-framework` →
generate a private key + note the **Client ID**). Then per adopter repo, set two
**repo- or org-level, NOT per-environment** entries (the CI `lint + test` job
declares no `environment:`, so it only sees repo/org variables and secrets):

1. `DATALAB_FRAMEWORK_APP_CLIENT_ID` — an Actions **variable** (the App's Client ID, `Iv23li…`).
2. `DATALAB_FRAMEWORK_APP_PRIVATE_KEY` — an Actions **secret** (the .pem body).

The CI/CD workflows already carry the token flow (`common-ci-steps.yml` /
`common-cd-steps.yml`): `actions/create-github-app-token@v3` mints a token scoped
to `datalab-framework`, then a
`git config url."https://x-access-token:<token>@github.com/…".insteadOf
"https://github.com/…"` rewrite so `uv` and the wheel build clone over HTTPS. Nothing
to author — generating the repo copies these workflows; you only supply the two
values. (Full mechanics + rotation:
[CICD.md → Private framework dependency](CICD.md#private-framework-dependency-git-auth).)

**Alternatives** when a GitHub App doesn't fit the org's policy:

- **Fine-grained PAT / machine user** with read on `datalab-framework`, stored as a
  secret and used by a credential-helper step in place of the App-token step.
- **Decouple from source entirely** (below) if you can't grant any read access —
  deliver the framework as a vendored wheel.

(Deploy keys were the previous default; some orgs disable deploy keys org-wide,
which silently invalidates them — the App is immune to that and needs no per-adopter
key.)

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

The App token is for CI, not people; don't hand its private key to developers.
A per-dev fine-grained PAT in the credential store also works.

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
needed anywhere. These are policy choices; the GitHub App path above is the
established default.

## Pin the framework version

Two places must reference the **same** framework release — keep them in lockstep:

1. `pyproject.toml` → `[tool.uv.sources] datalab` git **tag** (the git dep):

   ```toml
   [tool.uv.sources]
   datalab = { git = "https://github.com/dediggibyte/datalab-framework.git", tag = "v<x.y.z>" }
   ```

   (`datalab` is listed under `[dependency-groups].dev`. In an adopter repo the
   root project IS the domain package; only the multi-domain template repo sets
   `package = false` and uses a uv workspace.)

2. `variables/medallion.yml` → `var.datalab_version` (the wheel filename):

   ```yaml
   datalab_version:
     default: "<x.y.z>"      # → datalab-<x.y.z>-py3-none-any.whl on each project catalog's artifacts.wheels volume
   ```

   (Placeholders on purpose — the real value is whatever `pyproject.toml`
   currently pins; a literal example here would drift every release.)

<!-- template-only:adopting-wheel-path start -->
`var.datalab_wheel` derives the full path from `var.catalog` +
`var.datalab_version`, so you never hand-write the wheel path (this repo's second
domain mirrors the split: `var.sales_datalab_wheel` derives from
`var.sales_catalog`). **Upgrading the framework = bump the git tag AND
`datalab_version`, then `make lock` + `make publish-wheel`** (see "Upgrading the
framework later").
<!-- template-only:adopting-wheel-path end -->

## Publish the framework wheel from your repo

`make publish-wheel` builds the framework wheel **from the pinned git dep** (a
shallow `git clone --depth 1 --branch <tag>` + `uv build --wheel`; there is no
`pip` in a uv-created venv) and uploads it into **each project
catalog's** `artifacts.wheels` UC Volume (`customer_sales.artifacts.wheels`,
`sales.artifacts.wheels` in this repo) — **one upload per project catalog** (the
wheel rides in the same catalog as the domain it serves, not a separate shared
catalog):

```bash
make publish-wheel TARGET=dev                                  # dry run — builds + prints what it would upload
make publish-wheel TARGET=dev APPLY=1 PROFILE=<cli-profile>    # actually uploads into each project catalog's volume
```

`PROFILE=` picks the workspace, exactly as for `bootstrap-uc` below — without it
the SDK uses your DEFAULT CLI profile, and a wrong default silently uploads the
wheel into another workspace's catalog (the pipeline then fails at env install).

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

- each **domain catalog** (`customer_sales` + `sales` in this repo, resolved
  through `scripts/domains.py`; just `<your_catalog>` for a single-domain adopter):
  `bronze`/`silver`/`gold` schemas, the edge-lane `landing`/`exports` volumes
  (volume catalogs only), persona grants, **and an `artifacts.wheels` UC Volume**
  for the framework wheel — the deploy SP writes to it via its catalog-level ALL,
  and the domain's pipeline/job run-as gets **READ VOLUME** so it can install the
  wheel (the install fails if that read grant is missing).

Per-target catalogs and groups are RESOLVED from `variables/`, `targets/` and
`rbac.yml` through `scripts/domains.py` — there are no `CATALOGS`/`GROUPS` dicts to
keep in sync (they were removed when the registry landed) (see AGENTS.md "Change access").

<!-- template-only:adopting-second-domain start -->
## Adding a SECOND domain to THIS reference repo (not an adopter task)

> **Adopters: this section is not for you.** A generated adopter repo is
> single-domain by design — the scaffold already wrote your root-level domain,
> and its `pyproject.toml` is a single package with **no `[tool.uv.workspace]`
> block**. Hand-copying a reference domain into an adopter is exactly the
> drift the scaffold exists to prevent. This section documents how a new
> domain is added to the multi-domain **template** repo itself.

Copy a reference domain and rename every `customer_sales`
token to the new catalog name. Two starting points:

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
     # environment_version: "4"   # leave OFF until the pipeline has run history
     dependencies:
       - ${var.datalab_wheel}                       # framework wheel from THIS project's catalog volume
       - ../../../dist/<catalog>_etl-*.whl          # this domain's wheel (bundle-built)
   ```

   Point the pipeline's `configuration:` `datalab.config_dir` at your config dir
   (`${workspace.file_path}/config/<catalog>` in an adopter repo). `databricks.yml`'s
   `include:` glob already picks up `resources/*.yml`.

<!-- template-only:adopting-second-domain end -->
## Validate → deploy → run

Same gates CI runs:

```bash
make install                          # uv sync → .venv (resolves the framework git dep)
make validate-configs lint test       # pydantic + dqx · ruff · pytest (local Spark, Java 17+)
make validate                         # databricks bundle validate -t dev
make deploy                           # validate + bundle deploy -t dev
make run                              # refresh the <catalog>_etl pipeline on dev
```

`make deploy` builds the domain wheels (needs `uv` on PATH) and CI publishes the
framework wheel before its deploy — so the first run finds both wheels in the
project catalog's `artifacts.wheels` volume.

## Upgrading the framework later

One command performs the whole lockstep:

```bash
make bump-framework VERSION=<x.y.z>
```

It rewrites the git **tag** in `pyproject.toml` `[tool.uv.sources] datalab` and
`var.datalab_version` in `variables/medallion.yml`, re-pins every link into the
framework repo (docs, skills) to the new tag, runs `make lock` (CI runs
`uv sync --frozen` and fails on drift), regenerates the vendored `schemas/*.json`
from the newly pinned models (`make sync-schemas`), and asserts the lockstep
(`make check-lockstep` — also a CI gate, so a partial bump can't merge). Then:

<!-- template-only:adopting-bump-changes start -->
1. Add the release's corresponding changes: read the framework CHANGELOG
   between the two versions, migrate anything flagged **BREAKING**, and document
   every new target/source kind in `.agents/skills/author-ldp-artifact/SKILL.md`
   (`make check-framework-surface` names them; `make sync-skills` after).
   Commit everything the bump touched (`git status` — pyproject, medallion.yml,
   uv.lock, schemas/, the re-pinned docs, the skill).
<!-- template-only:adopting-bump-changes end -->
2. `make publish-wheel TARGET=<t> APPLY=1` — build the new version from the new
   tag and upload it into each project catalog's `artifacts.wheels` volume
   (CI's deploy also publishes before `bundle deploy`).
3. Redeploy (`make deploy`, or merge → CI).

<!-- adopter-if:framework-bot start -->
You usually don't even start this by hand: the scheduled **framework-bump
workflow** (`.github/workflows/framework-bump.yml`) watches the framework repo
for new releases and opens the lockstep PR for you — a draft listing the
corresponding changes when the new version needs any.
<!-- adopter-if:framework-bot end -->
The template treats adopting each release as mandatory (`make
check-framework-current` fails CI until the bump merges); in your adopter repo
the same check only warns unless you set the `DATALAB_FRAMEWORK_MANDATE`
variable to `enforce` (docs/CICD.md "Framework bumps").

**Caching gotcha:** pipeline/job environments cache dependencies. A new framework
version may not appear until the environment rebuilds — trigger a full pipeline
restart (publishing a new version filename forces this) if a change doesn't show
up.

## First-deploy traps (found the hard way)

Three things bite on a brand-new adopter repo, all confirmed against a real
customer workspace in August 2026. None is obvious from the error message.

### Persona groups must be ACCOUNT-level, not workspace-level

Unity Catalog `GRANT` resolves **account** groups. `databricks groups create`
creates a **workspace-local** group, which appears in the workspace UI and is
perfectly usable for pipeline/job `permissions:` ACLs — but is invisible to UC,
so every grant fails:

```
PRINCIPAL_DOES_NOT_EXIST: Could not find principal with name <group>
```

Databricks documents that workspace-local groups "cannot be granted access to
data in a Unity Catalog metastore", but the error says nothing about scope, so it
reads like a typo. Create them at account level and assign to the workspace:

```bash
# once per group (readers / engineers / admins):
databricks account groups create --display-name <catalog>_readers --profile <account-profile>
# then assign each group to the workspace (group ids: `databricks account groups list`):
databricks account workspace-assignment update <workspace-id> <group-id> \
    --json '{"permissions": ["USER"]}' --profile <account-profile>
```

Account-level commands need an account profile (host = the account console URL +
`account_id`) with account-admin rights — a workspace PAT will not do. If you
don't have that yet, `make bootstrap-uc ... SKIP_GRANTS=1` provisions the
catalogs/schemas/volumes alone so you are not blocked.

### Default Storage metastores reject `CREATE CATALOG`

If your account has Default Storage enabled and the metastore has no storage
root:

```
Metastore storage root URL does not exist. Default Storage is enabled in your
account. You can use the UI to create a new catalog using Default Storage, or
please provide a storage location for the catalog.
```

The API cannot help either — `CreateCatalog` has no default-storage field, so
`databricks catalogs create` fails identically (unresolved:
[databricks/cli#4513](https://github.com/databricks/cli/issues/4513)).
`bootstrap_uc.py` now pre-flights this and fails *before* running any DDL, naming
the three workable paths:

```bash
# 1. reuse a sibling catalog's location (this is what unblocked us)
databricks catalogs get <existing-catalog> --profile <p>   # read .storage_root
make bootstrap-uc TARGET=dev ... MANAGED_LOCATION=<that storage_root>

# 2. create the catalog once in the UI / with --storage-root, then
make bootstrap-uc TARGET=dev ... SKIP_CATALOGS=1

# 3. on a SERVERLESS workspace, run `CREATE CATALOG <name>` from a serverless SQL
#    warehouse (Default Storage supplies the location), then SKIP_CATALOGS=1
```

### `environment_version` cannot be enabled on a new pipeline

The generated pipeline resource ships with `environment_version` **commented
out**. Databricks gates enabling it behind a fingerprint check that a new
pipeline cannot satisfy, and a failed attempt leaves the pipeline unable to run
until the setting is removed. Every documented remedy was tried against a real
pipeline:

| Attempt | Result |
|---|---|
| baseline run → enable | `NO_PREVIOUS_FINGERPRINT`, then `FINGERPRINT_MISMATCH` |
| re-baseline with byte-identical code → enable | `FINGERPRINT_MISMATCH` |
| baseline **and** enable both with `--full-refresh-all` | `FINGERPRINT_MISMATCH` |
| `pipelines.environmentVersion.enableCompatibilityScan: "true"` | **zero** issues reported — and the gate still refused |

What you give up by leaving it off: the Python version is 3.12.3 either way today
(DBR 17.3 and environment version 4 agree), so only the **preinstalled library
set** is left unpinned across DBR upgrades. Enabling it also switches pipeline
code to Spark Connect, which is why the gate exists. Uncomment it once the
pipeline has a stable update history, and expect to iterate.

## Where to go next

- [GETTING_STARTED.md](GETTING_STARTED.md) — author your first table end to end.
- [NAMING.md](NAMING.md) — the folder ↔ UC namespace convention.
- [CICD.md](CICD.md) — GitHub OIDC CI/CD, dev/stage/prod promotion.
- Framework reference (authoring fields, SDP capability matrix):
  [`datalab-framework/docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/v1.0.0/docs/FRAMEWORK.md).
  The local `docs/FRAMEWORK.md` is a thin pointer to it.
- [AGENTS.md](../AGENTS.md) — conventions, gotchas, protected-file protocol.
