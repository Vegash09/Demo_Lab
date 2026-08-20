# Changelog

All notable changes to **this repo** — `datalab-projects`, the reference domains
+ deploy bundle that consumes the [datalab
framework](https://github.com/dediggibyte/datalab-framework) — are documented
here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Changes to the FRAMEWORK itself live in the framework repo's own CHANGELOG.

**Scope.** This changelog tracks the bundle + reference domains and how they
consume the framework — the pinned framework version, the deploy/publish flow,
and the example domains under `projects/`.

**Two version knobs.** This repo's own version is `pyproject.toml`
`[project].version`. The FRAMEWORK version it pins lives in two places that MUST
move in lockstep: the `datalab` git tag in `pyproject.toml` `[tool.uv.sources]`
and `variables/medallion.yml` `datalab_version` (the Volume wheel filename) —
`make bump-framework VERSION=x.y.z` moves both (plus `uv.lock` and the vendored
schemas), CI asserts the lockstep, and the scheduled framework-bump workflow
opens the bump PR automatically; then `make publish-wheel`.

## [Unreleased]

### Fixed
- **`publish-wheel` now honors a per-target `datalab_version` override.** It
  resolved the version from `datalab.__version__` (whatever the repo-wide
  pyproject pin installed locally) and always built from the pyproject tag, so
  the soak-test procedure documented in `targets/stage.yml` — override
  `datalab_version`, then `make publish-wheel TARGET=stage APPLY=1` — could not
  publish the overridden release. `--target` now resolves the version through the
  domain registry (new `domains.framework_version()`), builds THAT release, and
  prints a note when it differs from the pyproject pin.
- **`check-lockstep` now asserts uv.lock's resolved PACKAGE VERSION equals
  `var.datalab_version`.** The wheel filename `var.datalab_wheel` points at is
  composed from the package version, not the tag; the two agreed only by way of a
  gate in the *framework* repo that runs after the tag already exists. A
  disagreement passed every gate here and failed only when a serverless
  environment tried to install a wheel that was not on the Volume.
- **`check-lockstep` surfaces per-target `datalab_version` overrides.** The gate
  whose purpose is "the framework version agrees everywhere" never read
  `targets/*.yml` — the one file where an environment can legitimately disagree.
  Overrides are now printed with the publish command needed to make them real.
- **The `adopter scaffold smoke test` job gained the "Missing framework App
  credentials" preflight** the other three framework-secret consumers already
  had. Without it, one missing secret produced two unrelated-looking failures on
  the same run, on a job whose name gives no hint it needs those credentials —
  which is exactly how the 2026-07/08 outage presented.

### Changed
- **Framework pin bumped `0.9.0` → `0.10.0`** and `gold.sales_by_category` no
  longer hardcodes its joined table. The transform used to build the dimension's
  name itself:

  ```python
  catalog = spark.conf.get("datalab.catalog")
  products = spark.read.table(f"{catalog}.{silver_schema}.products")
  ```

  so the artifact did not describe its own inputs, the dimension's layer was
  fixed in Python, a cross-catalog dimension was inexpressible, and — because the
  read bypassed `ResolveContext` — `run_dataset`'s `inputs=` substitution could
  not reach it, which is why this was the only gold dataset with no end-to-end
  test. The dimension is now DECLARED in
  `projects/sales/config/sales/gold/sales_by_category.yml`:

  ```yaml
  transform:
    - function: sales.sales_by_category
      tables:
        products_table: {name: products, layer: silver}
  ```

  and arrives as a resolved, per-environment table name
  (`@transform def sales_by_category(df, products_table: str)`). Framework
  v0.10.0 supplies `transform[].tables`; see its CHANGELOG.
- **New end-to-end test** `test_run_dataset_sales_by_category_joins_the_declared_dimension`
  — the coverage hole the hardcoding created, now closable because the declared
  ref is substitutable via `inputs=`.
- `AGENTS.md` + the `author-ldp-artifact` skill now state the rule: a transform
  never names a catalog/schema and never reads `spark.conf` — extra tables come
  from `tables:`, extra scalars from `args:` (where `${conf:<key>}` resolves).
  Caveat recorded too: a `tables:` ref is a batch read OUTSIDE the SDP graph and
  adds no dependency edge; `source.kind: sql` remains the in-graph join.

### Changed
- **Framework pin bumped `0.6.0` → `0.9.0`** (`make bump-framework VERSION=0.9.0`
  — `pyproject.toml` git tag + `variables/medallion.yml` `datalab_version` +
  `uv.lock` + re-vendored `schemas/`). Picks up five framework releases: custom
  sub-layer identifiers (0.7.0), the `is_non_negative` / `is_positive` /
  `is_valid_email` / `is_valid_uuid` built-in checks (0.8.0), the batch
  quarantine-MV `TABLE_OR_VIEW_NOT_FOUND` fix (0.8.1), pyspark 4.2 capability
  probing (0.8.2), and dqx `0.15.0` → `0.16.0` plus `target.replace_where`,
  `foreach_batch_sink` and the opt-in `quality.metrics.summary` MV (0.9.0).
  Publish the new wheel with `make publish-wheel APPLY=1` per target.

### Fixed
- **dqx 0.16.0 list-membership literals** in
  `projects/sales/config/sales/silver/orders.yml` (`order_status`, `channel`,
  `currency`): dqx now resolves a BARE string in `allowed:` as a COLUMN
  reference / SQL expression rather than a literal, so the three lists are
  requoted as `["'completed'", …]`. Without this the domain fails
  `make validate-configs` on 0.9.0.

### Added
- **Adopter-hardening pass** (schemas, lockstep, registry, bot, CI, showcase):
  - `make sync-schemas` / `make check-schemas` (`scripts/sync_schemas.py`): the
    vendored `schemas/*.json` are now GENERATED from the PINNED framework's
    Pydantic models instead of hand-copied — the hand copies had gone stale
    pre-0.6.0 and were missing the two 0.5.0 template schemas entirely. All 4
    schemas re-vendored at v0.6.0; drift now fails CI and the pre-commit guard.
  - `make check-lockstep` (`scripts/check_lockstep.py`) asserts the framework
    pin agrees across `pyproject.toml`, `variables/medallion.yml` and `uv.lock`;
    `make bump-framework VERSION=x.y.z` (`scripts/bump_framework.py`) performs
    the whole upgrade in one command (edits + lock + schema regen + assert).
  - **Framework-bump bot** (`.github/workflows/framework-bump.yml`): daily
    check of `datalab-framework` for a new `vX.Y.Z` tag; opens a pre-validated
    full-lockstep PR. `.github/dependabot.yml` keeps the GitHub Actions pins +
    regular Python deps fresh (the framework pin is excluded there — the bot
    owns that lockstep).
  - **Domain registry** (`scripts/domains.py`): the ONE place listing this
    repo's domains; `bootstrap_uc.py` + `publish_wheel.py` now RESOLVE
    per-target catalogs/groups from `variables/` + `targets/` + `rbac.yml`
    instead of hardcoded `CATALOGS`/`GROUPS` dicts (`make check-domains` gates
    CI). `publish_wheel.py --catalog-for <domain>=<catalog>` mirrors a deploy's
    `--var catalog` override so the wheel always lands in the catalog the
    pipelines will read (deploy-dab now passes it; previously an overridden
    deploy published to the wrong catalog).
  - `make check-sync-lists` (`scripts/check_sync_lists.py`): databricks.yml
    `sync.exclude` and `.databricksignore` (two hand-mirrored lists) now fail
    CI on divergence.
  - **Adopter-scaffold smoke test in CI**: `make new-adopter` into a temp dir,
    then the GENERATED repo's own `validate-configs`/`lint`/`test`/`check-*`
    gates — the headline scaffold transformation was previously unverified.
  - **sales domain is now the framework feature showcase**: `customers_history`
    (AUTO CDC **SCD2** with explicit `__START_AT`/`__END_AT` schema + the
    `operational_metadata: false` opt-out), `product_catalog`
    (**`cdc_from_snapshot`** pattern A over `bronze.products`, quarantine as MV),
    domain-wide **`operational_metadata:`** stamps (`_loaded_at`,
    `_record_source`), and a **config template** (`templates/revenue_rollup.yml`
    + `gold/revenue_rollups.yml`) expanding two `sql`-source gold MVs
    (`revenue_by_state`, `revenue_by_country`) — all pinned by new
    graph/run_dataset contract tests. Fan-in `sources:` and `backfill:`
    intentionally remain example-less (they need second physical sources this
    demo workspace lacks; see `projects/README.md`).
  - Failure alerting scaffold: `var.alert_emails` (complex, default `[]`) wired
    into the refresh job's `email_notifications.on_failure`; per-target
    `datalab_version` override documented in `targets/stage.yml` for
    soak-testing a new framework release before prod.
  - Edge-lane contract tests (`test_export_job.py`): the export job's
    fail-fast-on-missing-volume guard and cli_params error surface.

### Changed
- **CI/CD consolidated to ONE workflow** (`.github/workflows/ci-cd.yml`): the
  three near-identical `ci-cd-{dev,stage,prod}.yml` wrappers are replaced by a
  params job that derives the target from the trigger (PR→CI vs dev; main
  push→deploy dev with auto-approve; `v*-rc*`→stage; `v*`→prod; manual dispatch
  with a target choice). `databricks/setup-cli` is now pinned (`v1.6.0`, was
  `@main` — the one floating action on the deploy path). CI's `bundle validate`
  job gained the same graceful skip as CD for unprovisioned GitHub
  Environments. New CI drift gates: check-schemas, check-lockstep,
  check-domains, check-sync-lists.
- `publish_wheel.py` is now STRICT about the wheel it uploads: a stale
  framework wheel from an earlier bump in `dist-framework/` is an error (and
  `--build` clears old wheels first) — previously a fuzzy glob could silently
  publish the wrong version.
- `make run` takes `PIPELINE=<resource>` (default `customer_sales_etl`), so the
  `sales_etl` pipeline is now runnable via make.
- The adopter scaffold additionally repoints `docs/CICD.md`'s OIDC identity
  (federation subject, deploy SP, host — previously a generated repo's docs
  pointed at the TEMPLATE's service principal), converts the CD plumbing to the
  single-domain shape (drops the `sales_*` forwards; `landing_path` override),
  patches `scripts/domains.py`, strips the template-only CI jobs, keeps
  `sync.exclude`/`.databricksignore` aligned (incl. `.mcp.json`, which the
  generated bundle previously deployed), and REJECTS a non-`vX.Y.Z` framework
  pin (a branch pin would break the wheel-filename contract).
- `silver.customers` (sales) email rule uses the dqx 0.15 built-in
  `is_valid_email` instead of a hand-rolled `regex_match`.
- `schemas/`, `scripts/domains.py` and the other repo-integrity scripts joined
  the protected-file surface (all three guards updated).
- **In-place, interactive adopter configurator** (`make configure-adopter`). The
  GitHub-template flow now converts a clone in place by driving the deterministic
  engine (`scripts/scaffold_adopter.py --in-place`) instead of hand-editing —
  PROMPTING for and confirming every workspace-specific value (base catalog, host,
  SQL warehouse id, MCP CLI profile, RBAC groups, deploy SP, framework tag). The
  `bootstrap-adopter-repo` skill now drives this engine rather than describing
  manual surgery (`references/templates.md` is the fallback).

### Changed
- **Adopter generation now repoints the MCP grounding config and guards the
  catalog name.** Both `make configure-adopter` (in place) and `make new-adopter`
  (sibling) rewire `.mcp.json` + `.cursor/mcp.json` to the customer's SQL warehouse
  id + CLI profile (previously left pointing at the template's `diggi_dev_aws` /
  warehouse), and **reject** a `<catalog>` carrying an env suffix
  (`_dev`/`_stage`/`_prod`) — the fix for adopter repos that landed as
  `config/<catalog>_databricks_prod` instead of `config/<catalog>/`. New flags:
  `--in-place`, `--interactive`, `--warehouse-id`, `--mcp-profile`,
  `--allow-env-suffix`, `--yes`.
- **Completed the framework split.** The reusable framework now lives in its own
  repo, [`dediggibyte/datalab-framework`](https://github.com/dediggibyte/datalab-framework),
  consumed here as a **git dependency** (local/CI, pinned in `pyproject.toml`
  `[tool.uv.sources]`) + a **UC-Volume wheel** for serverless. This repo BUILDS
  that wheel **from the pinned git dep** (`pip wheel "datalab @ git+…@<tag>"`) and
  publishes it on every deploy — superseding 0.3.0's initial root `uv build`.
  `src/datalab` and the framework `tests/` no longer live here.
- Restored the CD publish path (`scripts/publish_wheel.py` + `make publish-wheel`,
  now building from the git dep) and fixed `make validate-connect` (its overlay
  installs the framework git dep + the editable domain, not the package-less root).
- **Framework wheel now lives in each project's own catalog.** Replaced the shared
  `datalab_artifacts` catalog with an `artifacts.wheels` UC Volume inside EACH
  project catalog (`customer_sales.artifacts.wheels`, `sales.artifacts.wheels`);
  `make publish-wheel` uploads into each, and each domain's pipelines install from
  their own catalog (`var.datalab_wheel` / new `var.sales_datalab_wheel`). Removed
  the `var.datalab_artifacts_catalog` variable and the shared catalog.

### Added
- **`docs/ADOPTING.md`** — how to stand up your own repo on the framework: the two
  consumption paths, the version pin + lockstep, the wheel publish, UC bootstrap,
  and copying a reference domain.

### Docs
- Reframed README / AGENTS / docs / projects as the **adopter-shaped reference
  repo**; repointed the framework reference to the framework repo's
  `docs/FRAMEWORK.md`.

## [0.3.0] — 2026-06-18

### Changed
- **The framework now ships as its OWN wheel.** `uv build` at the repo root
  builds a FRAMEWORK-ONLY `datalab` wheel (contains only `datalab/**`). The two
  reference domains became separate uv-workspace members
  (`projects/<catalog>/pyproject.toml`), each building its own `<catalog>_etl`
  wheel. Previously a single wheel contained all three packages.
- **The framework wheel is distributed via a single shared UC Volume.**
  Pipeline/job serverless environments install the common `datalab` wheel from a
  shared `datalab_artifacts` catalog's `framework.wheels` Unity Catalog Volume
  (`/Volumes/<datalab_artifacts_catalog>/framework/wheels/datalab-<ver>-py3-none-any.whl`)
  instead of the bundle-local `../../../dist/*.whl` — one upload for ALL domains,
  not a per-domain Volume. The bundle now builds only the example domain wheels.
  See the framework repo's [docs/FRAMEWORK.md](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md) "Distribution".

### Added
- `make publish-wheel` + `scripts/publish_wheel.py` — build and upload the
  versioned framework wheel ONCE to the shared `datalab_artifacts`
  `framework.wheels` Volume (dry run by default; `APPLY=1` uploads). CI publishes
  before every deploy.
- `scripts/bootstrap_uc.py` provisions the shared `datalab_artifacts` catalog
  (`framework.wheels` Volume + READ grants), per target.
- Bundle variables `datalab_artifacts_catalog`, `datalab_version`, `datalab_wheel`.

### Notes
- **Public API is unchanged from 0.2.0** — `datalab.config`, `datalab.params`,
  `datalab.framework`, the registries, and the config `schema_version` (still
  `1`) are identical. This release is a distribution/packaging change only.
- The config `schema_version` migration machinery (v1 → v2) does not exist yet;
  it remains the forward-compatibility path for a future breaking config change.

## [0.2.0]
- Baseline: the medallion framework shipped as a single combined wheel
  (`datalab` + the example domains) referenced by a bundle-local relative path.
  Pre-changelog — see git history.

[Unreleased]: https://github.com/dediggibyte/datalab/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dediggibyte/datalab/releases/tag/v0.3.0
[0.2.0]: https://github.com/dediggibyte/datalab/releases/tag/v0.2.0
