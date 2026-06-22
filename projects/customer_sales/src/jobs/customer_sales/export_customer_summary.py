"""Export the gold customer summary as CSV to the sales export volume.

Python-file lane (spark_python_task): side-effectful by design, which is why
it lives here and not in an SDP dataset function. Reads the SDP-owned gold
table (read-only — the pipeline is the single writer) and snapshots it to the
export volume declared in ``resources/customer_sales_export.job.yml`` (next
to this example's src/).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from pyspark.sql import SparkSession

from datalab.config import fqn
from datalab.params import cli_params


def main(argv: Sequence[str] | None = None) -> None:
    params = cli_params(argv, ["catalog", "gold_schema", "export_path"])
    export_path = params["export_path"].rstrip("/")

    # The UC volume is per-environment, out-of-band setup. Fail fast instead of
    # letting Spark create a dev-shaped directory tree in the wrong workspace.
    if not os.path.isdir(export_path):
        raise FileNotFoundError(
            f"Export volume path {export_path!r} does not exist in this "
            "workspace. Create the UC volume for this environment first "
            "(see AGENTS.md, python-file lane rules)."
        )

    spark = SparkSession.builder.getOrCreate()
    source = fqn(params["catalog"], params["gold_schema"], "customers_by_city")

    (
        spark.read.table(source)
        .coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(f"{export_path}/customers_by_city")
    )


if __name__ == "__main__":
    main()
