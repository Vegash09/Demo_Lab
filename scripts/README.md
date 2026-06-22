# scripts/

Developer + CI entry points for this **adopter bundle** — each is wired to a
`make` target (`make help`) and is operational tooling, **not** domain code and
**not** imported by the pipelines at runtime. They live beside the `Makefile`;
the Makefile and CI reference these exact paths, so don't move them without
updating both. (The reusable framework lives in its own repo,
[dediggibyte/datalab-framework](https://github.com/dediggibyte/datalab-framework);
this repo consumes it as a git dependency + a versioned UC-Volume wheel.)

| Script | `make` target | Why it exists |
|---|---|---|
| `bootstrap_uc.py` | `make bootstrap-uc TARGET=<t>` | One-time Unity Catalog setup per target — catalog, schemas, volumes, GRANTs. **Deliberately out-of-band of the bundle** so `databricks bundle destroy` never touches governance state. Installs `databricks-sdk` into a throwaway `uv run --with` overlay (never `uv.lock`). Keep its `CATALOGS`/`GROUPS` dicts in sync with the group names in `rbac.yml`. |
| `publish_wheel.py` | `make publish-wheel TARGET=<t>` (`APPLY=1`) | Build the common **framework** wheel from the pinned git dep (`pyproject.toml` `[tool.uv.sources].datalab`) and upload it to this target's shared `datalab_artifacts` `framework.wheels` UC Volume — one upload serves every domain. CI runs it in the `deploy-dab` action **before** `bundle deploy` (the version every environment references via `var.datalab_wheel` must exist on the Volume first). Out-of-lock `uv run --with databricks-sdk --with pip` overlay (neither enters `uv.lock`). |
| `validate_connect.py` | `make validate-connect LAYER=… TABLE=…` | Run ONE dataset's `run_dataset` path (mapping → transforms → dqx → valid/quarantine) on a LIVE cluster via Databricks Connect, **no deploy**. Installed into an **isolated, out-of-lock overlay** (`uv run --no-project` with the framework git dep + the editable domain + `databricks-connect`) because `databricks-connect` conflicts with the dev `pyspark`. See the framework repo's `docs/FRAMEWORK.md` "Run anywhere". |
| `export_design.py` | `make design` | Re-export the `design/*.drawio` diagrams to `design/images/*.png` (needs draw.io Desktop). See `docs/ARCHITECTURE.md` "Editing the design diagrams". |

Two recurring patterns above are intentional:
- **Out-of-band of the bundle** (`bootstrap_uc.py`): governance state (catalogs,
  schemas, volumes, grants) must survive `bundle destroy`, so it is created by a
  script, not a bundle resource.
- **Out-of-lock overlay** (`validate_connect.py`): `databricks-connect` and
  `databricks-sdk` are installed ephemerally so they never enter the dev
  `.venv` / `uv.lock` (which is `pyspark`-based).
