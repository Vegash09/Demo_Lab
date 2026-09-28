---
name: deploy-databricks-bundle
description: Deploy or troubleshoot the datalab Declarative Automation Bundle (databricks.yml + resources/*.yml) — validate, deploy, run pipelines/jobs across dev/stage/prod, or wire up GitHub OIDC CI/CD. Use when the user wants to deploy, a `databricks bundle` command fails, a pipeline refresh errors, or CI/CD auth breaks. Skip for pure transformation-logic changes that don't touch deployment.
---

# Deploy the datalab bundle

The repo ships as a **Declarative Automation Bundle** (formerly Databricks
Asset Bundle): `databricks.yml` (variables + targets `dev`/`stage`/`prod`) +
per-domain resource files — in this repo `projects/*/resources/*.yml`
(adopter repos: root-level `resources/*.yml`); one SDP pipeline + its
refresh job per domain. CI/CD deploys via GitHub OIDC; local deploys use
your CLI auth.

## Local deploy (the fast path)

```bash
make validate          # databricks bundle validate -t dev
make deploy            # validate + databricks bundle deploy -t dev
make run               # databricks bundle run customer_sales_etl -t dev (refresh)
# other targets:
make deploy TARGET=stage
```

Prereqs: Databricks CLI **≥ v0.294.0** (pipeline `environment_version`
support), authenticated (`databricks auth login --host <workspace-url>`).

Inspect deployed state:

```bash
databricks bundle summary -t dev
databricks pipelines list-pipelines | head
```

## How config flows (read before editing yaml)

- `databricks.yml` declares **variables** (catalog, layer schemas,
  `sales_landing_path`, permission lists) and per-target values. Resources
  consume them via `${var.*}`.
- The pipeline resource passes parameters to code through its
  `configuration:` mapping → read in Python with
  `datalab.config.pipeline_conf`. Add new parameters in BOTH places.
- The pipeline environment installs TWO wheels in `environment.dependencies`:
  `${var.datalab_wheel}` (the framework, from THIS project's catalog
  `artifacts.wheels` Volume) + the domain wheel `../../../dist/<catalog>_etl-*.whl`.
  Serverless does NOT honor
  `--editable`. The config artifacts (`config/**`) + synced workspace files must
  still ship, so never add them to `.databricksignore`.
- `dev` target = `mode: development`: resource names get a `[dev <user>]`
  prefix, triggers are paused, deploys are isolated per user. `stage`/`prod` =
  `mode: production` with fixed `root_path`s.

## GitHub OIDC CI/CD

CD authenticates with OIDC (no client secret stored). One-time setup per
target (full walkthrough: `docs/CICD.md`):

1. On the deploy service principal (its NUMERIC account id), add a federation
   policy:
   - issuer: `https://token.actions.githubusercontent.com`
   - audience: `<DATABRICKS_ACCOUNT_ID>` (the account id — Databricks' default
     and recommendation; a host-URL audience fails with TOKEN_INVALID)
   - subject: `repo:<owner>/<repo>:environment:<target>` (env-style because
     the CI/CD jobs declare `environment: <target>`)
2. Create the GitHub Environment named `<target>` with secrets
   `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` (optional vars
   `DATALAB_CATALOG`, `DATALAB_SALES_LANDING_PATH`).
3. dev deploys on push to `main`, and a successful dev deploy cuts the
   `CHANGELOG.md` release (`[Unreleased]` → `## [X.Y.Z]`, pushed to main as
   `chore(release): vX.Y.Z`); stage on `v*-rc*` tags; prod on `v*` tags (all
   also via manual dispatch) — tag that release commit, the only tree the
   stage/prod gate accepts.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| stage/prod run fails in `derive target` with "this commit is not a promotable release" | The tag is not on a cut release: tag the `chore(release): vX.Y.Z` commit the dev deploy pushed (its `[Unreleased]` is empty, and the tag must name that version). `make release-changelog` shows what is still pending. |
| `cut the changelog release` fails with "Changelog release not pushed" | The deploy succeeded but `GITHUB_TOKEN` could not push to `main` — allow Actions to write (Settings → Actions → General → Workflow permissions / any rule on `main`), re-run the job; or `make release-changelog APPLY=1` in a PR titled `chore(release): vX.Y.Z`. |
| validate: unknown field `environment` / `environment_version` | CLI too old — upgrade to ≥ v0.294.0 (`databricks version`). |
| validate complains about an unset variable | Override with `--var key=value` or set a default in `databricks.yml`. |
| Pipeline fails: `Missing pipeline configuration 'datalab.*'` | Parameter not in the resource `configuration:` mapping — add it and redeploy. |
| `ModuleNotFoundError: datalab` in a pipeline | The framework wheel didn't install — check `${var.datalab_wheel}` resolves (the version exists in this project catalog's `artifacts.wheels` volume; `make publish-wheel`) and the `environment.dependencies` block. |
| New pip dependency not visible in pipeline | Pipeline environments cache deps in development — full restart the pipeline, or bump and redeploy. |
| Auto Loader path errors on first run | The landing volume (`${var.sales_landing_path}`) doesn't exist — create catalog/schema/volume or override the variable. |
| CI `auth describe` fails / `TOKEN_SUBJECT_INVALID` | OIDC federation policy subject/audience doesn't match — copy the exact strings from the error into the policy. |
| Stale bundle state ("already exists") | `rm -rf .databricks` then `databricks bundle deploy --force -t dev`. |
| Schedule didn't fire in dev | Expected — `mode: development` pauses triggers. Use `make run`. |

## Done check

1. `databricks bundle validate -t <target>` is clean.
2. `databricks bundle summary -t <target>` shows the pipeline + job.
3. A refresh (`make run` / job trigger) completes; silver/gold tables are
   queryable and `<table>_quarantine` holds only genuinely rejected rows
   (this repo uses dqx quarantines, not pipeline expectations).
