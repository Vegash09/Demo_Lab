"""Validate ONE dataset against a LIVE Databricks cluster via Databricks Connect.

Runs the framework's ``run_dataset`` path (loader → column mapping → transforms
→ dqx → valid/quarantine) on real cluster compute and Unity Catalog data,
WITHOUT deploying the bundle. This is the "test/validate from local" lane that
complements the OSS local run (``make run-local``) and the dev refresh.

Databricks Connect is deliberately ISOLATED from the dev venv (it conflicts with
the ``pyspark`` dev dependency). Run it through the out-of-lock overlay:

    make validate-connect LAYER=silver TABLE=customers \
        CONNECT_ARGS="--param datalab.catalog=customer_sales --param datalab.bronze_schema=bronze"

which expands to an isolated ``uv run --no-project`` overlay installing the
framework (from the pinned git dep), the domain package (editable), and
databricks-connect — none of which enter uv.lock (the root project is package-less
and so cannot supply the framework or domain itself).

Because there is no pipeline ``configuration`` mapping off-Databricks, pass every
conf key the dataset resolves (catalog/schema of its source, plus any path/topic
confs) via repeatable ``--param key=value`` — run_dataset reads them directly.

Auth comes from the Databricks SDK environment: DATABRICKS_HOST plus a token or
``DATABRICKS_CONFIG_PROFILE``, and DATABRICKS_CLUSTER_ID (or serverless). See
docs/FRAMEWORK.md "Validate via Databricks Connect".

NOTE: Auto Loader (cloud_files) and AUTO CDC are engine-owned and are NOT
executed here — Connect validates the DataFrame logic (mapping/transforms/dqx)
against real data; the SCD merge itself is verified by a dev refresh.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", required=True, help="domain config dir (holds domain.yml)")
    parser.add_argument("--layer", required=True, choices=["bronze", "silver", "gold"])
    parser.add_argument("--table", required=True, help="target table (dataset) name")
    parser.add_argument("--flow", default=None, help="fan-in source / backfill entry to preview")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="pipeline conf the dataset resolves, e.g. datalab.catalog=customer_sales; repeatable",
    )
    args = parser.parse_args(argv)

    params: dict[str, str] = {}
    for item in args.param:
        if "=" not in item:
            parser.error(f"--param expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        params[key] = value

    # Imported here so a missing/incompatible install fails with a clear message.
    from databricks.connect import DatabricksSession

    from datalab.framework import run_dataset

    spark = DatabricksSession.builder.getOrCreate()
    res = run_dataset(
        spark,
        args.config_dir,
        args.layer,
        args.table,
        params=params or None,
        flow=args.flow,
    )

    print(f"dataset: {args.layer}.{args.table}" + (f" (flow {args.flow})" if args.flow else ""))
    if res.cdc_plan:
        print(res.cdc_plan)
    print(f"valid rows:      {res.valid_df.count()}")
    if res.quarantine_df is not None:
        print(f"quarantine rows: {res.quarantine_df.count()}")
    else:
        print("quarantine:      (none configured)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
