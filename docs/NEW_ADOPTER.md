# Stand up a new adopter repo — the checklist

This is **the** ordered path for standing up a datalab adopter repo for a new
customer — every step is one command, its success signal, and where to look when
it fails. Deep background lives elsewhere and is linked per step; you do not
need it to get to a running pipeline. Agents: the `bootstrap-adopter-repo`
skill drives steps 1–3 of this same sequence.

> Reading this inside a repo that was already generated? Steps 1–2 are done —
> start at step 3.

## 0. Prerequisites — collect these BEFORE touching a keyboard

Some of these are cross-team requests with real lead time. Ask for all of them
on day zero.

| You need | Who provides it | Used for |
|---|---|---|
| Read access to `dediggibyte/datalab` (this template) **and** `dediggibyte/datalab-framework` for you and your devs | framework-repo admin | generating the repo; `make lock install` clones the private framework |
| Framework reader **GitHub App** Client ID (`Iv23li…`) + private key `.pem` | framework-repo admin | CI clones the private framework ([ADOPTING.md](ADOPTING.md#accessing-the-private-framework-repo-local--ci-cross-org)) |
| Databricks **workspace URL** + a **running SQL warehouse id** | customer workspace admin | UC bootstrap + the read-only MCP grounding config |
| **Deploy service principal** — note BOTH identifiers: the **application id** (UUID; it doubles as the OAuth client id) and the **numeric id** (account console → the SP's ID) | customer account admin | application id → scaffold `DEPLOY_SP=`, the UC GRANT, and the `DATABRICKS_CLIENT_ID` secret; numeric id → the federation policy |
| **Account-admin** access (or an admin who will run step 5 for you) + the **Databricks account id** and **workspace id** | customer account admin | account-level persona groups + the OIDC federation policy — a workspace PAT will NOT do |
| Tools: `uv`, `gh`, `databricks` CLI ≥ v0.294.0, Java 17+ | you | everything below |

<!-- template-only:new-adopter-generate start -->
## 1. Generate the repo from the template

```bash
gh repo create <owner>/<customer>-datalab --template dediggibyte/datalab --private --clone
cd <customer>-datalab
```

`--clone` is a boolean flag — it clones into `./<customer>-datalab`; it takes no
path argument. ✅ *Success: the repo exists on GitHub and you are inside the
clone.* (One-time, template admin: `gh repo edit dediggibyte/datalab
--template` enables the template flag.)

## 2. Convert the clone into your adopter repo

```bash
make configure-adopter
```

A short form, each question with a default you accept with Enter:

1. **Customer & repo** — base catalog name (lowercase, **no**
   `_dev`/`_stage`/`_prod` suffix), customer display name, a one-line
   description, the GitHub `<owner>/<repo>` (the OIDC federation subject).
2. **Workspace & environments** — the dev workspace host; whether stage/prod
   live in other workspaces (then their hosts); the per-environment catalogs;
   the SQL warehouse id, CLI profile and deploy SP.
3. **Access groups** — reader / engineer / admin (account-level).
4. **Coding agents** — any of claude, codex, cursor, genie, or none.
5. **Components** — docs, design, schemas, local-dev, githooks, pr-template,
   dependabot, framework-bot, mcp (what each ships:
   [ADOPTING.md](ADOPTING.md#what-each-choice-ships)).
6. **Framework** — the datalab release tag to pin.

Then a summary of what will ship and what is left out, and the fill-before-deploy
TODOs for any placeholder you kept. Prefill any answer to skip its question
(`CATALOG=acme HOST=… AGENTS=claude,cursor COMPONENTS=+design`), or run fully
scripted with `YES=1` (requires `CATALOG=` or `ANSWERS=`). The answers are
saved to `.datalab-adopter.json`. ✅ *Success: `scaffold: done.` and
`config/<catalog>/` exists.* ❌ *An "anchor not found" or "docs still point at
material this repo does not have" error names exactly which file drifted —
nothing was written; report it on the template repo.*
<!-- template-only:new-adopter-generate end -->

## 3. Local gates

```bash
make lock install       # clones the private framework — needs your read access (step 0)
make enable-githooks    # protected-files pre-commit guard (one-time per clone)
make validate-configs lint test
```

✅ *Success: all three gates green.* ❌ *`Repository not found` from `make
lock` → your machine lacks framework read access; `gh auth login` +
`gh auth setup-git`, or see [ADOPTING.md](ADOPTING.md#local-developer-machines--yes-every-dev).*

## 4. GitHub wiring (repo Settings — no Databricks yet)

```bash
gh variable set DATALAB_FRAMEWORK_APP_CLIENT_ID --body "Iv23li…"
gh secret set DATALAB_FRAMEWORK_APP_PRIVATE_KEY < path/to/app-key.pem
```

Both at **repo/org scope, NOT per-environment** (the CI test job declares no
`environment:`). Then create GitHub **Environments** `dev`, `stage`, `prod`,
each with **secrets** (not variables — set as variables the deploy skips with
a green run): `DATABRICKS_HOST` and `DATABRICKS_CLIENT_ID` (the SP application
id). ✅ *Success: push a commit — `ci / lint + unit test` is green.*

<!-- adopter-if:dependabot start -->
**Dependabot** reads a separate secret store — mirror the key there too, or
every dependabot-triggered CI run fails the App-token mint:

```bash
gh secret set DATALAB_FRAMEWORK_APP_PRIVATE_KEY --app dependabot < path/to/app-key.pem
```

If this repo lives in the **same org** as the framework repo, also grant
Dependabot access to the framework repo so its `uv` updater can resolve the
lockfile (org Settings → Code security → Dependabot → private repository
access, or the `repository-access` API — see
[CICD.md](CICD.md#private-framework-dependency-git-auth)); **cross-org** the
grant can't reach it — give the updater a `registries:` `type: git`
credential in `dependabot.yml` (PAT in the Dependabot store) or remove the
`uv` ecosystem there. ✅ *Success: a dependabot PR (or `@dependabot rebase` on
one) is green, its log reading `Secret source: Dependabot`.*
<!-- adopter-if:dependabot end -->

## 5. Databricks account-level setup (account admin; once per workspace)

```bash
# an ACCOUNT-level CLI profile (host = the account console, not the workspace)
databricks auth login --host https://accounts.cloud.databricks.com \
    --account-id <DATABRICKS_ACCOUNT_ID> --profile <customer>_account

# persona groups — ACCOUNT level. `databricks groups create` (workspace-level)
# makes groups Unity Catalog CANNOT see: every GRANT then fails
# PRINCIPAL_DOES_NOT_EXIST. See ADOPTING.md "First-deploy traps".
for g in <catalog>_readers <catalog>_engineers <catalog>_admins; do
  databricks account groups create --display-name "$g" --profile <customer>_account
done

# assign each group to the workspace (group ids: `databricks account groups list`)
databricks account workspace-assignment update <WORKSPACE_ID> <GROUP_ID> \
    --json '{"permissions": ["USER"]}' --profile <customer>_account

# OIDC federation policy — one per target; audience is the ACCOUNT id
databricks account service-principal-federation-policy create <SP_NUMERIC_ID> \
    --profile <customer>_account --json '{
  "oidc_policy": {
    "issuer": "https://token.actions.githubusercontent.com",
    "audiences": ["<DATABRICKS_ACCOUNT_ID>"],
    "subject": "repo:<owner>/<customer>-datalab:environment:<target>"
  }
}'
```

✅ *Success: groups listed by `databricks account groups list`; three federation
policies exist.* ❌ *`TOKEN_SUBJECT_INVALID` / `TOKEN_INVALID` at deploy time →
copy the exact subject/audience strings from the error into the policy
([CICD.md](CICD.md#one-time-setup-per-target)).*

## 6. Workspace auth + UC bootstrap

```bash
databricks auth login --host <workspace-url> --profile <catalog>_dev
make bootstrap-uc TARGET=dev                                    # dry run — review the SQL
make bootstrap-uc TARGET=dev WAREHOUSE_ID=<id> PROFILE=<catalog>_dev
```

The `--profile` login creates the CLI profile every later command (and the MCP
grounding config) uses — and `PROFILE=` matters: without it the SDK silently
uses your DEFAULT profile, which may be a different workspace. ✅ *Success:
`bootstrap complete for target 'dev'`.* ❌ *`PRINCIPAL_DOES_NOT_EXIST` → step 5
was skipped or used workspace-local groups; `Metastore storage root` error →
[ADOPTING.md "First-deploy traps"](ADOPTING.md#first-deploy-traps-found-the-hard-way).*

## 7. Publish the framework wheel

```bash
make publish-wheel TARGET=dev APPLY=1 PROFILE=<catalog>_dev
```

✅ *Success: an upload into `/Volumes/<catalog>/artifacts/wheels/` is logged —
the wheel must exist there BEFORE the first pipeline run or its environment
install fails.*

## 8. Commit and push the conversion

```bash
git add -A && git commit -m "configure <catalog> adopter" && git push
```

CI runs `uv sync --frozen` — the `uv.lock` that `make lock` regenerated in step
3 **must** be committed. ✅ *Success: the full CI/CD run is green (dev deploy
included).*

## 9. Deploy, seed, run

```bash
make deploy
databricks fs cp sample_data/landing/<catalog>/events/events.json \
    dbfs:/Volumes/<catalog>/landing/<catalog>/events/ --profile <catalog>_dev
make run
```

✅ *Success: the `<catalog>_etl` pipeline refresh completes and
`<catalog>.bronze.events_raw` holds the seeded rows.*

## 10. Extend

Add real tables with the `author-ldp-artifact` skill (one YAML artifact per
table — [GETTING_STARTED.md](GETTING_STARTED.md)). When stage/prod are ready:
different hosts go in `targets/stage.yml` / `targets/prod.yml`, then repeat
steps 5–9 per target.

---

**Where the depth lives:** [ADOPTING.md](ADOPTING.md) — what the conversion
does, framework credential theory, first-deploy traps · [CICD.md](CICD.md) —
workflows, OIDC, release flow · [NAMING.md](NAMING.md) — the folder ↔ UC
namespace contract · [GETTING_STARTED.md](GETTING_STARTED.md) — authoring your
first real table.
