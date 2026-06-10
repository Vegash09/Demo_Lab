# CI/CD

GitHub Actions + GitHub OIDC + Declarative Automation Bundles. No long-lived
Databricks secrets are stored in GitHub.

## Workflows

| Workflow | Trigger | What runs |
|---|---|---|
| `ci-cd-dev.yml` | PRs to `main`, pushes to `main`, manual | CI on PRs; CI + deploy to `dev` on push to main |
| `ci-cd-stage.yml` | `v*-rc*` tags, manual | CI + deploy to `stage` |
| `ci-cd-prod.yml` | `v*` tags (non-rc), manual | CI + deploy to `prod` |
| `pr-template-check.yml` | every PR | enforces the unified PR template |

Reusable pieces:

- `common-ci-steps.yml` — `uv sync --frozen` → `ruff check` → `pytest`
  (local Spark, Java 21) → `databricks bundle validate -t <target>` (OIDC).
- `common-cd-steps.yml` — OIDC setup → `deploy-dab` composite action
  (validate + deploy with optional `--var` overrides).
- Composite actions: `.github/actions/databricks-setup` (CLI install +
  `~/.databrickscfg` with `auth_type = github-oidc`),
  `.github/actions/deploy-dab`.

## One-time setup per target

This repo deliberately reuses the **same workspace + OIDC service principal**
as the `klarna-access-agent` and `databricks_dqx_agent` repos:

- workspace: `https://dbc-425be768-f138.cloud.databricks.com`
- SP application ID: `437346a1-0b53-418a-80d4-abaf2586ed97`
  (`access-management-sp-rulebook`)

For each target (`dev`, `stage`, `prod`):

1. **Service principal** (Databricks Account Console → Service principals):
   the shared SP above; it needs permission to deploy bundles to the
   workspace (and CREATE/USE on the target catalog).
2. **Federation policy** on that service principal — one per target, because
   the subject embeds the repo and GitHub Environment:

   ```bash
   databricks account service-principal-federation-policy create <SP_NUMERIC_ID> --json '{
     "oidc_policy": {
       "issuer": "https://token.actions.githubusercontent.com",
       "audiences": ["<DATABRICKS_ACCOUNT_ID>"],
       "subject": "repo:dediggibyte/datalab:environment:<target>"
     }
   }'
   ```

   The subject is environment-style because the CI/CD jobs declare
   `environment: <target>`. If a deploy fails with `TOKEN_SUBJECT_INVALID` /
   `TOKEN_INVALID`, copy the exact subject/audience strings from the error
   into the policy.
3. **GitHub Environment** named exactly `<target>`
   (repo Settings → Environments):
   - secrets: `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` (the SP application ID)
   - optional variables: `DATALAB_CATALOG`, `DATALAB_SALES_LANDING_PATH`,
     `DATALAB_READER_GROUP`, `DATALAB_ENGINEER_GROUP`
     (forwarded as `--var` overrides; empty → `databricks.yml` defaults)
   - for `prod`: add required reviewers so deploys need approval.
   - Environments without secrets are skipped gracefully by the deploy gate
     (the merge stays green until stage/prod are provisioned).
4. **Unity Catalog bootstrap** (one time, before the first deploy):
   create the persona groups (`databricks groups create` or the account
   console — `dl_sales_readers`, `dl_sales_engineers` for stage/prod), then
   `make bootstrap-uc TARGET=<target> WAREHOUSE_ID=<sql-warehouse-id>` to
   create the catalog, medallion + landing/exports schemas, volumes, and
   GRANTs. Dry-run first by omitting `WAREHOUSE_ID`. The SP also needs
   CREATE/USE on the target catalog (step 1).

## Release flow

```
feature branch ──PR──▶ main          # CI: lint+test+validate (+ template check)
        merge ▶ main                 # auto-deploy → dev
        tag v1.4.0-rc1               # CI + deploy → stage
        tag v1.4.0                   # CI + deploy → prod
```

## Local equivalents

CI and the Makefile run the same commands, so green locally ≈ green in CI:

```bash
make lint && make test && make validate
```
