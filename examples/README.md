# examples/ — reference domains

The reusable framework lives in its **own repo**
([dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework)),
consumed here as a dependency; everything under `examples/` is **reference
material**: complete, working domains that show how a team adopts the framework
for bronze → silver → gold ETL. The bundle deploys them (they double as the
framework's integration test), but the framework does not depend on them — it
lifts into any project untouched.

```
examples/
  customer_sales/   the complete worked example: config-driven pipeline, edge
                    jobs, notebook triage, tests, ABAC SQL — start here
```

## How an example maps to YOUR repo

Each `examples/<catalog>/` folder is named after the **base Unity Catalog
catalog** the domain stores its data in, and **mirrors an adopter repo root**
— the full folder↔UC naming contract is [docs/NAMING.md](../docs/NAMING.md).
The layout transfers 1:1: copy the folder's contents to your repo root (next
to `databricks.yml` and `pyproject.toml`) and rename every `customer_sales`
token to your catalog name:

| In `examples/customer_sales/` | In your repo | What it is |
|---|---|---|
| `config/customer_sales/` | `config/<catalog>/` | `domain.yml` + ONE `<schema>/<table>.yml` artifact per target table (path == UC table FQN) |
| `src/customer_sales_etl/` | `src/<catalog>_etl/` | 3-line pipeline entrypoint, pure `@transform` functions, custom dqx checks |
| `src/jobs/customer_sales/` | `src/jobs/<catalog>/` | python-file lane (headless, side-effectful edge jobs) |
| `notebooks/customer_sales/` | `notebooks/<catalog>/` | notebook lane (human-gated, on-demand runs) |
| `resources/*.yml` | `resources/*.yml` | bundle resources — pipeline + jobs (paths inside are relative, they move as is) |
| `tests/` | `tests/` | the domain's own unit + contract tests |
| `sql/abac/` | `sql/abac/` | display-only row-filter/column-mask SQL (admin-applied, never run by CI) |

The two places an adopter wires a new domain up outside the copied folder:

1. `pyproject.toml` → register the domain as a `[tool.uv.workspace]` member, so
   it builds its own `<catalog>_etl` wheel for the pipeline/job environments.
2. `databricks.yml` → the `include:` glob already picks up `resources/*.yml`
   (this repo additionally globs `examples/*/resources/*.yml` to deploy the
   reference domains themselves).

Step-by-step: [docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md).
Wire your repo to the framework: [docs/ADOPTING.md](../docs/ADOPTING.md).
Authoring reference: the framework repo's [FRAMEWORK.md](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md).
Naming convention: [docs/NAMING.md](../docs/NAMING.md).
