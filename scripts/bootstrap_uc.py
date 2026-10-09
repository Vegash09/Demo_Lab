"""One-time Unity Catalog bootstrap per target: catalog, schemas, volumes, grants.

Deliberately OUT-OF-BAND of the bundle lifecycle so `databricks bundle destroy`
can never touch governance state. Idempotent: every statement is
CREATE ... IF NOT EXISTS or a re-runnable GRANT.

Default is a dry run that prints the SQL for review. Apply it with:

    make bootstrap-uc TARGET=dev WAREHOUSE_ID=<sql-warehouse-id> PROFILE=<cli-profile>

PROFILE picks the workspace — the SDK otherwise uses the DEFAULT CLI profile, which
may point at a different (or invalid) workspace than the bundle target. On a
Default-Storage metastore SQL CREATE CATALOG needs a location, so create the domain
catalogs in the UI first and pass SKIP_CATALOGS=1 (--skip-catalogs) to set up only
schemas/volumes/grants, or pass a MANAGED LOCATION. It runs `uv run --with
databricks-sdk` so the SDK never enters uv.lock (the dev venv stays pyspark-only —
databricks-connect/sdk conflicts, see AGENTS.md). Group CREATION is
manual, and the SCOPE matters — see below. This script only grants to groups.

GROUPS: WORKSPACE vs ACCOUNT — these are NOT the same principal
--------------------------------------------------------------
* the bundle's `permissions:` blocks (rbac.yml -> pipeline/job ACLs) resolve
  WORKSPACE groups:  `databricks groups create --profile <workspace>`
* Unity Catalog GRANT resolves ACCOUNT groups:
  `databricks account groups create --profile <account>`  (account-admin auth)

A workspace-local group is INVISIBLE to Unity Catalog: granting to one fails
with PRINCIPAL_DOES_NOT_EXIST even though the group is plainly listed in the
workspace UI. Databricks documents this — workspace-local groups "cannot be
granted access to data in a Unity Catalog metastore" — but the failure gives no
hint about scope, so it reads as a typo. Create the personas at ACCOUNT level and
assign them to the workspace (`databricks account workspace-assignment update`).

Pass --skip-grants to provision catalogs/schemas/volumes alone when the account
groups do not exist yet (e.g. a dev workspace where the catalog creator already
owns everything).
"""

from __future__ import annotations

import argparse
import sys

# The per-target domain catalogs and persona groups are RESOLVED from the bundle
# files (variables/medallion.yml + targets/<t>.yml + rbac.yml) through the domain
# registry — no hardcoded per-target dicts to keep in sync anymore. Adding a
# domain = one entry in scripts/domains.py DOMAINS.
from domains import (
    ARTIFACTS_SCHEMA,
    WHEELS_VOLUME,
    catalogs,
    extra_schemas_by_catalog,
    groups,
    targets,
)

BASE_SCHEMAS = ["bronze", "silver", "gold"]
VOLUME_SCHEMAS = ["landing", "exports"]  # only for catalogs with edge-lane volumes

# The CI/CD deploy service principal (GitHub OIDC) — needs full rights on the
# catalog it deploys pipelines/tables into. Keep in sync with docs/CICD.md.
DEPLOY_SP = "437346a1-0b53-418a-80d4-abaf2586ed97"


def _catalog_sql(
    catalog: str,
    reader: str,
    engineer: str,
    location: str,
    edge_volume: str | None,
    extra_schemas: list[str] | None = None,
    create_catalog: bool = True,
    grants: bool = True,
) -> list[str]:
    """Idempotent DDL + grants for ONE domain catalog. Engineers get build rights
    across the medallion; readers get silver+gold reads; bronze stays
    engineer-only. Every catalog also gets an `artifacts.wheels` volume holding
    the datalab framework wheel for THIS project's pipelines (published by
    `make publish-wheel`). Volume catalogs (customer_sales) additionally get the
    Auto Loader landing + export volumes, NAMED by the domain registry's
    ``edge_volume`` field (scripts/domains.py) so they always match the volume
    segment of the domain's landing/export path variables. ``create_catalog=False``
    skips the CREATE CATALOG statement when the catalog already exists (e.g. made
    via the UI on a Default-Storage metastore, where SQL CREATE CATALOG needs an
    explicit location) — schemas/volumes/grants still run."""
    with_volumes = edge_volume is not None
    schemas = (
        BASE_SCHEMAS
        + list(extra_schemas or [])
        + [ARTIFACTS_SCHEMA]
        + (VOLUME_SCHEMAS if with_volumes else [])
    )
    stmts = []
    if create_catalog:
        stmts.append(f"CREATE CATALOG IF NOT EXISTS `{catalog}`{location}")

    if not grants:
        # Structure only — for a workspace whose ACCOUNT-level persona groups do
        # not exist yet (UC cannot see workspace-local groups; see the module
        # docstring). The catalog creator already owns everything created here.
        stmts += [f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{s}`" for s in schemas]
        stmts.append(
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{ARTIFACTS_SCHEMA}`.`{WHEELS_VOLUME}`"
        )
        if with_volumes:
            stmts += [
                f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`landing`.`{edge_volume}`",
                f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`exports`.`{edge_volume}`",
            ]
        return stmts
    # The deploy SP owns everything the bundle creates in this catalog — and, by
    # privilege inheritance, can write the framework wheel into the volume.
    stmts.append(f"GRANT ALL PRIVILEGES ON CATALOG `{catalog}` TO `{DEPLOY_SP}`")
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
    stmts += [
        f"GRANT CREATE TABLE, SELECT, MODIFY ON SCHEMA `{catalog}`.`{schema}` TO `{engineer}`"
        for schema in (extra_schemas or [])
    ]
    # Framework-wheel volume: `make publish-wheel` uploads the datalab wheel here;
    # this domain's pipeline/job run-as identities install from it (READ). The
    # deploy SP writes via its catalog-level ALL; engineers get WRITE for local
    # `make publish-wheel`.
    stmts += [
        f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{ARTIFACTS_SCHEMA}`.`{WHEELS_VOLUME}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{ARTIFACTS_SCHEMA}` TO `{engineer}`",
        f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`{ARTIFACTS_SCHEMA}`.`{WHEELS_VOLUME}` TO `{engineer}`",
        f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{ARTIFACTS_SCHEMA}` TO `{reader}`",
        f"GRANT READ VOLUME ON VOLUME `{catalog}`.`{ARTIFACTS_SCHEMA}`.`{WHEELS_VOLUME}` TO `{reader}`",
    ]
    if with_volumes:
        stmts += [
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`landing`.`{edge_volume}`",
            f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`exports`.`{edge_volume}`",
            f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`landing`.`{edge_volume}` TO `{engineer}`",
            f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME `{catalog}`.`exports`.`{edge_volume}` TO `{engineer}`",
            f"GRANT READ VOLUME ON VOLUME `{catalog}`.`exports`.`{edge_volume}` TO `{reader}`",
        ]
    return stmts


def bootstrap_sql(
    target: str, managed_location: str = "", create_catalogs: bool = True,
    grants: bool = True,
) -> list[str]:
    """Idempotent DDL + grants for ``target``: every domain catalog (the
    customer_sales medallion + the pipeline-only ``sales`` catalog), each
    including the `artifacts.wheels` volume that holds the datalab framework
    wheel for that domain's pipelines.

    On a metastore WITHOUT a storage root (Default Storage), SQL CREATE CATALOG
    needs a location: either pass ``managed_location`` for fresh catalogs, or —
    if the catalogs already exist (created via the UI) — set
    ``create_catalogs=False`` to skip CREATE CATALOG and just ensure the
    schemas/volumes/grants."""
    who = groups(target)
    reader = who["reader"]
    engineer = who["engineer"]
    location = f" MANAGED LOCATION '{managed_location}'" if managed_location else ""
    stmts: list[str] = []
    extras = extra_schemas_by_catalog(target)
    for catalog, edge_volume in catalogs(target):
        stmts += _catalog_sql(
            catalog,
            reader,
            engineer,
            location,
            edge_volume,
            extras.get(catalog, []),
            create_catalogs,
            grants,
        )
    return stmts


def preflight_storage_root(profile: str | None, *, managed_location: str, creating: bool) -> None:
    """Fail BEFORE executing DDL when CREATE CATALOG cannot possibly succeed.

    On a metastore with no storage root (accounts with Default Storage enabled),
    `CREATE CATALOG` fails with:

        Metastore storage root URL does not exist. Default Storage is enabled in
        your account. You can use the UI to create a new catalog using Default
        Storage, or please provide a storage location for the catalog.

    Without this check that surfaces as a bare failure on statement #1, after the
    run has already begun — and the remedy is not obvious, because the API cannot
    help either: `CreateCatalog` has no default-storage field at all (an
    unresolved CLI gap, databricks/cli#4513), so `databricks catalogs create`
    fails the same way. The workable paths are all listed below.

    Degrades to a no-op if the metastore cannot be inspected — a permissions
    quirk must never block a bootstrap that would otherwise succeed.
    """
    if not creating or managed_location:
        return
    try:
        from databricks.sdk import WorkspaceClient

        client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
        summary = client.metastores.summary()
        storage_root = getattr(summary, "storage_root", None)
    except Exception as exc:  # noqa: BLE001 — advisory only
        print(f"note: could not inspect the metastore ({exc}); skipping the storage-root preflight")
        return

    if storage_root:
        return

    raise SystemExit(
        "this metastore has NO storage root (Default Storage), so `CREATE CATALOG` "
        "will fail — and the Catalogs API cannot create a Default-Storage catalog "
        "either (databricks/cli#4513). Pick one:\n"
        "  1. Reuse an existing catalog's location:\n"
        "       databricks catalogs get <existing-catalog> --profile <p>   # read .storage_root\n"
        "       make bootstrap-uc ... MANAGED_LOCATION=<that storage_root>\n"
        "  2. Create the catalog once in the UI (or with `databricks catalogs create "
        "--storage-root <url>`), then re-run with SKIP_CATALOGS=1.\n"
        "  3. On a SERVERLESS workspace, run `CREATE CATALOG <name>` from a serverless "
        "SQL warehouse — Default Storage applies the location automatically — then "
        "re-run with SKIP_CATALOGS=1."
    )


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
    parser.add_argument("--target", choices=targets(), required=True)
    parser.add_argument("--apply", action="store_true", help="execute (default: print SQL only)")
    parser.add_argument("--warehouse-id", default="", help="SQL warehouse id (required with --apply)")
    parser.add_argument("--profile", default="", help="Databricks CLI profile (default: ambient auth)")
    parser.add_argument(
        "--managed-location",
        default="",
        help="catalog MANAGED LOCATION (required on metastores without a storage root)",
    )
    parser.add_argument(
        "--skip-grants",
        action="store_true",
        help="create catalogs/schemas/volumes only, no GRANTs — for a workspace where the "
        "ACCOUNT-level persona groups do not exist yet (UC does not resolve workspace-local "
        "groups; granting to one fails PRINCIPAL_DOES_NOT_EXIST)",
    )
    parser.add_argument(
        "--skip-catalogs",
        action="store_true",
        help="skip CREATE CATALOG (the domain catalogs already exist, e.g. created via the "
        "UI on a Default-Storage metastore); still ensures schemas/volumes/grants",
    )
    args = parser.parse_args(argv)

    statements = bootstrap_sql(
        args.target,
        args.managed_location,
        create_catalogs=not args.skip_catalogs,
        grants=not args.skip_grants,
    )
    if not args.apply:
        print(f"-- dry run for target '{args.target}' — re-run with --apply to execute\n")
        print(";\n".join(statements) + ";")
        return
    if not args.warehouse_id:
        parser.error("--apply requires --warehouse-id")
    preflight_storage_root(
        args.profile or None,
        managed_location=args.managed_location,
        creating=not args.skip_catalogs,
    )
    apply(statements, args.warehouse_id, args.profile or None)
    print(f"bootstrap complete for target '{args.target}'")


if __name__ == "__main__":
    main(sys.argv[1:])
