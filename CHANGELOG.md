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

**Releases are cut by the deploy.** Record every change as a bullet under
`## [Unreleased]` (Keep a Changelog headings; start a bullet `**BREAKING:**`
when it breaks adopters). After each successful deploy of `main` to dev, CI
moves those entries into `## [X.Y.Z] — YYYY-MM-DD` — the SemVer bump the
headings call for — sets `pyproject.toml` `[project].version` (and `uv.lock`)
to `X.Y.Z`, and pushes a `chore(release): vX.Y.Z` commit: the commit stage and
prod promote (tag `vX.Y.Z-rcN` / `vX.Y.Z`). Never cut a version or edit the
version by hand — see `docs/CICD.md` "Changelog releases".

**Two version knobs.** This repo's own version is `pyproject.toml`
`[project].version`, moved only by that release cut. The FRAMEWORK version it pins lives in two places that MUST
move in lockstep: the `datalab` git tag in `pyproject.toml` `[tool.uv.sources]`
and `variables/medallion.yml` `datalab_version` (the Volume wheel filename) —
`make bump-framework VERSION=x.y.z` moves both (plus `uv.lock` and the vendored
schemas), CI asserts the lockstep, and the scheduled framework-bump workflow
opens the bump PR automatically; then `make publish-wheel`.

## [Unreleased]

_Nothing yet._

## [0.5.0] — 2026-10-09

### Added
- **UC bootstrap provisions the MySQL ingestion schemas.** `scripts/domains.py`
  gained a per-domain `extra_schemas` field and `extra_schemas_by_catalog()`;
  `scripts/bootstrap_uc.py` now creates and grants `mysql_raw` and
  `mysql_gateway_meta` in the `customer_sales` catalog instead of assuming a
  human created them out of band.
- **A contract test that enforces the safety boundary.**
  `projects/customer_sales/tests/test_mysql_ingestion_contract.py` now asserts
  that no MySQL resource sits in the live `projects/*/resources/*.yml` glob, that
  source config and rendered examples agree, that no placeholder survives, that
  the schedule stays paused, and that bootstrap emits the raw/gateway schema DDL
  and grants.

### Changed
- **Lakeflow Connect MySQL ingestion no longer deploys placeholder resources.**
  Following PR review, the hand-authored gateway/ingestion/schedule resources and
  the downstream bronze reader moved out of the live bundle include path into
  `projects/customer_sales/resources/examples/` and
  `projects/customer_sales/config/customer_sales/bronze/examples/`. A merge to
  `main` (which auto-deploys dev) can no longer create unresolvable
  `REPLACE_ME_*` pipelines or break the live `customer_sales_etl` graph with a
  bronze table whose upstream does not exist yet.
- **The adopter side now supplies a framework-style ingestion SOURCE CONFIG**,
  not transcribed resource YAML:
  `projects/customer_sales/config/customer_sales/ingestion/mysql/customer_sales_mysql.yml`
  uses the `lakeflow_connect_ingestion_source` contract owned by
  `datalab-framework` (renderer: `python -m datalab.framework.ingestion render`,
  shipping in framework v2.0.0). `_template.yml` is now render instructions
  instead of a parallel hand-maintained spec.
- **No `REPLACE_ME_*` values anywhere in the ingestion surface.** Realistic but
  anonymized identifiers are used instead (`customer_sales_mysql_connection`,
  source schema `app_sales`, destination table `customers_cdc_raw`), so nothing
  in the repo looks deployable-but-broken and no real instance name leaks.
- **Scheduling defaults to `PAUSED`.** The example ingestion schedule job no
  longer ships `pause_status: UNPAUSED`, which would have started a 2-hourly
  ingestion run against a non-existent source on first deploy.
- **`run_as.service_principal_name` placeholders removed.** Ownership guidance
  moved to `docs/LAKEFLOW_CONNECT_MYSQL.md` as a promotion prerequisite; a fake
  SP application id is no longer committed as if it were configuration.
- **Bronze CDC read semantics fixed.** The bronze example streams its Lakeflow
  Connect source with `options: {skipChangeCommits: "true"}`, which an SCD1
  destination table requires — without it the stream fails on upstream
  updates/deletes.

## [0.4.0] — 2026-09-28

### Added
- **The design diagrams are generated from the estate, never hand-drawn.**
  `scripts/design_diagram.py` builds `design/02_implementation_end_to_end.drawio`
  from `config/`, `resources/*.yml`, `targets/`, `ci-cd.yml` and the new
  `design/estate.yml` overlay: an estate overview (domains, pipelines, jobs and
  an inventory table), one lineage page per domain (sources, layers, quarantine,
  orchestration, edge jobs, consumers) and a delivery page.
  `scripts/design_spec.py` rebuilds `design/01_*` from its text. Both go through
  the vendored **drawio-architecture-designer** kit (`scripts/drawio_kit/`,
  `.agents/skills/drawio-architecture-designer/`): cards sized from their text,
  arrows routed shape to shape through gutter lanes and corridors, and a layout
  audit (overflow incl. unbreakable tokens, colour, collisions, arrows through
  cards, overlapping runs) that fails `--write` and `--check`. The old
  hand-edited map had 22 arrows with no waypoints running through cards and a
  second domain bolted onto the bottom. Enforced by
  `.cursor/hooks/design_drawio_guard.py` (Claude Code, Codex, Cursor),
  `make check-design` (CI + pre-commit) and `make design-preview`; the images
  are now one PNG per page (`design/images/02_<n>_<page>.png`). Adopters with
  the `design` component get the same generator, kit, hook and gate.
- **`sales.gold.daily_sales_by_currency`** — a new gold materialized view over
  `silver.orders`: order count, recognized revenue and average order value per
  `order_date` and `currency`. Amounts are not FX-converted, so currency is a
  grouping key. An `is_unique` check on the grain gates it. The
  `sales.daily_sales_by_currency` transform shares its measures with
  `daily_sales` through the `_order_rollup` helper.
- **Adopting every datalab-framework release is MANDATORY in the template.**
  New `make check-framework-current` (its own CI job, every PR + main) fails
  while a newer PUBLISHED framework release exists than the pinned tag — merge
  the bump PR. One mode variable, `DATALAB_FRAMEWORK_MANDATE`, governs both new
  gates: `enforce` by default in the template, `warn` by default in generated
  adopter repos (set `enforce` to opt in); `warn` in the template is the
  incident break-glass.
  New `make check-framework-surface` (CI + pre-commit) fails while the
  `author-ldp-artifact` skill misses a target/source kind of the pinned
  framework's schema — the corresponding change a feature release needs (the
  skill had silently never learned `foreach_batch_sink`). Both scripts join the
  protected surface; the scaffold smoke test runs them in the generated repo.
- **Framework-doc links are pinned to the framework version.** Every link into
  the framework repo (`…/datalab-framework/blob/<ref>/…`) now names the pinned
  tag instead of `main` (which ran ahead of the pin and described features this
  repo couldn't use yet): `make bump-framework` re-pins them, `make
  check-lockstep` fails on drift, and the scaffold pins a generated adopter's
  links to ITS `--framework-tag`.
- **Adopter repos carry only what the customer chooses.** The configurator
  (`make configure-adopter` / `make new-adopter`, `scripts/scaffold_adopter.py`)
  now asks — in a short interactive form, or via flags / make variables — which
  **coding agents** the repo uses (`claude`, `codex`, `cursor`, `genie`, or
  none) and which **optional components** it carries (`docs`, `design`,
  `schemas`, `local-dev`, `githooks`, `pr-template`, `dependabot`,
  `framework-bot`, `mcp`), plus per-target workspace hosts and catalogs, the
  customer's display name / description and the GitHub repo (OIDC subject). A
  dropped choice takes its files, make targets, CI steps and doc passages with
  it: file ownership is declared once (`TOP_LEVEL` + `PATH_RULES` — an
  unclassified new top-level entry fails the scaffold), passages are fenced
  with `adopter-if:<feature>` markers in the shared files. The confirmed
  answers are recorded in the adopter's `.datalab-adopter.json`, and
  `ANSWERS=<file>` replays them byte for byte (flags override).
- **A design package generated for the customer** (`design` component):
  `design/OVERVIEW.md`, a starter implementation diagram following the
  `maintain-design-diagram` band conventions, the framework design spec, and
  **`design/PIPELINES.md`** — rendered from the `config/` artifacts by the new
  `scripts/design_inventory.py` (`make design`), so it tracks the pipelines as
  they grow; `make check-design` gates CI. This repo now carries its own
  `design/PIPELINES.md` for the reference domains too.
- Docs in an adopter are re-cast for the customer: NAMING's config-tree and
  environment tables, ARCHITECTURE's system / lanes / data-view diagrams and
  environment table use the adopter's own catalog, per-target catalogs and
  workspaces; the template-facing sections become "this repo was generated"
  notes. Without the `docs` component, every doc reference is relinked to this
  repo's copy.
- **`make check-agent-settings`** (CI + pre-commit) — fails if a COMMITTED
  agent-harness config (`.claude/settings.json`, `.cursor/hooks.json`,
  `.codex/hooks.json`) contains a machine-specific absolute path, or a hook
  pointing at a script that does not exist. Those files are shared with every
  developer and copied verbatim into every generated adopter repo.
- **`make check-templates-doc`** (CI + pre-commit) — diffs every code block in
  the `bootstrap-adopter-repo` skill's `references/templates.md` against
  `scripts/scaffold_adopter.py`'s file templates. That doc is the documented
  MANUAL FALLBACK for converting a repo by hand, and prose-enforced lockstep had
  drifted into shipping instructions that break a fresh conversion.
- **`make check-adopter-docs`** — runs inside a GENERATED adopter and fails if
  any surface it reads still names the template's workspace, deploy service
  principal, SQL warehouse or second-domain variables, or references the
  `projects/` + `design/` + `omnigent` material the conversion deletes.
  Attribution is checked per paragraph, not per line. No-ops in this repo.
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
- **`docs/ADOPTING.md`** — how to stand up your own repo on the framework: the two
  consumption paths, the version pin + lockstep, the wheel publish, UC bootstrap,
  and copying a reference domain.

### Changed
- **Framework pinned to datalab 1.0.0** (from 0.10.0): git tag +
  `var.datalab_version` + `uv.lock` + regenerated `schemas/` (managed tables,
  checkpoint import, AUTO CDC partial updates, dq fixes — the framework's first
  release under its strict feature=MAJOR / fix=MINOR policy; not breaking). The
  corresponding changes: the `author-ldp-artifact` skill documents every source
  and target kind (new `managed_table`, plus `foreach_batch_sink` / `view` /
  `sql` / `python` / `snapshot_function` it never covered), `replace_where`,
  `import_checkpoint_conf`, the CDC partial-update fields and `dq.variables_conf`
  substitution; the framework reference links are pinned to v1.0.0. Every gate
  passes unchanged (configs, 22 domain tests).
- **The framework-bump bot is reliable.** It checks twice a day in a cheap job
  (the heavy bump job starts only when due) and accepts a
  `datalab-framework-released` `repository_dispatch`. It runs EVERY CI gate on
  the bumped tree and always opens the PR — a DRAFT labeled
  `needs-corresponding-changes` listing the failing gates plus the framework
  CHANGELOG between the pins, BREAKING entries and new capabilities — instead of
  opening nothing (a failing `make bump-framework` is reported the same way).
  It compares against the newest PUBLISHED release, force-pushes its own branch
  only when it holds nothing but bot commits (a pushed-but-unopened branch used
  to wedge every later run), dispatches `ci-cd.yml` on it (GITHUB_TOKEN PRs
  trigger no CI), closes older bump PRs only after the new one exists and only
  when they carry no human commits, supports a manual dry run, files/updates a
  `framework-bump` tracking issue on any failure (e.g. PR creation refused) and
  closes those issues once the pin is current. docs/CICD.md "Framework bumps"
  documents the flow and its three external prerequisites.
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
- **Framework pin bumped `0.6.0` → `0.9.0`** (`make bump-framework VERSION=0.9.0`
  — `pyproject.toml` git tag + `variables/medallion.yml` `datalab_version` +
  `uv.lock` + re-vendored `schemas/`). Picks up five framework releases: custom
  sub-layer identifiers (0.7.0), the `is_non_negative` / `is_positive` /
  `is_valid_email` / `is_valid_uuid` built-in checks (0.8.0), the batch
  quarantine-MV `TABLE_OR_VIEW_NOT_FOUND` fix (0.8.1), pyspark 4.2 capability
  probing (0.8.2), and dqx `0.15.0` → `0.16.0` plus `target.replace_where`,
  `foreach_batch_sink` and the opt-in `quality.metrics.summary` MV (0.9.0).
  Publish the new wheel with `make publish-wheel APPLY=1` per target.
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

### Fixed
- **The deploy now cuts the changelog release.** Nothing ever released
  `[Unreleased]`: every dev deploy since 0.3.0 left its entries there and
  `[project].version` at 0.3.0, so the changelog said nothing about what each
  workspace runs. After every successful deploy of `main`, `ci-cd.yml`'s new
  `release` job runs `scripts/release_changelog.py cut`: `[Unreleased]` →
  `## [X.Y.Z] — date` (duplicate `###` groups merged, the SemVer bump read from
  the headings), `pyproject.toml` + `uv.lock` moved in lockstep, pushed to
  `main` as `chore(release): vX.Y.Z`. It releases only the commit it deployed,
  and repairs the entry a PR branched before a cut merges cleanly INTO the
  released section (reproduced in `scripts/tests/test_release_changelog.py`).
  Stage/prod deploys now refuse a tree with unreleased entries or a tag naming
  another version. New `make check-changelog` (CI + pre-commit) keeps the file
  releasable; `make release-changelog` previews the next cut (`APPLY=1` for
  recovery). The CD workflow exposes a `deployed` output the job keys on. The
  adopter scaffold's `CHANGELOG.md` uses the same `## [Unreleased]` format, so
  generated repos release on their first deploy too.
- **`make configure-adopter` can no longer wreck an adopter.** Re-run inside an
  already-generated repo it overwrote `pyproject.toml`, `databricks.yml`,
  `targets/`, `variables/`, README and CHANGELOG, added a second domain, and
  only then crashed on a missing template anchor. The engine now builds the
  whole adopter in a scratch dir and writes nothing unless every patch and the
  doc check pass, refuses any repo without `projects/`, and the scaffold
  tooling is template-only (never shipped to adopters).
- **Adopter details that were silently wrong:** `make help` advertised the
  template's `customer_sales_etl` as the default pipeline; AGENTS.md, the
  deploy skill and NAMING/ARCHITECTURE/AGENT_MCP/ADOPTING docs kept
  `customer_sales` examples, the stale `CATALOGS` dict and a `ci-cd-{dev,stage,prod}`
  workflow that no longer exists; `.databricksignore` shipped a garbled comment
  (line-based filtering cut a sentence in half) — it is now generated from the
  same list as `sync.exclude`; `.gitattributes` shipped design-only rules to
  repos without `design/`; `scripts/README.md` described removed dicts and
  listed 4 of 16 scripts; stage/prod always got the dev host (now asked per
  target); the sibling path could never set the OIDC subject (`--repo`).
- **`make check-adopter-docs` catches what it used to miss** — it now runs from
  the template against a generated repo and flags any reference to a path, doc
  or `make` target the repo does not have (not just `projects/`), plus
  `customer_sales` leftovers.
- **Tracked agent settings shipped a write grant.** `.claude/settings.json`
  carried `Bash(PROTECTED_EDIT_OK=1 git commit …)` (a commit that skips the
  protected-files guard) into every adopter. Removed; `check-agent-settings`
  now rejects any tracked grant that is not a read-only `make` target, and the
  adopter's allow-list is regenerated from its own Makefile.
- **The framework-bump bot runs only the gates an adopter has.** Its gate list
  is fenced per component (a dropped component's `make` target would fail the
  loop and turn every bump PR into a draft), and the PR body names `schemas/`
  and the authoring skill only when the repo carries them.
- **Framework bumps worked only sometimes.** Root causes found in the bot's run
  history: jobs refused by GitHub billing ("recent account payments have
  failed or your spending limit needs to be increased", 2026-08-31 and
  2026-09-21 — a whole day lost each time); the App private key missing
  (2026-08-16/17/18); the 06:17 cron routinely starting 5–6 h late; and the
  bump path itself never having run end to end — every real bump (0.5.0, 0.6.0,
  0.9.0, 0.10.0) was made by hand, and its `gh pr create` would have been
  refused because "Allow GitHub Actions to create and approve pull requests" is
  off on this repo. See the bot entry under Changed.
- **The adopter templates doc no longer hands out a broken conversion.** It
  shipped `environment_version: "4"` uncommented (Databricks' fingerprint gate
  then leaves a brand-new pipeline unable to run), told the reader to pre-create
  empty `silver/`/`gold/` layer dirs (the config validator rejects them),
  omitted `tests/test_smoke.py` (pytest exits 5 on an empty suite, failing the
  `make test` gate the same doc prescribes), and dropped the `pyspark<4.3` cap.
- **Generated adopters no longer inherit the template's workspace identity in
  their own docs.** `docs/AGENT_MCP.md` is now repointed at the adopter's host,
  CLI profile and SQL warehouse (previously it told a new customer to log into
  the template's workspace while claiming everything had already been
  rewritten); `docs/ARCHITECTURE.md`, `docs/NAMING.md` and `docs/ADOPTING.md`
  gained `template-only` regions the scaffold swaps for adopter text;
  `docs/MIGRATION.md` (this repo's own restructure history) is dropped.
- **`.github/CODEOWNERS` is reduced to a commented placeholder.** It shipped a
  team that exists in no other org, which makes the file invalid — so the
  "Require review from Code Owners" protection it describes silently enforced
  nothing.
- **`.cursor/rules/project.mdc` and the `author-ldp-artifact` /
  `deploy-databricks-bundle` skills are converted too.** The rule file is
  auto-attached to every Cursor edit and described the `projects/` layout as
  fact; the skills cited `sales_landing_path` / `DATALAB_SALES_LANDING_PATH`,
  which do not exist in an adopter.
- **`docs/GETTING_STARTED.md` stopped giving adopters four broken
  instructions**: keep `environment_version` (bricks a new pipeline), use
  `../../../dist/` (wrong depth at the repo root), declare bundle variables in
  `databricks.yml` (they live in `variables/`), and register a
  `[tool.uv.workspace]` member (breaks `make lock` in a single-package repo).
  Also `make install` → `make lock install` (a fresh adopter has no `uv.lock`)
  and `PROFILE=` restored on `bootstrap-uc`.
- **`rbac.yml` no longer recommends the command that breaks every UC grant.**
  It said to create groups with `databricks groups create`; that makes
  workspace-local groups Unity Catalog cannot see, so grants fail
  `PRINCIPAL_DOES_NOT_EXIST` — the trap four other documents call out as the
  number-one first-deploy failure. It also referenced a `GROUPS` dict that no
  longer exists.
- **First-deploy ordering is now identical in all three places** that give it
  (`docs/NEW_ADOPTER.md`, the generated `README.md`, the skill): commit + push
  before deploy, and the landing-data seed step between `make deploy` and
  `make run` — without it the documented "bronze materializes" check cannot pass.
- **A local-path git origin no longer produces a fake OIDC subject.**
  `repo_slug()` turned `git clone /some/dir` into `datalab/.` and wrote it into
  `docs/CICD.md` as the federation subject, the one string that must match
  exactly or every deploy fails `TOKEN_SUBJECT_INVALID`. Non-GitHub remotes now
  fall back to the `<owner>/<repo>` placeholder.
- **Stale mechanics corrected across the docs**: the framework wheel is built by
  a shallow `git clone` + `uv build --wheel`, not `pip wheel` (a uv-created venv
  has no pip); `make bootstrap-uc` takes `MANAGED_LOCATION=`, not
  `--managed-location`; `docs/ADOPTING.md`'s template-generation command named
  the wrong owner for cross-org adopters.
- **The scaffold smoke test covers what customers actually run.** It exercised
  only `make new-adopter`, while `docs/NEW_ADOPTER.md` step 2 tells every
  adopter to run `make configure-adopter` (convert in place) — a materially
  different path. Both modes now run, plus `check-skills`, `check-templates-doc`,
  `check-adopter-docs` and `make dry-run-local` on the generated repo.
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
- **dqx 0.16.0 list-membership literals** in
  `projects/sales/config/sales/silver/orders.yml` (`order_status`, `channel`,
  `currency`): dqx now resolves a BARE string in `allowed:` as a COLUMN
  reference / SQL expression rather than a literal, so the three lists are
  requoted as `["'completed'", …]`. Without this the domain fails
  `make validate-configs` on 0.9.0.

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
