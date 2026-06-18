# Changelog

All notable changes to the **datalab framework** (`src/datalab`, the package
published as the `datalab` wheel) are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Scope.** This changelog tracks the FRAMEWORK's public API and distribution —
the contracts adopters depend on (`datalab.config`, `datalab.params`,
`datalab.framework`, the `@transform` / `@check_function` / `@snapshot_source`
registries, the config models under `schemas/`, and the config `schema_version`).
The reference domains under `examples/` are not separately released.

**Version is set in three places that MUST move in lockstep:**
`pyproject.toml` `[project].version`, `src/datalab/__init__.py` `__version__`,
and `variables/medallion.yml` `datalab_version` (the Volume wheel filename). Bump
all three, then `make publish-wheel`.

## [Unreleased]

## [0.3.0] — 2026-06-18

### Changed
- **The framework now ships as its OWN wheel.** `uv build` at the repo root
  builds a FRAMEWORK-ONLY `datalab` wheel (contains only `datalab/**`). The two
  reference domains became separate uv-workspace members
  (`examples/<catalog>/pyproject.toml`), each building its own `<catalog>_etl`
  wheel. Previously a single wheel contained all three packages.
- **The framework wheel is distributed via a UC Volume.** Pipeline/job serverless
  environments install `datalab` from a per-domain `artifacts.wheels` Unity
  Catalog Volume
  (`/Volumes/<catalog>/artifacts/wheels/datalab-<ver>-py3-none-any.whl`) instead
  of the bundle-local `../../../dist/*.whl`. The bundle now builds only the
  example domain wheels. See [docs/FRAMEWORK.md](docs/FRAMEWORK.md) "Distribution".

### Added
- `make publish-wheel` + `scripts/publish_wheel.py` — build and upload the
  versioned framework wheel to each domain's artifacts Volume (dry run by
  default; `APPLY=1` uploads). CI publishes before every deploy.
- `scripts/bootstrap_uc.py` provisions an `artifacts.wheels` Volume (+ READ
  grants) in every domain catalog.
- Bundle variables `datalab_version`, `datalab_wheel`, `sales_datalab_wheel`.

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
