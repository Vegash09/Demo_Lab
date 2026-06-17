# notebooks/

**Framework devtool notebooks only — this is NOT an EDA / exploration folder.**

| Path | What it is |
|---|---|
| `framework/verify_dataset.py` | Interactively verify one dataset *before* deploying: runs `datalab.framework.run_dataset` (loader → column mapping → transforms → dqx → valid/quarantine) against sample or real inputs, with no bundle deploy. The notebook counterpart of `make validate-connect` and the `run_dataset` contract test. |
| `framework/sample_data/` | Tiny sample input(s) the notebook reads locally. |

### Where other notebooks belong (so this folder stays scoped)

- **Domain / human-gated notebooks** — the *notebook lane* (quarantine triage,
  supervised repair, demos) — live under `examples/<catalog>/notebooks/<catalog>/`
  (adopter repos: `notebooks/<catalog>/`) and are wired as `notebook_task`
  resources. They are deployed; this framework devtool is not part of any domain.
- **Exploration / EDA** belongs in **workspace user folders, outside the bundle
  entirely** — never committed to the repo. See AGENTS.md "Authoring rules":
  *exploration with no managed target stays out of the bundle.*

This is a dev tool, not part of the deployed medallion; root `notebooks/` is
listed in `.databricksignore`.
