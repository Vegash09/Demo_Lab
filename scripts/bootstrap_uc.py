"""One-time Unity Catalog bootstrap per target: catalog, schemas, volumes, grants.

Deliberately OUT-OF-BAND of the bundle lifecycle so `databricks bundle destroy`
can never touch governance state. Idempotent: every statement is
CREATE ... IF NOT EXISTS or a re-runnable GRANT.

Default is a dry run that prints the SQL for review. Apply it with:

    make bootstrap-uc TARGET=dev WAREHOUSE_ID=<sql-warehouse-id>

which runs `uv run --with databricks-sdk` so the SDK never enters uv.lock
(the dev venv stays pyspark-only — databricks-connect/sdk conflicts, see
AGENTS.md). Group CREATION is workspace/account-level and stays manual:
`databricks groups create` — this script only grants to groups.
"""

from __future__ import annotations

import argparse
import sys

# Domain catalogs to provision per target, each as (catalog, with_volumes).
# `with_volumes` controls the edge-lane Auto Loader landing + export volumes
# (customer_sales only). The datalab framework wheel does NOT live here — it has
# its own SHARED catalog (ARTIFACTS_CATALOGS below). Keep in sync with
# databricks.yml targets.*.variables (catalog, sales_catalog).
CATALOGS = {
    "dev":   [("customer_sales",       True), ("sales",       False)],
    "stage": [("customer_sales_stage", True), ("sales_stage", False)],
    "prod":  [("customer_sales_prod",  True), ("sales_prod",  False)],
}

# The SHARED framework-artifacts catalog per target — hosts exactly ONE thing: the
# common datalab framework wheel under `framework.wheels`, installed by every
# pipeline/job environment across ALL domains (one upload, one source of truth;
# see variables/medallion.yml var.datalab_artifacts_catalog + var.datalab_wheel).
# Keep in sync with databricks.yml targets.*.variables.datalab_artifacts_catalog.
ARTIFACTS_CATALOGS = {
    "dev":   "datalab_artifacts",
    "stage": "datalab_artifacts_stage",
    "prod":  "datalab_artifacts_prod",
}

# Persona groups per target — keep in sync with rbac.yml
# reader_group / engineer_group variables.
GROUPS = {
    "dev": {"reader": "demo_analyst", "engineer": "Data Science group"},
    "stage": {"reader": "dl_sales_readers", "engineer": "dl_sales_engineers"},
    "prod": {"reader": "dl_sales_readers", "engineer": "dl_sales_engineers"},
}

BASE_SCHEMAS = ["bronze", "silver", "gold"]
VOLUME_SCHEMAS = ["landing", "exports"]  # only for catalogs with edge-lane volumes
# The shared framework-artifacts catalog (ARTIFACTS_CATALOGS) holds the common
# datalab FRAMEWORK wheel under this schema/volume — installed by every
# pipeline/job environment across all domains (make publish-wheel; see
# variables/medallion.yml var.datalab_wheel + AGENTS.md "Wheel delivery").
FRAMEWORK_SCHEMA = "framework"
FRAMEWORK_VOLUME = "wheels"

# The CI/CD deploy service principal (GitHub OIDC) — needs full rights on the
# catalog it deploys pipelines/tables into. Keep in sync with docs/CICD.md.
DEPLOY_SP = "437346a1-0b53-418a-80d4-abaf2586ed97"


def _catalog_sql(
    catalog: str, reader: str, engineer: str, location: str, with_volumes: bool
) -> list[str]:
    """Idempotent DDL + grants for ONE domain catalog. Engineers get build rights
    across the medallion; readers get silver+gold reads; bronze stays
    engineer-only. Volume catalogs (customer_sales) additionally get the Auto
    Loader landing + export volumes and their grants. The framework wheel lives in
    the SHARED artifacts catalog (_artifacts_catalog_sql), not here."""
    schemas = BASE_SCHEMAS + (VOLUME_SCHEMAS if with_volumes else [])
    stmts = [
        f"CREATE CATALOG IF NOT EXISTS `{catalog}`{location}",
        # The deploy SP owns everything the bundle creates in this catalog.
        f"GRANT ALL PRIVILEGES ON CATALOG `{catalog}` TO `{DEPLOY_SP}`",
    ]
    stmts += [f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{s}`" for s in schemas]
    stmts += [
        f"GRANT USE CATALOG, USE SCHEMA, CREATE SCHEMA ON CATALOG `{catalog}` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`bronze` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`silver` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`gold` TO `{engineer}`",
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{reader}`",
        f"GRANT USE SCHEMA, SELECT ON SCHEMA `{catalog}`.`silver` TO `{reader}`",
        f"GRANT USE SCHEMA, SELECT ON SCHEMA `{catalog}`.`gold` TO `{reader}`",
    ]
    if with_volumes:
        stmts += [
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`landing`.`sales`",
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`exports`.`sales`",
            f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`landing`.`sales` TO `{engineer}`",
            f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`exports`.`sales` TO `{engineer}`",
            f"GRANT READ VOLUME ON VOLUME `{catalog}`.`exports`.`sales` TO `{reader}`",
        ]
    return stmts


def _artifacts_catalog_sql(
    catalog: str, reader: str, engineer: str, location: str
) -> list[str]:
    """Idempotent DDL + grants for the SHARED framework-artifacts catalog. Holds
    exactly ONE thing: the common datalab framework wheel under `framework.wheels`,
    published by `make publish-wheel` / CI and installed by every pipeline and job
    environment across ALL domains. The deploy SP owns it (publishes; the
    serverless run-as installs); engineers get READ+WRITE (local publish), readers
    READ — so any pipeline/job run-as identity can install the wheel."""
    return [
        f"CREATE CATALOG IF NOT EXISTS `{catalog}`{location}",
        f"GRANT ALL PRIVILEGES ON CATALOG `{catalog}` TO `{DEPLOY_SP}`",
        f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{FRAMEWORK_SCHEMA}`",
        f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{FRAMEWORK_SCHEMA}`.`{FRAMEWORK_VOLUME}`",
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{engineer}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{FRAMEWORK_SCHEMA}` TO `{engineer}`",
        f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`{FRAMEWORK_SCHEMA}`.`{FRAMEWORK_VOLUME}` TO `{engineer}`",
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{reader}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{FRAMEWORK_SCHEMA}` TO `{reader}`",
        f"GRANT READ VOLUME ON VOLUME `{catalog}`.`{FRAMEWORK_SCHEMA}`.`{FRAMEWORK_VOLUME}` TO `{reader}`",
    ]


def bootstrap_sql(target: str, managed_location: str = "") -> list[str]:
    """Idempotent DDL + grants for ``target``: the SHARED framework-artifacts
    catalog (the common datalab wheel) plus every domain catalog (the
    customer_sales medallion + the pipeline-only ``sales`` catalog).

    ``managed_location`` is required on metastores without a storage root
    (e.g. Default Storage accounts) — use the same path as the workspace's
    existing catalogs."""
    reader = GROUPS[target]["reader"]
    engineer = GROUPS[target]["engineer"]
    location = f" MANAGED LOCATION '{managed_location}'" if managed_location else ""
    # The shared framework-wheel catalog first (every domain's pipelines install
    # from it), then each domain's medallion + edge-lane volumes.
    stmts: list[str] = _artifacts_catalog_sql(
        ARTIFACTS_CATALOGS[target], reader, engineer, location
    )
    for catalog, with_volumes in CATALOGS[target]:
        stmts += _catalog_sql(catalog, reader, engineer, location, with_volumes)
    return stmts


def apply(statements: list[str], warehouse_id: str, profile: str | None) -> None:
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    for stmt in statements:
        print(f"  applying: {stmt}")
        resp = client.statement_execution.execute_statement(
            statement=stmt, warehouse_id=warehouse_id, wait_timeout="50s"
        )
        state = resp.status.state.value if resp.status and resp.status.state else "?"
        if state != "SUCCEEDED":
            error = resp.status.error.message if resp.status and resp.status.error else state
            raise SystemExit(f"FAILED: {stmt}\n  -> {error}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--apply", action="store_true", help="execute (default: print SQL only)")
    parser.add_argument("--warehouse-id", default="", help="SQL warehouse id (required with --apply)")
    parser.add_argument("--profile", default="", help="Databricks CLI profile (default: ambient auth)")
    parser.add_argument(
        "--managed-location",
        default="",
        help="catalog MANAGED LOCATION (required on metastores without a storage root)",
    )
    args = parser.parse_args(argv)

    statements = bootstrap_sql(args.target, args.managed_location)
    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply to execute\n")
        print(";\n".join(statements) + ";")
        return
    if not args.warehouse_id:
        parser.error("--apply requires --warehouse-id")
    apply(statements, args.warehouse_id, args.profile or None)
    print(f"bootstrap complete for target '{args.target}'")


if __name__ == "__main__":
    main(sys.argv[1:])
