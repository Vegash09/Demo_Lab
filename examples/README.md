# examples/ — reference domains

Everything under `src/` is the reusable framework; everything under
`examples/` is **reference material**: complete, working domains that show
how a team adopts the framework for bronze → silver → gold ETL. The bundle
deploys them (they double as the framework's integration test), but nothing
in the framework depends on them — delete this folder and `src/datalab`
still lifts into any project untouched.

```
examples/
  sales/        the complete worked example: config-driven pipeline, edge
                jobs, notebook triage, tests, ABAC SQL — start here
```

## How an example maps to YOUR repo

Each `examples/<domain>/` folder **mirrors an adopter repo root**, so the
layout transfers 1:1 — copy the folder's contents to your repo root (next to
`databricks.yml`, `pyproject.toml` and `src/datalab`) and rename `sales`:

| In `examples/sales/` | In your repo | What it is |
|---|---|---|
| `config/sales/` | `config/<domain>/` | `domain.yml` + ONE `<layer>/<table>.yml` artifact per target table |
| `src/sales_etl/` | `src/<domain>_etl/` | 3-line pipeline entrypoint, pure `@transform` functions, custom dqx checks |
| `src/jobs/sales/` | `src/jobs/<domain>/` | python-file lane (headless, side-effectful edge jobs) |
| `notebooks/sales/` | `notebooks/<domain>/` | notebook lane (human-gated, on-demand runs) |
| `resources/*.yml` | `resources/*.yml` | bundle resources — pipeline + jobs (paths inside are relative, they move as is) |
| `tests/` | `tests/` | the domain's own unit + contract tests |
| `sql/abac/` | `sql/abac/` | display-only row-filter/column-mask SQL (admin-applied, never run by CI) |

The two places an adopter wires a new domain up outside the copied folder:

1. `pyproject.toml` → `[tool.hatch.build.targets.wheel]` packages gets the
   domain package dir (so pipeline/job environments can import it).
2. `databricks.yml` → the `include:` glob already picks up `resources/*.yml`
   (this repo additionally globs `examples/*/resources/*.yml` to deploy the
   reference domains themselves).

Step-by-step: [docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md).
Authoring reference: [docs/FRAMEWORK.md](../docs/FRAMEWORK.md).
