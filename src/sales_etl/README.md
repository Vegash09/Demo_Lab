# sales_etl — the sales domain (framework adopter)

Everything the sales domain owns, kept OUTSIDE the reusable framework
(`src/datalab/`) so the framework lifts into other projects untouched:

```
transformations/
  pipeline.py       3-line LDP entrypoint: generate(spark, datalab.config_dir)
transforms/
  sales.py          pure DataFrame functions, registered @transform("sales.*")
checks/
  __init__.py       custom dqx check functions (@check_function)
```

The datasets themselves are declared in `config/sales/{bronze,silver,gold}.yml`
(this folder's python is referenced from there via the `imports:` list and
transform registry names — see `docs/FRAMEWORK.md`).

Conventions:

- Business logic = pure functions here, with unit tests in `tests/`.
- No hand-written `dp.*` wiring — the framework generates all LDP objects.
- Parameters come from the pipeline `configuration` mapping (bundle
  variables); never hardcode catalogs, schemas, or paths.
- This package is listed in `[tool.hatch.build.targets.wheel]` so the
  pipeline/job environments can import it.

Run a development refresh:

```bash
make run          # databricks bundle run sales_etl -t dev
```
