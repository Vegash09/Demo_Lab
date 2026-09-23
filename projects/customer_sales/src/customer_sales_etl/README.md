# customer_sales_etl — the customer_sales domain (framework adopter)

Everything the customer_sales domain owns, kept OUTSIDE the reusable
framework (an external dependency — the `datalab-framework` repo) so the
framework lifts into other projects untouched. The package is named
`<catalog>_etl` per the repo naming contract
(`docs/NAMING.md`):

```
transformations/
  pipeline.py       3-line LDP entrypoint: generate(spark, datalab.config_dir)
transforms/
  customers.py      pure DataFrame functions, registered @transform("customer_sales.*")
checks/
  __init__.py       custom dqx check functions (@check_function)
```

The datasets themselves are declared in the artifacts under
`../../config/customer_sales/<schema>/<table>.yml` (this folder's python is
referenced from there via the `imports:` list and transform registry names —
see the framework repo's [`docs/FRAMEWORK.md`](https://github.com/dediggibyte/datalab-framework/blob/v1.0.0/docs/FRAMEWORK.md)).
The full tour of the example lives in
`projects/customer_sales/README.md`.

Conventions:

- Business logic = pure functions here, with unit tests in `tests/`.
- No hand-written `dp.*` wiring — the framework generates all LDP objects.
- Parameters come from the pipeline `configuration` mapping (bundle
  variables); never hardcode catalogs, schemas, or paths.
- This package is a uv-workspace member; its own `pyproject.toml`
  `[tool.hatch.build.targets.wheel]` builds the `customer_sales_etl` wheel the
  pipeline/job environments install (next to the framework wheel from the Volume).

Run a development refresh:

```bash
make run          # databricks bundle run customer_sales_etl -t dev
```
