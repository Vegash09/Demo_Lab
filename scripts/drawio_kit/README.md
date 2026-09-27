# drawio_kit - vendored drawio-architecture-designer kit

Vendored from the `drawio-architecture-designer` skill (the method is in
`.agents/skills/drawio-architecture-designer/SKILL.md`) so every coding agent
and CI build the design diagrams the same way. `scripts/design_diagram.py` and
`scripts/design_spec.py` build on it; the diagrams in `design/` are its output.

| File | Role |
|---|---|
| `drawio_kit.py` | The layout model (`Page`, cards, panels, tables, edges) and its two emitters: `.drawio` and the HTML twin. Repo change from upstream: `ASSETS` points at `./assets`. |
| `arrows.py` | Shape-to-shape routing (`Lanes`, `flow`, `down`) and `audit_arrows`. Taken from the skill's embedded listing. |
| `render.py` | The layout audit (`OVERFLOW`, `COLOR`, `SLACK`, `COLLIDE`) and the playwright screenshot of the twin. |
| `extract_drawio.py` | Inventory, palette and logo harvest of an existing `.drawio`. |
| `fetch_logos.py` | Official brand marks from the `simple-icons` npm package. |
| `assets/` | `logos.json` mark pack, the official `unity_catalog.jpg` (the only permitted Unity Catalog mark), `example_page.py`. |

Keep it close to upstream; ruff skips this folder (`extend-exclude`). Improve a
check here only together with the skill, and never loosen one to get a layout
through - fix the layout.
