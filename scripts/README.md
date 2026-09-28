# scripts/

Developer + CI entry points for this repo — each is wired to a `make` target
(`make help`) and is operational tooling, **not** domain code and **not**
imported by the pipelines at runtime. They live beside the `Makefile`; the
Makefile and CI reference these exact paths, so don't move them without
updating both. (The reusable framework lives in its own repo,
[dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework);
this repo consumes it as a git dependency + a versioned UC-Volume wheel.)

| Script | `make` target | Why it exists |
|---|---|---|
| `domains.py` | `make check-domains` | THE domain registry — the one place listing the domains this repo deploys. Per-target catalogs and persona groups are RESOLVED from `variables/` + `targets/` + `rbac.yml`, so `bootstrap_uc.py` and `publish_wheel.py` have nothing to keep in sync by hand. |
| `bootstrap_uc.py` | `make bootstrap-uc TARGET=<t>` | One-time Unity Catalog setup per target — catalog, schemas, volumes (incl. `artifacts.wheels`), GRANTs. **Deliberately out-of-band of the bundle** so `databricks bundle destroy` never touches governance state. Dry run by default; runs in a throwaway `uv run --with databricks-sdk` overlay (never `uv.lock`). |
| `publish_wheel.py` | `make publish-wheel TARGET=<t>` (`APPLY=1`) | Build the **framework** wheel from the pinned git dep (`pyproject.toml` `[tool.uv.sources].datalab`) for the target's resolved `datalab_version` and upload it into each domain catalog's `artifacts.wheels` UC Volume. CI runs it in the `deploy-dab` action **before** `bundle deploy` (the wheel `var.datalab_wheel` names must already be on the volume). |
| `check_lockstep.py` | `make check-lockstep` | Assert the framework pin agrees everywhere: the pyproject git tag, `var.datalab_version`, uv.lock's tag + package version, and the ref of every framework-doc link (CI gate). |
| `bump_framework.py` | `make bump-framework VERSION=x.y.z` | Rewrite the framework pin at every site in lockstep and re-pin the framework-doc links; the make target then re-locks and re-checks. |
| `check_framework_current.py` | `make check-framework-current` | Fail while a newer published datalab-framework release exists than the pin (its own CI job). `DATALAB_FRAMEWORK_MANDATE=enforce\|warn` — enforce in the template, warn by default in generated adopters. |
| `check_framework_surface.py` | `make check-framework-surface` | Fail while the `author-ldp-artifact` skill misses a target/source kind of the pinned framework's schema — the corresponding change a feature release needs (CI + pre-commit; same mode variable). | <!-- adopter-if:schemas&any-agent -->
| `check_sync_lists.py` | `make check-sync-lists` | Assert `databricks.yml` `sync.exclude` == `.databricksignore` (CI gate — `bundle deploy` reads only the first, `databricks sync` only the second). |
| `release_changelog.py` | `make check-changelog` / `make release-changelog` (`APPLY=1`) | THE changelog release: after every successful CI deploy of `main`, the `ci-cd.yml` `release` job runs `cut --apply` — `CHANGELOG.md` `[Unreleased]` becomes `## [X.Y.Z] — date` (SemVer bump from its headings), `pyproject.toml` + `uv.lock` move with it, and entries a stale PR merged into an already-released section move to the new release. `check` keeps the file releasable (CI + pre-commit); `verify` refuses a stage/prod deploy of anything but a cut release. |
| `sync_schemas.py` | `make sync-schemas` / `make check-schemas` | Regenerate / verify the vendored editor schemas in `schemas/` from the PINNED framework's Pydantic models — never hand-copied. | <!-- adopter-if:schemas -->
| `sync_skills.py` | `make sync-skills` / `make check-skills` | Regenerate / verify the `.claude/skills` copy of the canonical `.agents/skills` (Claude Code does not reliably follow symlinked skills). | <!-- adopter-if:agent-claude -->
| `publish_genie_skills.py` | `make publish-genie-skills` (`APPLY=1`) | Publish `.agents/skills` to Databricks Genie Code's Workspace `.assistant/skills/` via `databricks workspace import-dir`. | <!-- adopter-if:agent-genie -->
| `check_agent_settings.py` | `make check-agent-settings` | Fail if a TRACKED agent-harness config carries a machine-specific path, a hook pointing at a missing script, or a write grant that belongs in `.claude/settings.local.json`. | <!-- adopter-if:hooked-agent -->
| `validate_connect.py` | `make validate-connect LAYER=… TABLE=…` | Run ONE dataset's `run_dataset` path (mapping → transforms → dqx → valid/quarantine) on a LIVE cluster via Databricks Connect, **no deploy**, in an **isolated, out-of-lock overlay** (`databricks-connect` conflicts with the dev `pyspark`). | <!-- adopter-if:local-dev -->
| `design_inventory.py` | `make design` / `make check-design` | Render `design/PIPELINES.md` — every table, its source, target kind and quality gate, plus a lineage graph — from the `config/` artifacts; `--check` (CI) fails while it is stale. | <!-- adopter-if:design -->
| `design_diagram.py` | `make design` / `make check-design` / `make design-preview` | GENERATE `design/02_*.drawio` from the estate (config/, resources/, targets/, ci-cd.yml, `design/estate.yml`) and `design/01_*` from `design_spec.py`, through the vendored drawio-architecture-designer kit; `--check` (CI + pre-commit) fails on drift, a hand edit or any layout-audit finding; `--preview` writes the HTML twin + PNGs. | <!-- adopter-if:design -->
| `design_spec.py` | (imported by `design_diagram.py`) | The conceptual spec pages as text + computed layout - edit the text here, never the `.drawio`. | <!-- adopter-if:design -->
| `drawio_kit/` | (imported) | VENDORED drawio-architecture-designer kit: layout model -> `.drawio` + HTML twin, the layout audit (`render.py`), arrow routing (`arrows.py`), `extract_drawio.py`, `fetch_logos.py`, the logo pack and the official Unity Catalog mark. | <!-- adopter-if:design -->
| `export_design.py` | `make design` | Export the `design/*.drawio` diagrams to `design/images/*.png`, one per page (draw.io Desktop CLI; else the kit's HTML twin via playwright; else skipped with a note). | <!-- adopter-if:design -->
| `scaffold_adopter.py` | `make configure-adopter` / `make new-adopter` | The adopter configurator: turns this template into a customer's single-domain repo with the coding agents and components they chose (template repo only). | <!-- adopter-if:template -->
| `check_templates_doc.py` | `make check-templates-doc` | Assert the `bootstrap-adopter-repo` skill's `references/templates.md` mirrors the configurator's file templates byte for byte (template repo only). | <!-- adopter-if:template -->
| `check_adopter_docs.py` | `make check-adopter-docs ADOPTER=<dir>` | Check a GENERATED adopter for leftover template identity and dangling references to material it does not have (template repo only). | <!-- adopter-if:template -->
| `tests/` | `make test` | Unit tests for the gate scripts above (lockstep, link pinning, framework currency and surface, the changelog release cut) — template repo only. | <!-- adopter-if:template -->

Two recurring patterns above are intentional:

- **Out-of-band of the bundle** (`bootstrap_uc.py`): governance state (catalogs,
  schemas, volumes, grants) must survive `bundle destroy`, so it is created by a
  script, not a bundle resource.
- **Out-of-lock overlays** (`bootstrap_uc.py`, `publish_wheel.py`, and
  `validate_connect.py` where present): `databricks-sdk` and `databricks-connect`
  are installed ephemerally with `uv run --with …` so they never enter the dev
  `.venv` / `uv.lock` (which is `pyspark`-based).
