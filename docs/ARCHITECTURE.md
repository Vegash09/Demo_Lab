# Architecture

[← README](../README.md) · **Architecture** · [Framework](FRAMEWORK.md) · [CI/CD](CICD.md) · [Migration](MIGRATION.md)

How datalab hangs together: from a GitHub push to running Lakeflow resources,
the three authoring lanes, the medallion data view, code organization, and
governance.

## System view

```mermaid
flowchart LR
    subgraph GH["GitHub"]
        DEV["developer / agent<br/>push · PR"] --> CI["Actions: ci-cd-{dev,stage,prod}<br/>common-ci: ruff + pytest + bundle validate"]
        CI -->|"OIDC — no stored secret"| CD["common-cd: bundle deploy"]
    end

    subgraph WS["Databricks workspace"]
        CD --> DAB["Declarative Automation Bundle<br/>databricks.yml + examples/*/resources/*.yml"]
        DAB --> PL["Lakeflow SDP pipeline: customer_sales_etl<br/>(serverless, environment_version 4)"]
        DAB --> JOB["job: customer_sales_etl_refresh<br/>daily pipeline_task · paused in dev"]
        DAB --> EXP["job: customer_sales_export<br/>weekly spark_python_task"]
        DAB --> QR["job: customer_sales_quarantine_report<br/>on-demand notebook_task"]
        JOB --> PL
    end
```

The bundle is the only thing that touches the workspace. CI validates it on
every PR; CD deploys it on merge (dev) and tags (stage/prod) — details in
[CICD.md](CICD.md).

## Execution profiles (run anywhere)

One config-driven codebase runs three ways; `datalab.profile` (a pipeline
`configuration` value, default `databricks`) selects the graph. Only the
Databricks profile is the deploy/production path — the other two are local
development aids. Details + fidelity caveats: [FRAMEWORK.md](FRAMEWORK.md)
"Run anywhere".

```mermaid
flowchart TD
    CFG["config/*.yml + @transform fns<br/>(one codebase)"] --> GEN["datalab.framework.generate(spark, cfg)"]
    GEN -->|"profile=databricks (default)"| DBX["writers.register_dataset<br/>streaming tables · AUTO CDC · cloud_files · dqx · sinks"]
    GEN -->|"profile=local"| LOC["local.register_dataset_local<br/>batch materialized views (mapping + transforms)"]
    DBX --> RUNDBX["Databricks: bundle deploy + refresh (production)"]
    LOC --> RUNLOC["local OSS: spark-pipelines run / dry-run<br/>(make run-local / dry-run-local)"]
    CFG --> RD["run_dataset (batch, no writes)"]
    RD -->|"isolated overlay"| CONN["Databricks Connect: live-cluster validation<br/>(make validate-connect)"]
```

- **Databricks** — the bundle deploys the full Lakeflow graph; the only profile
  that runs AUTO CDC, Auto Loader, dqx quarantine and sinks for real.
- **Local OSS** (`datalab.framework.local`) — downgrades to a batch
  materialized-view graph the `spark-pipelines` CLI runs on sample data; no
  AUTO CDC dedup / dqx / Auto Loader (OSS SDP can't express them).
- **Databricks Connect** — runs one dataset's mapping/transforms/dqx via
  `run_dataset` on a live cluster from an isolated, out-of-lock overlay.

## Three authoring lanes

The SDP pipeline owns **all medallion tables** (single-writer invariant).
Jobs work the lakehouse edges and only *read* pipeline-owned tables:

```mermaid
flowchart LR
    PL["SDP pipeline customer_sales_etl<br/>bronze → silver → gold<br/>(owns every medallion table)"]
    PL -->|read-only| EXP["customer_sales_export · python-file lane<br/>examples/customer_sales/src/jobs/customer_sales/export_customer_summary.py<br/>→ /Volumes/&lt;catalog&gt;/exports/sales/ (CSV)"]
    PL -->|read-only| QR["customer_sales_quarantine_report · notebook lane<br/>examples/customer_sales/notebooks/customer_sales/quarantine_report.py<br/>→ owns customers_quarantine_report"]
    QR -.->|"repaired rows re-enter<br/>via landing"| PL
```

Routing is the 3-question router (AGENTS.md, "Authoring rules"):

| New target is… | Lane | Mechanism |
|---|---|---|
| a managed medallion Delta table | **SDP via YAML config** (mandatory) | `config/<catalog>/<schema>/<table>.yml`; backfills via `backfill:` once-flows |
| headless, side-effectful edge work | **python-file** | `spark_python_task`: argparse + explicit `main()` |
| human-must-decide | **notebook** | `notebook_task`, no trigger; widgets mirror job parameters |

## Data view (medallion, generated from the customer_sales example's artifacts)

```mermaid
flowchart LR
    YML[["examples/customer_sales/config/customer_sales/*.yml<br/>Pydantic-validated artifacts<br/>(datasets + dqx rules)"]] -.->|"datalab.framework.generate"| BR
    LAND[("UC volume<br/>landing/sales/customers")] -->|"Auto Loader cloudFiles"| BR["bronze.customers_raw<br/>streaming_table + lineage cols"]
    BR --> IN["customers__input<br/>temporary view<br/>(rename + try_cast + customer_sales.normalize_email)"]
    IN --> CHK["customers__checked<br/>dqx apply_checks_by_metadata<br/>(_errors/_warnings)"]
    CHK -->|get_valid| VAL["customers__valid"]
    CHK -->|"get_invalid<br/>errors only"| QUAR["silver.customers_quarantine<br/>(dqx evidence structs)"]
    VAL -->|"AUTO CDC flow<br/>keys=[customer_id] · sequence_by=_ingest_ts · SCD1"| SIL["silver.customers<br/>create_streaming_table"]
    SIL --> GOLD["gold.customers_by_city<br/>materialized_view<br/>(customer_sales.summarize_customers_by_city)"]
```

Developers (and agents) edit YAML only; the framework validates configs with
Pydantic at pipeline import and registers every LDP object through
reader/writer adapters; data quality is databrickslabs/dqx end to end. The
artifact schema and semantics — including fan-in `sources:`, `backfill:`
once-flows, snapshot CDC, kafka in/out, and the SDP capability matrix — are
in [FRAMEWORK.md](FRAMEWORK.md).

## Code organization

```mermaid
flowchart TD
    subgraph REPO["repository"]
        FW["src/datalab/<br/>THE framework — models, adapters,<br/>generator, devtools, param helpers<br/>(zero domain code)"]
        subgraph DOMAIN["examples/&lt;domain&gt;/ — reference domain (adopters: repo root)"]
            CFG["config/&lt;domain&gt;/<br/>domain.yml + &lt;layer&gt;/&lt;table&gt;.yml"]
            DOM["src/&lt;domain&gt;_etl/<br/>pure @transform fns · custom dqx checks ·<br/>3-line pipeline entrypoint"]
            JOBS["src/jobs/ + notebooks/<br/>edge lanes"]
            RES["resources/<br/>the domain's bundle resources"]
            DTESTS["tests/<br/>the domain's own tests"]
        end
        TESTS["tests/<br/>framework tests — local SparkSession,<br/>example-free, no workspace"]
    end
    CFG -->|consumed by| FW
    DOM -->|registered into| FW
    TESTS -->|exercise| FW
```

Layer rules, deliberately separated:

1. **`src/datalab/`** — THE framework, the only package under `src/`
   (installed into the pipeline and job environments via
   `--editable ${workspace.file_path}`). Models, adapters, generator,
   devtools, param helpers; never contains domain code or hardcoded domain
   module paths. Unit-testable locally (`tests/`, example-free).
2. **`examples/<domain>/`** — complete reference domains, each mirroring an
   adopter repo root (`examples/README.md` has the mapping table): the YAML
   artifacts (`config/<domain>/`), the domain package (`src/<domain>_etl/`),
   the edge-lane entry points (`src/jobs/<domain>/`, `notebooks/<domain>/`),
   the domain's bundle `resources/` (relative paths, so the folder
   transplants to an adopter repo unchanged), and its own `tests/`.
3. **Parameterization, one fail-fast contract per lane**, no hardcoding
   anywhere: bundle variables → pipeline `configuration:` →
   `pipeline_conf(spark, key)` (SDP); bundle variables → job `parameters:` →
   widgets → `datalab.params.notebook_params` (notebook) or argv flags →
   `datalab.params.cli_params` (python-file).

Quality: dqx checks are defined per dataset in the layer YAML. The same list
drives the target's valid-row filter and the quarantine table, so the two can
never diverge; evidence lands as `_errors`/`_warnings` structs.

## Environments

| Target | Mode | Catalog (default) | Trigger state |
|---|---|---|---|
| dev | development — resources prefixed `[dev <user>]`, isolated per user | `customer_sales` | paused |
| stage | production | `customer_sales_stage` | live |
| prod | production | `customer_sales_prod` | live |

Catalogs and schemas are bundle variables; the same artifacts deploy to all
three targets unchanged.

## Access governance (RBAC / ABAC)

Three layers, each with one home:

```mermaid
flowchart TD
    L1["1 · Workspace-resource RBAC<br/>permissions: on every bundle resource<br/>(rbac.yml: group + permission-level variables)"]
    L2["2 · Unity Catalog RBAC<br/>grants-as-code: scripts/bootstrap_uc.py<br/>(out-of-band — bundle destroy never touches it)"]
    L3["3 · ABAC — row/column level<br/>sql/abac/ masks + row filters<br/>(display-only; admin reviews and applies)"]
    L1 --> L2 --> L3
```

- **Layer 1** controls who can run/manage pipelines and jobs: `permissions:`
  on every resource, driven by the group (`reader_group` / `engineer_group` /
  `admin_group`) and permission-level (`*_pipeline_level` / `*_job_level`)
  string variables in `rbac.yml` (include'd by `databricks.yml`, which keeps
  only the medallion variables). Both the groups AND their levels diverge per
  target (dev uses demo groups with broad levels; stage/prod use the
  `dl_sales_*` persona groups; prod tightens readers to `CAN_VIEW` and adds an
  `admin_group`) and per GitHub Environment (`DATALAB_READER_GROUP` /
  `DATALAB_ENGINEER_GROUP` repo variables → `deploy-dab` `--var`).
- **Layer 2** controls who can read/write the data: grants-as-code in
  `scripts/bootstrap_uc.py` — idempotent catalog/schema/volume DDL + GRANTs,
  applied once per target with `make bootstrap-uc`. Deliberately out-of-band
  of the bundle so `bundle destroy` never touches governance state. Readers
  get silver/gold SELECT + export-volume reads; engineers get medallion
  build rights; bronze/landing stay engineer-only.
- **Layer 3** is row/column-level policy: column masks and row filters under
  the domain's `sql/abac/` folder (this repo:
  `examples/customer_sales/sql/abac/`). Display-only by convention — agents and CI
  never execute them; an admin reviews and applies. SDP does offer a
  pipeline-level `row_filter`/column-mask surface (Public Preview); this
  repo deliberately does not use it — access policy stays admin-applied,
  out of the deploy path. Allowed constructs:
  `CREATE FUNCTION ... RETURN`, `ALTER TABLE ... SET MASK / SET ROW FILTER`,
  `is_account_group_member()`, `current_user()`. Re-runnable, function
  before ALTER, named `dl_mask_<purpose>` / `dl_rf_<purpose>`. Worked
  example: `examples/customer_sales/sql/abac/mask_customer_email.sql`.

Group creation stays account/workspace-level (`databricks groups create`) —
nothing in this repo creates principals.

---

Keep this document in sync with reality — it is part of the protected
documents-of-record surface (see AGENTS.md).
