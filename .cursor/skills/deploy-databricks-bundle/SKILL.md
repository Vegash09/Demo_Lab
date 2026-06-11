---
name: deploy-databricks-bundle
description: Deploy or troubleshoot the datalab Declarative Automation Bundle (databricks.yml + resources/*.yml) — validate, deploy, run pipelines/jobs across dev/stage/prod, or wire up GitHub OIDC CI/CD. Use when the user wants to deploy, a `databricks bundle` command fails, a pipeline refresh errors, or CI/CD auth breaks. Skip for pure transformation-logic changes that don't touch deployment.
---

# Deploy the datalab bundle

The repo ships as a **Declarative Automation Bundle** (formerly Databricks
Asset Bundle): `databricks.yml` (variables + targets `dev`/`stage`/`prod`) +
per-domain resource files — in this repo `examples/*/resources/*.yml`
(adopter repos: root-level `resources/*.yml`); one SDP pipeline + its
refresh job per domain. CI/CD deploys via GitHub OIDC; local deploys use
your CLI auth.

## Local deploy (the fast path)

```bash
make validate          # databricks bundle validate -t dev
make deploy            # validate + databricks bundle deploy -t dev
make run               # databricks bundle run sales_etl -t dev (refresh)
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
- The pipeline environment installs the repo with
  `--editable ${workspace.file_path}` — `pyproject.toml` + `src/**` +
  `examples/**` (code AND config artifacts) must ship, so never add them to
  `.databricksignore`.
- `dev` target = `mode: development`: resource names get a `[dev <user>]`
  prefix, triggers are paused, deploys are isolated per user. `stage`/`prod` =
  `mode: production` with fixed `root_path`s.

## GitHub OIDC CI/CD

CD authenticates with OIDC (no client secret stored). One-time setup per
target (full walkthrough: `docs/CICD.md`):

1. On the deploy service principal, add a federation policy:
   - issuer: `https://token.actions.githubusercontent.com`
   - audience: `<DATABRICKS_HOST>/oidc/v1/token`
   - subject: `repo:<owner>/<repo>:environment:<target>` (env-style because
     the CI/CD jobs declare `environment: <target>`)
2. Create the GitHub Environment named `<target>` with secrets
   `DATABRICKS_HOST` + `DATABRICKS_CLIENT_ID` (optional vars
   `DATALAB_CATALOG`, `DATALAB_SALES_LANDING_PATH`).
3. dev deploys on push to `main`; stage on `v*-rc*` tags; prod on `v*` tags
   (all also via manual dispatch).

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| validate: unknown field `environment` / `environment_version` | CLI too old — upgrade to ≥ v0.294.0 (`databricks version`). |
| validate complains about an unset variable | Override with `--var key=value` or set a default in `databricks.yml`. |
| Pipeline fails: `Missing pipeline configuration 'datalab.*'` | Parameter not in the resource `configuration:` mapping — add it and redeploy. |
| `ModuleNotFoundError: datalab` in a pipeline | The editable env dependency or `pyproject.toml`/`src/**` didn't ship — check `.databricksignore` and the `environment.dependencies` block. |
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
