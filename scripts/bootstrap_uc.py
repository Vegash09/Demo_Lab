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

# Catalog per target — keep in sync with databricks.yml `targets.*.variables`.
CATALOGS = {
    "dev": "customer_sales",
    "stage": "customer_sales_stage",
    "prod": "customer_sales_prod",
}

# Persona groups per target — keep in sync with databricks.yml
# reader_group / engineer_group variables.
GROUPS = {
    "dev": {"reader": "demo_analyst", "engineer": "Data Science group"},
    "stage": {"reader": "dl_sales_readers", "engineer": "dl_sales_engineers"},
    "prod": {"reader": "dl_sales_readers", "engineer": "dl_sales_engineers"},
}

SCHEMAS = ["bronze", "silver", "gold", "landing", "exports"]


def bootstrap_sql(target: str) -> list[str]:
    """Idempotent DDL + grants for one target. Readers see gold (and silver
    for engineers); bronze/landing stay engineer-only; volumes back the
    Auto Loader source and the export job."""
    catalog = CATALOGS[target]
    reader = GROUPS[target]["reader"]
    engineer = GROUPS[target]["engineer"]
    stmts = [f"CREATE CATALOG IF NOT EXISTS `{catalog}`"]
    stmts += [f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{s}`" for s in SCHEMAS]
    stmts += [
        f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`landing`.`sales`",
        f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`exports`.`sales`",
        # Engineers: full build rights on the medallion + both volumes.
        f"GRANT USE CATALOG, USE SCHEMA, CREATE SCHEMA ON CATALOG `{catalog}` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`bronze` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`silver` TO `{engineer}`",
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`gold` TO `{engineer}`",
        f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`landing`.`sales` TO `{engineer}`",
        f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`exports`.`sales` TO `{engineer}`",
        # Readers: consumption only — gold + silver reads, export pickup.
        f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{reader}`",
        f"GRANT USE SCHEMA, SELECT ON SCHEMA `{catalog}`.`silver` TO `{reader}`",
        f"GRANT USE SCHEMA, SELECT ON SCHEMA `{catalog}`.`gold` TO `{reader}`",
        f"GRANT READ VOLUME ON VOLUME `{catalog}`.`exports`.`sales` TO `{reader}`",
    ]
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
    args = parser.parse_args(argv)

    statements = bootstrap_sql(args.target)
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
