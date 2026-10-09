# Lakeflow Connect — Managed MySQL CDC Ingestion

How to set up Databricks-managed Lakeflow Connect CDC ingestion for a MySQL
source, and the operational prerequisites that must be in place before the
rendered resources may be deployed.

Status: staged config, not live deployed. The framework-style source config and
the rendered resource examples are checked in, but no Lakeflow Connect gateway
or ingestion pipeline is deployed until a real UC Connection, run-as identity,
and source grants exist.

## Current safety boundary

The bundle manifest includes only the live `resources/*.yml` glob. In the
template repo the MySQL gateway, ingestion pipeline, and optional schedule
examples live under `projects/customer_sales/resources/examples/`, which sits
OUTSIDE that glob, so a merge to `main` (which auto-deploys dev) will not create
unresolvable placeholder resources.

In the template repo the downstream bronze example likewise lives under
`projects/customer_sales/config/customer_sales/bronze/examples/`, so the live
`customer_sales` ETL pipeline graph does not read a raw table that Lakeflow
Connect has not created yet. An adopter keeps the same split one level up:
`resources/examples/` and `config/<catalog>/bronze/examples/`.

## Framework-owned source config

The framework owns the ingestion source-config contract and the renderer; the
adopter repo supplies only the source config plus deployment, permissions, and
environment variables. The config shape is
`lakeflow_connect_ingestion_source`, and it lives under
`config/<catalog>/ingestion/<connector>/<source>.yml`.

In the template repo that file is
`projects/customer_sales/config/customer_sales/ingestion/mysql/customer_sales_mysql.yml`;
an adopter keeps the same file at `config/<catalog>/ingestion/mysql/<source>.yml`.

<!-- adopter-if:schemas start -->
It deliberately carries no `$schema` line yet: `schemas/` is GENERATED from the
PINNED framework release, and `ingestion_source.schema.json` only exists once
the pin moves to framework v2.0.0 (`make bump-framework VERSION=2.0.0`). Adding
the vendored schema by hand fails `make check-schemas`.
<!-- adopter-if:schemas end -->
<!-- adopter-if:!schemas start -->
It carries no `$schema` line: editor schema validation is not enabled in this
repo, and the source config is validated by the framework renderer instead.
<!-- adopter-if:!schemas end -->

Once the framework pin is on v2.0.0, render the live resources with the
framework renderer:

```
python -m datalab.framework.ingestion render \
  --source config/<catalog>/ingestion/mysql/<source>.yml \
  --out resources \
  --check
```

Until then, the checked-in example files show the expected rendered shape but
stay outside the bundle include glob.

## What must exist before promoting examples to live resources

Before moving rendered files from `resources/examples/` into the live
`resources/` directory:

1. Create the UC Connection named by `gateway.connection_name` in the source
   config. Never store host/user/password in this repo.
2. Ensure the run-as and deploy identities have Unity Catalog grants AND the
   required cloud-storage / external-location access. UC grants alone are not
   sufficient for the gateway to run.
3. Run the UC bootstrap for the target so the ingestion schemas exist in the
   domain catalog (`make bootstrap-uc TARGET=<t>`):
   - `mysql_raw` — where Lakeflow Connect lands replicated tables
   - `mysql_gateway_meta` — the gateway's own CDC bookkeeping/staging
4. Verify source MySQL binlog retention is at least 7 days and sized against the
   largest table's expected full-refresh recovery time: there is no manual
   binlog-position reset, so a binlog gap forces a full refresh of every table
   on that gateway.
5. Move the bronze example into the live bronze config directory only after the
   managed ingestion destination table actually exists.

## Rendered resource shape

One source config renders exactly one gateway and one ingestion pipeline. The
ingestion pipeline references the gateway by bundle expression rather than a
hardcoded id, using the gateway's resource key:

```
ingestion_definition.ingestion_gateway_id:
  ${resources.pipelines.<gateway_resource_key>.id}
```

A pipeline with `ingestion_definition` must NOT also set top-level `catalog`,
`target`, `schema`, or `libraries`; destination catalog/schema/table are
per-object fields inside `ingestion_definition`. There is also no `pipeline_type`
field on the DAB pipeline resource — the presence of `gateway_definition` is
what makes a pipeline a gateway.

The gateway is `continuous: true` (binlog capture); the ingestion pipeline is
`continuous: false` and job-triggered. The optional schedule example ships
`pause_status: PAUSED` and must stay paused until the connection, identity, and
source grants are verified.

Managed-ingestion tables expose no `CLUSTER BY` authoring surface, so the
ingestion pipeline keeps an `optimizeWrite` + bounded-retention `configuration:`
block as the only pipeline-native lever against small-file growth and unbounded
Delta log retention.

## Downstream bronze CDC read semantics

Lakeflow Connect writes Delta tables outside the SDP graph. A promoted bronze
reader consumes them with `source.kind: table` — bronze does not care whether
Auto Loader or Lakeflow Connect produced the upstream table.

When the managed destination is an SCD1 / CDC-updated table, the bronze stream
MUST set `options: {skipChangeCommits: "true"}`; without it the stream fails the
moment an upstream update or delete rewrites files.

## Testing contract

The domain's MySQL ingestion contract test asserts:

- no MySQL gateway/ingestion/schedule resource sits in the live bundle resource
  glob while no real source exists;
- the source config and the rendered examples contain no `REPLACE_ME`
  placeholders;
- the example gateway/ingestion resources agree with the source config
  (connection name, schemas, source/destination table names);
- the optional schedule remains `PAUSED`;
- the bronze example sets `skipChangeCommits`;
- UC bootstrap emits the `mysql_raw` / `mysql_gateway_meta` schema DDL and the
  matching engineer grants.

Once a real instance is deployed, add a second tier: a job/notebook task that
queries `system.information_schema.tables` for gateway staging growth and the
pipeline event log for consecutive failures. There is no platform circuit
breaker on repeated failures — alert externally.

## Known limitations to design around

- No manual binlog-position reset: a purged binlog forces a full refresh of every
  table on that gateway.
- All-or-nothing per gateway: one table's binlog gap blocks every table sharing
  it, including healthy ones.
- Gateway staging can grow far larger than the source (an observed 100MB source
  produced 4-5GB of staging) with no documented materialization SLA — keep it in
  its own schema and monitor it independently.
- Schema evolution is only partially automatic: new non-spatial columns
  auto-ingest; dropped source columns are NOT removed at the destination;
  `TRUNCATE`, type/rename changes, `DROP COLUMN`, `ADD PRIMARY KEY`, and spatial
  columns all require a full refresh.
- A Beta "integrated CDC pipeline" (single pipeline, no separate gateway) removes
  several of these, but it is not GA, needs workspace enablement, and has no
  in-place migration path from the gateway + ingestion pattern.

## Adding a real MySQL source

1. Copy or edit the ingestion source config for the real UC Connection and table
   mappings. Use realistic but non-secret identifiers only.
2. Render it with the framework renderer into the live resources directory, then
   re-run the renderer with `--check` so CI catches drift.
3. Add the matching bronze config in the live bronze directory only when the raw
   destination table exists.
4. Run the domain contract tests, `make validate-configs`, and
   `databricks bundle validate -t dev` before requesting review.
