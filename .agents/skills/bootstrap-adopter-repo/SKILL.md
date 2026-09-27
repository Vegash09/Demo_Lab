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
the generated repo too when it takes the `docs` component).

## How this works — drive the deterministic configurator, don't hand-edit

A single deterministic engine, `scripts/scaffold_adopter.py`, does the whole
conversion: it guarantees the adopter matches the template structure and
repoints **every** workspace-specific surface in one shot. Always prefer it to
hand-conversion — hand-editing is exactly what drifts (a catalog folder named
`config/<catalog>_databricks_prod` instead of `config/<catalog>/`; an `.mcp.json`
still pointing at the template's SQL warehouse).

- **In place — the GitHub-template flow (this skill).** Generate from the
  template, then convert the clone in place. `make configure-adopter` PROMPTS for
  and confirms every value; or, when you (an agent) have already gathered the
  values from the user, drive the script non-interactively (step 3).
- **Fresh sibling repo (alternative).** From a clone of THIS repo,
  `make new-adopter CATALOG=<c> OUT=../<c>-datalab …` emits the same adopter in a
  sibling dir — same engine, then `git init` + push.

What the engine does every run: drops the reference domains (`projects/`), the
template's design assets and `omnigent/`; writes one minimal root-level domain
renamed to `<catalog>`; rewrites every repo-level file (single-package
`pyproject.toml`, root `resources/`, single catalog, per-target hosts + catalogs
in `targets/`, `rbac.yml`, `Makefile`, `scripts/domains.py` +
`scripts/bootstrap_uc.py`, CI/CD incl. `docs/CICD.md`'s OIDC identity);
validates the base-catalog name and the vX.Y.Z framework tag; and repoints the
read-only MCP grounding config (`.mcp.json` + `.cursor/mcp.json`) at the
customer's SQL warehouse + CLI profile.

**Only the mandatory surface is fixed — the rest is the user's choice**, and the
engine ships exactly that choice:

- **Coding agents** — `claude`, `codex`, `cursor`, `genie`, any subset or
  `none`. Each brings only its own harness; `.agents/skills` ships with any.
- **Components** — `docs`, `design` (a design package GENERATED for this
  customer, with a pipeline inventory `make design` keeps in step with
  `config/`), `schemas`, `local-dev`, `githooks`, `pr-template`, `dependabot`,
  `framework-bot`, `mcp`. Defaults: all but `design`.

A dropped choice takes its files, make targets, CI steps and doc passages with
it (`adopter-if` markers in the shared files), and the engine runs a
dangling-reference check on the result BEFORE writing anything. The answers are
recorded in the adopter's `.datalab-adopter.json`. The scaffold tooling itself
(this skill, `scaffold_adopter.py`, its doc checks) never ships — an adopter is
not a template, and the engine refuses to run inside one.
`references/templates.md` is the human-readable record of what it writes — and
the manual fallback, including which files each choice owns.

## 1. Gather inputs (ask the user)

- **Base catalog / domain name** `<catalog>` (lowercase, e.g. `acme`) — drives
  the package `<catalog>_etl`, the pipeline `<catalog>_etl`, and folder names
  (`docs/NAMING.md`). **BASE name only — no `_dev`/`_stage`/`_prod` suffix:** the
  bundle appends the environment per target, so `acme` deploys as `acme` (dev),
  `acme_stage`, `acme_prod`. The configurator REJECTS a suffixed name — pass
  `acme`, never `acme_prod` (that is the `config/<catalog>_databricks_prod`
  drift). Confirm the base name with the user before running.
- **Customer display name** and a **one-line description** of the data product
  (default: derived from the catalog) — they title the README and, with
  `design`, the generated overview and diagram.
- **New repo** `<owner>/<customer-repo>` (e.g. `dediggibyte/acme-datalab`),
  public/private — `<owner>/<customer-repo>` is also the OIDC federation subject
  written into `docs/CICD.md` (`--repo`).
- **Databricks workspace host** `<host>` — and whether **stage / prod live in
  other workspaces** (then their hosts: `--host-stage` / `--host-prod`). The
  per-target catalogs default to `<catalog>`, `<catalog>_stage`,
  `<catalog>_prod` (`--catalog-{dev,stage,prod}` to change).
- **SQL warehouse id** `<warehouse-id>` — used for the one-time UC bootstrap AND
  written into the MCP grounding config (`.mcp.json` / `.cursor/mcp.json`) so the
  agent's read-only queries hit the customer's workspace, not the template's.
- **MCP CLI profile** `<cli-profile>` — the `databricks auth login` profile that
  read-only SQL grounding authenticates with (default `<catalog>_dev`).
- **CI/CD deploy service principal** application id `<deploy-sp-app-id>`.
- **Workspace groups** `<reader-group>` / `<engineer-group>` / `<admin-group>`.
- **Coding agents** the team will use — any of `claude`, `codex`, `cursor`,
  `genie`, or `none` (`--agents`).
- **Optional components** — which of `docs`, `design`, `schemas`, `local-dev`,
  `githooks`, `pr-template`, `dependabot`, `framework-bot`, `mcp` the repo
  should carry (`--components`; a list, `all`, `none`, or `+x`/`-x` edits of the
  defaults — pass it as `--components=-x` when the value starts with `-`).
  What each one ships: `docs/ADOPTING.md` "What each choice ships".
- **Framework version** `<framework-tag>` to pin (default: copy the current
  `[tool.uv.sources] datalab` tag in this repo's `pyproject.toml`).
- **Framework read-access credential** — how the new repo's CI **and** the
  developers clone the PRIVATE `dediggibyte/datalab-framework`. Default: the shared
  read-only **datalab-framework reader GitHub App** (installed on that repo; works
  across orgs) — set `DATALAB_FRAMEWORK_APP_CLIENT_ID` (variable) +
  `DATALAB_FRAMEWORK_APP_PRIVATE_KEY` (secret). Alternatives (PAT / vendored wheel) +
  the OIDC-is-not-this distinction: `docs/ADOPTING.md` → "Accessing the private
  framework repo".

If the user has not decided some of these, use clearly-marked placeholders in
the files and list them as TODOs at the end — never invent a workspace host or
an SP id.

**Another organization?** This skill and `make new-adopter` are org-agnostic —
set `<owner>` to any org you can push to. Two caveats: generating from the
template needs read access to THIS (private) repo, and it copies **files only** —
Actions secrets, GitHub Environments, the OIDC policy, the framework App id/key,
and branch protections do not carry over and are recreated in the new repo
(step 5). OIDC ≠ framework access (step 5).

## 2. Generate the repo from the template

Resolve this repo's slug from `git remote -v` (the `origin` `<owner>/<repo>`),
then create + clone the new repo as a sibling:

```bash
gh repo create <owner>/<customer-repo> --template <owner>/<this-repo> --private --clone
cd <customer-repo>    # --clone is a boolean flag: it clones into ./<customer-repo>, it takes no path
```

(Or GitHub UI: "Use this template" → "Create a new repository", then clone.)
Everything below runs **inside `../<customer-repo>`**, never in the template.

If this repo is not yet flagged as a template, enable it once (repo admin):
`gh repo edit <owner>/<this-repo> --template`.

## 3. Configure the clone (run the deterministic configurator)

Copy this checklist and track it (it is steps 1–10 of `docs/NEW_ADOPTER.md`
compressed — that doc is the canonical ordered sequence with success signals
and failure pointers; keep the user pointed at it for everything you don't do
for them):

```
- [ ] 2. Generated + cloned the new repo; cd into it        (NEW_ADOPTER.md 1)
- [ ] 3. Ran the configurator — domain + repo files + MCP   (NEW_ADOPTER.md 2)
- [ ] 4. make lock + the local gates pass                   (NEW_ADOPTER.md 3)
- [ ] 5. GitHub wiring · account groups · bootstrap · first deploy (NEW_ADOPTER.md 4-9)
- [ ] 6. Handed off to author-ldp-artifact for real tables  (NEW_ADOPTER.md 10)
```

Run it **from inside the clone** — two equivalent ways:

**Interactive (a human at a terminal).** Walks a short form — customer & repo →
workspace & environments → access groups → coding agents → components →
framework — each question with a default (Enter accepts), then shows what will
ship and what is left out, and asks to confirm (`e` re-walks the form with your
answers as defaults). Leftover placeholders are listed as fill-before-deploy
TODOs:

```bash
make configure-adopter
# prefill any answer (skips its question):
make configure-adopter CATALOG=<catalog> HOST=https://<workspace> \
    WAREHOUSE_ID=<warehouse-id> DEPLOY_SP=<app-id> AGENTS=claude,cursor COMPONENTS=+design
# fully scripted (no prompts at all; CATALOG= or ANSWERS= required):
make configure-adopter YES=1 CATALOG=<catalog> HOST=https://<workspace> AGENTS=claude
```

**Non-interactive (you, an agent, applying values you already gathered +
confirmed with the user in step 1).** Pass every value as a flag and `--yes`:

```bash
uv run --no-project python scripts/scaffold_adopter.py --in-place --yes \
    --catalog <catalog> --customer "<customer>" --description "<one line>" \
    --repo <owner>/<customer-repo> --host https://<workspace> \
    [--host-stage https://<stage-ws> --host-prod https://<prod-ws>] \
    --warehouse-id <warehouse-id> --mcp-profile <catalog>_dev \
    --deploy-sp <deploy-sp-app-id> --reader-group <reader-group> \
    --engineer-group <engineer-group> --admin-group <admin-group> \
    --agents=<claude,codex,cursor,genie|none> --components=<list|default,+design,-x> \
    [--framework-tag <framework-tag>]
```

(`--answers <file>` replays a previous run's `.datalab-adopter.json`; flags
override it.) It creates the minimal root domain (`config/<catalog>/` + one Auto
Loader bronze table, `src/<catalog>_etl/`, `resources/<catalog>_etl.{pipeline,job}.yml`,
`tests/`), rewrites every repo-level file (`pyproject.toml`, `databricks.yml`,
`variables/`, `targets/`, `rbac.yml`, `Makefile`, `scripts/domains.py`,
`scripts/bootstrap_uc.py`, CI/CD + `docs/CICD.md`, `.databricksignore`,
`README`/`CHANGELOG`), rewires `.mcp.json` + `.cursor/mcp.json`, removes
`projects/ design/ omnigent/ uv.lock`, and keeps only the agents and components
chosen (with `design`, it generates the customer's own `design/`).

It builds the whole adopter in a scratch dir and touches the clone only after
every patch and the dangling-reference check passed — on failure nothing is
written. It refuses to run against the canonical template (origin
`dediggibyte/datalab`) and inside an already-generated adopter (no `projects/`) —
that is why you run it **in a fresh clone**.

> **Manual fallback.** If you must convert without the script, follow
> [references/templates.md](references/templates.md) file-by-file (kept in lockstep
> with the engine). The two things hand-conversion forgets are exactly the two
> the engine guarantees: the **base-catalog name** (no `_dev`/`_stage`/`_prod`
> suffix → no `config/<catalog>_databricks_prod`) and the **MCP rewiring**
> (`.mcp.json` + `.cursor/mcp.json` off the template's `diggi_dev_aws` /
> warehouse). The `$schema` relative paths shift to 2–3 `../` because the domain
> now sits at the root, not under `projects/`.

## 4. Relock and validate

```bash
make lock                       # rewrite uv.lock for the single package
make install
make validate-configs lint test # pydantic + dqx · ruff · pytest (local Spark)
make validate                   # databricks bundle validate -t dev
```

Fix what each gate names before moving on (`docs/GETTING_STARTED.md` "When
something fails"). `make validate` needs the Databricks CLI authenticated
(`databricks auth login --host <host>`).

## 5. CI/CD, UC bootstrap, first deploy

Detailed walkthrough: `docs/CICD.md` + `docs/ADOPTING.md` ("Accessing the private
framework repo" for the cross-org credential). In the new repo:

- **Framework read access (a git credential, NOT OIDC).** CI (`uv sync`) and CD
  (build the wheel + `bundle deploy`) clone the PRIVATE
  `dediggibyte/datalab-framework`. For an adopter in another org, reuse the shared
  **datalab-framework reader GitHub App** (installed on that repo); set the
  `DATALAB_FRAMEWORK_APP_CLIENT_ID` **variable** + `DATALAB_FRAMEWORK_APP_PRIVATE_KEY`
  **secret** at **repo/org level — not per-environment** (the CI test job declares
  no `environment:`). OIDC cannot
  do this: it federates Actions to Databricks, not to GitHub, so it can't grant
  read on another private repo. Cross-org alternatives (PAT / GitHub App /
  vendored wheel) are in `docs/ADOPTING.md`.
- **GitHub Environments** `dev` / `stage` / `prod` with **secrets** (not
  variables — set as variables the deploy skips with a green run)
  `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` (Databricks auth only).
- **OIDC federation** on the deploy SP (its NUMERIC account id, not the app
  id): subject `repo:<owner>/<customer-repo>:environment:<target>`, audience
  `<DATABRICKS_ACCOUNT_ID>` — the account id, per the policy JSON in
  `docs/CICD.md` (a wrong audience surfaces as TOKEN_INVALID at first deploy).
- **Account-level persona groups BEFORE bootstrap** (`docs/NEW_ADOPTER.md`
  step 5): `databricks account groups create` + `databricks account
  workspace-assignment update` per group — a group made with plain
  `databricks groups create` is invisible to Unity Catalog and every GRANT
  fails `PRINCIPAL_DOES_NOT_EXIST`.
- **First deploy:**

```bash
databricks auth login --host <host> --profile <cli-profile>           # creates the CLI profile used below
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<warehouse-id> PROFILE=<cli-profile>  # catalog/schemas/volumes/grants
make publish-wheel TARGET=dev APPLY=1 PROFILE=<cli-profile>           # framework wheel → this catalog's volume
make deploy                                                          # bundle deploy -t dev
make run                                                             # refresh the pipeline
git add -A && git commit -m "configure adopter" && git push          # CI needs the regenerated uv.lock
```

(`<warehouse-id>` / `<cli-profile>` are the same values from step 1 — already
written into `.mcp.json` / `.cursor/mcp.json` by the configurator.)

## 6. Extend with pipelines

The repo is now ready. Add real bronze/silver/gold tables with the
**`author-ldp-artifact`** skill (one YAML artifact per table), pure
`@transform` functions in `src/<catalog>_etl/transforms/` (+ a unit test), and
register their modules in `config/<catalog>/domain.yml` `imports:`. For the rare
case the YAML cannot express, use **`author-sdp-pipeline`**; for deploy issues,
**`deploy-databricks-bundle`**. With the `design` component, run `make design`
after each table, job or pipeline change - it re-renders `design/PIPELINES.md`
and regenerates the diagrams from the estate (CI's `make check-design` fails
while either is stale or hand-edited), and the **`maintain-design-diagram`**
skill (with **`drawio-architecture-designer`** for layout changes) keeps the
diagrams and overview in step.

## Done check

- `make validate-configs lint test validate` are green in the new repo.
- `databricks bundle summary -t dev` shows `<catalog>_etl` + its refresh job.
- A refresh materializes `bronze.events_raw`; adding a silver table with dqx
  produces `<table>` + `<table>_quarantine`.
- The catalog folder is `config/<catalog>/` (the BASE name — **not**
  `config/<catalog>_stage`, `config/<catalog>_prod`, or a profile/env-suffixed
  name), and `.mcp.json` / `.cursor/mcp.json` reference the customer's warehouse +
  profile — `rg -n "diggi_dev_aws|c1cdbe2406e5cf04" .mcp.json .cursor/mcp.json` is
  clean.
- The DEPLOYED surfaces carry no template identity:
  `rg -n "customer_sales|diggi_dev_aws|c1cdbe2406e5cf04" config src resources
  variables targets rbac.yml databricks.yml Makefile pyproject.toml README.md`
  is clean. (Do NOT grep the whole repo: `scripts/` and the hook files
  legitimately mention template names in docstrings/regexes.)
- Everything the new repo reads describes THIS repo and only what it chose — run
  from the TEMPLATE checkout: `make check-adopter-docs ADOPTER=../<customer-repo>`
  (template identity + any reference to a path, doc or `make` target the repo
  does not have). The configurator already ran it before writing; re-run it
  after hand edits.
- `.datalab-adopter.json` lists the agents and components the user confirmed,
  and only their files exist (e.g. no `.cursor/` without cursor or a hooked
  agent, no `docs/` without `docs`).
