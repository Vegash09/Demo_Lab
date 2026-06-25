---
name: bootstrap-adopter-repo
description: Stand up a brand-new datalab adopter repo for another customer by generating from this repo's GitHub template and converting it into a minimal, root-level single-domain repo ready to extend with pipelines. Use when the user wants a new customer/project repo "like this one", to reuse the framework for another customer, or to scaffold/bootstrap/template a fresh adopter repo.
---

# Bootstrap a new datalab adopter repo from this template

This repo is a **GitHub template repository**. Generating from it gives a new
repo that is a *reference* clone (domains under `projects/`, two example
domains, design assets). This skill converts that clone into a clean
**single-domain adopter repo** for one customer, with the domain at the repo
**root** (`config/<catalog>/`, `src/<catalog>_etl/`, `resources/*.yml`) — then
hands off to the `author-ldp-artifact` skill to add real tables.

Three repos are involved:

- **framework** — `dediggibyte/datalab-framework` (the `datalab` library, never
  edited here; consumed as a git dep + UC-Volume wheel).
- **this template repo** — what you generate from.
- **the new customer repo** — what you produce.

Concrete file contents to paste live in [references/templates.md](references/templates.md).
Background (the two consumption paths, UC bootstrap, CI/CD) is in `docs/ADOPTING.md`,
`docs/GETTING_STARTED.md`, `docs/CICD.md`, and `docs/NAMING.md` (these ship in
the generated repo too).

## Two ways to do this

- **Flow A — deterministic generator (recommended for a brand-new repo).** From
  THIS repo, `make new-adopter` (wraps `scripts/scaffold_adopter.py`) emits a
  ready adopter repo in ONE command: it copies only git-tracked files (never
  secrets/state/build output), drops the reference domains, writes the minimal
  root domain, and rewrites every repo-level file. Then `git init` + push.

  ```bash
  make new-adopter CATALOG=<catalog> OUT=../<catalog>-datalab \
      HOST=https://<workspace> DEPLOY_SP=<app-id>
  cd ../<catalog>-datalab && git init -b main && make lock install \
      && make validate-configs lint test
  ```

  Steps 4–6 below document exactly what the generator does; the gather-inputs
  and CI/CD/deploy steps (1, 7, 8) still apply.

- **Flow B — GitHub template + manual conversion (the rest of this skill).** Use
  this when converting a `gh repo create --template` clone by hand, or when you
  want to adjust the layout as you go. Follow steps 1–8.

## 1. Gather inputs (ask the user)

- **Base catalog / domain name** `<catalog>` (lowercase, e.g. `acme`) — drives
  the package `<catalog>_etl`, the pipeline `<catalog>_etl`, and folder names
  (`docs/NAMING.md`).
- **New repo** `<owner>/<customer-repo>` (e.g. `dediggibyte/acme-datalab`),
  public/private.
- **Databricks workspace host** `<host>`.
- **CI/CD deploy service principal** application id `<deploy-sp-app-id>`.
- **Workspace groups** `<reader-group>` / `<engineer-group>` / `<admin-group>`.
- **Framework version** `<framework-tag>` to pin (default: copy the current
  `[tool.uv.sources] datalab` tag in this repo's `pyproject.toml`).
- **Framework read-access credential** — how the new repo's CI **and** the
  developers clone the PRIVATE `dediggibyte/datalab-framework`. Default: a
  per-adopter read-only SSH **deploy key** (repo-scoped, so it works across
  orgs). Alternatives (PAT / GitHub App / vendored wheel) +
  the OIDC-is-not-this distinction: `docs/ADOPTING.md` → "Accessing the private
  framework repo".

If the user has not decided some of these, use clearly-marked placeholders in
the files and list them as TODOs at the end — never invent a workspace host or
an SP id.

**Another organization?** This skill and `make new-adopter` are org-agnostic —
set `<owner>` to any org you can push to. Two caveats: generating from the
template needs read access to THIS (private) repo, and it copies **files only** —
Actions secrets, GitHub Environments, the OIDC policy, the framework deploy key,
and branch protections do not carry over and are recreated in the new repo
(steps 6–7). OIDC ≠ framework access (step 7).

## 2. Generate the repo from the template

Resolve this repo's slug from `git remote -v` (the `origin` `<owner>/<repo>`),
then create + clone the new repo as a sibling:

```bash
gh repo create <owner>/<customer-repo> --template <owner>/<this-repo> --private --clone ../<customer-repo>
cd ../<customer-repo>
```

(Or GitHub UI: "Use this template" → "Create a new repository", then clone.)
Everything below runs **inside `../<customer-repo>`**, never in the template.

If this repo is not yet flagged as a template, enable it once (repo admin):
`gh repo edit <owner>/<this-repo> --template`.

## 3. Conversion workflow

Copy this checklist and track it:

```
- [ ] 2. Generated + cloned the new repo; cd into it
- [ ] 4. Created the minimal root domain (config/, src/, resources/, tests/)
- [ ] 5. Rewrote the repo-level files for the adopter layout
- [ ] 5. Stripped reference material (projects/, design/, uv.lock)
- [ ] 6. make lock + the local gates pass
- [ ] 7. CI/CD secrets + UC bootstrap + first deploy
- [ ] 8. Handed off to author-ldp-artifact for real tables
```

## 4. Create the minimal root domain

Create these from [references/templates.md](references/templates.md), substituting
`<catalog>` (and the other placeholders) throughout. The `$schema` relative
paths differ from the reference repo because the domain now sits at the root
(2–3 `../` to `schemas/`, not 4–5):

- `config/<catalog>/domain.yml`
- `config/<catalog>/bronze/events_raw.yml` (one Auto Loader table) + empty
  `config/<catalog>/silver/` and `config/<catalog>/gold/` folders
- `src/<catalog>_etl/__init__.py`,
  `src/<catalog>_etl/transformations/pipeline.py`,
  `src/<catalog>_etl/transforms/__init__.py`,
  `src/<catalog>_etl/checks/__init__.py`
- `resources/<catalog>_etl.pipeline.yml` + `resources/<catalog>_etl.job.yml`
  (root-relative paths: `../src/...`, `../dist/<catalog>_etl-*.whl`,
  `config_dir: ${workspace.file_path}/config/<catalog>`)
- `tests/conftest.py` (the shared SparkSession fixture)

## 5. Rewire the repo-level files

Full contents/edits in [references/templates.md](references/templates.md). Summary
of what changes from the reference repo:

- **`pyproject.toml`** → a single buildable package (`name = "<catalog>_etl"`,
  hatchling, `packages = ["src/<catalog>_etl"]`). Remove `[tool.uv.workspace]`
  and the `customer_sales_etl`/`sales_etl` members + sources. Keep the
  `datalab` git source (pinned tag), the dev group, ruff config (fix
  `known-first-party` + `per-file-ignores` to `src/*`), `testpaths = ["tests"]`.
- **`databricks.yml`** → bundle `name: <catalog>`; one `artifacts:` entry
  (`uv build --wheel`); `include:` drops `projects/*/resources/*.yml`;
  `sync.exclude` drops the `projects/*` lines.
- **`variables/medallion.yml`** → single `catalog`; replace the `sales_*` vars
  with one `landing_path`; keep `datalab_version` + `datalab_wheel`.
- **`targets/{dev,stage,prod}.yml`** → single `catalog` var per env
  (`<catalog>` / `<catalog>_stage` / `<catalog>_prod`); set `host`.
- **`rbac.yml`** → keep the structure; set the customer's group names + per-env
  overrides.
- **`Makefile`** → `LINT_PATHS := scripts src`; `run` target → `<catalog>_etl`;
  `LOCAL_*` / `CONNECT_*` paths → root `config/<catalog>` + `src/<catalog>_etl`;
  the `spec-local` conf → `datalab.landing_path`.
- **`scripts/bootstrap_uc.py`** → `CATALOGS` (one catalog/target), `GROUPS`,
  `DEPLOY_SP`. (`scripts/publish_wheel.py` follows `CATALOGS` — no edit.)
- **`.github/workflows/common-ci-steps.yml`** → ruff `scripts projects` →
  `scripts src`; keep the framework deploy-key step.
- **`.databricksignore`** → drop `projects/*` lines (align with `sync.exclude`).
- **`README.md` / `CHANGELOG.md`** → rewrite for the customer; keep `docs/`
  (reusable) but fix repo-specific references.

Then **strip the reference material** (after the minimal domain + `tests/conftest.py`
exist):

```bash
rm -rf projects design uv.lock
# optional: rm -rf omnigent   (dev-time pilot, not needed)
```

Keep: the repo-level scaffold, `scripts/`, `schemas/` (vendored — needed for
config validation), `.github/`, and the agent harness (`.agents`, `.claude`,
`.cursor`, `.codex`, `.githooks`) — the adopter keeps every authoring/deploy
skill, including this one.

## 6. Relock and validate

```bash
make lock                       # rewrite uv.lock for the single package
make install
make validate-configs lint test # pydantic + dqx · ruff · pytest (local Spark)
make validate                   # databricks bundle validate -t dev
```

Fix what each gate names before moving on (`docs/GETTING_STARTED.md` "When
something fails"). `make validate` needs the Databricks CLI authenticated
(`databricks auth login --host <host>`).

## 7. CI/CD, UC bootstrap, first deploy

Detailed walkthrough: `docs/CICD.md` + `docs/ADOPTING.md` ("Accessing the private
framework repo" for the cross-org credential). In the new repo:

- **Framework read access (a git credential, NOT OIDC).** CI (`uv sync`) and CD
  (build the wheel + `bundle deploy`) clone the PRIVATE
  `dediggibyte/datalab-framework`. For an adopter in another org, the
  framework-repo admin mints a **per-adopter read-only deploy key**; store its
  private half as the `DATALAB_FRAMEWORK_DEPLOY_KEY` secret at **repo/org level —
  not per-environment** (the CI test job declares no `environment:`). OIDC cannot
  do this: it federates Actions to Databricks, not to GitHub, so it can't grant
  read on another private repo. Cross-org alternatives (PAT / GitHub App /
  vendored wheel) are in `docs/ADOPTING.md`.
- **GitHub Environments** `dev` / `stage` / `prod` with secrets
  `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` (Databricks auth only).
- **OIDC federation** on the deploy SP: subject
  `repo:<owner>/<customer-repo>:environment:<target>`, audience
  `<host>/oidc/v1/token`.
- **First deploy:**

```bash
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<id> PROFILE=<cli-profile>  # catalog/schemas/volumes/grants
make publish-wheel TARGET=dev APPLY=1                                 # framework wheel → this catalog's volume
make deploy                                                          # bundle deploy -t dev
make run                                                             # refresh the pipeline
```

## 8. Extend with pipelines

The repo is now ready. Add real bronze/silver/gold tables with the
**`author-ldp-artifact`** skill (one YAML artifact per table), pure
`@transform` functions in `src/<catalog>_etl/transforms/` (+ a unit test), and
register their modules in `config/<catalog>/domain.yml` `imports:`. For the rare
case the YAML cannot express, use **`author-sdp-pipeline`**; for deploy issues,
**`deploy-databricks-bundle`**.

## Done check

- `make validate-configs lint test validate` are green in the new repo.
- `databricks bundle summary -t dev` shows `<catalog>_etl` + its refresh job.
- A refresh materializes `bronze.events_raw`; adding a silver table with dqx
  produces `<table>` + `<table>_quarantine`.
- No `customer_sales` / `sales` / `projects/` references remain
  (`rg -n "customer_sales|projects/" --glob '!docs/**'` is clean or only hits
  intentional doc text).
