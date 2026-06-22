# Changelog

All notable changes to **this repo** — `datalab-examples`, the reference domains
+ deploy bundle that consumes the [datalab
framework](https://github.com/dediggibyte/datalab-framework) — are documented
here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Changes to the FRAMEWORK itself live in the framework repo's own CHANGELOG.

**Scope.** This changelog tracks the bundle + reference domains and how they
consume the framework — the pinned framework version, the deploy/publish flow,
and the example domains under `examples/`.

**Two version knobs.** This repo's own version is `pyproject.toml`
`[project].version`. The FRAMEWORK version it pins lives in two places that MUST
move in lockstep: the `datalab` git tag in `pyproject.toml` `[tool.uv.sources]`
and `variables/medallion.yml` `datalab_version` (the Volume wheel filename) —
bump both, then `make publish-wheel`.

## [Unreleased]

### Changed
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

### Added
- **`docs/ADOPTING.md`** — how to stand up your own repo on the framework: the two
  consumption paths, the version pin + lockstep, the wheel publish, UC bootstrap,
  and copying a reference domain.

### Docs
- Reframed README / AGENTS / docs / examples as the **adopter-shaped reference
  repo**; repointed the framework reference to the framework repo's
  `docs/FRAMEWORK.md`.

## [0.3.0] — 2026-06-18

### Changed
- **The framework now ships as its OWN wheel.** `uv build` at the repo root
  builds a FRAMEWORK-ONLY `datalab` wheel (contains only `datalab/**`). The two
  reference domains became separate uv-workspace members
  (`examples/<catalog>/pyproject.toml`), each building its own `<catalog>_etl`
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
