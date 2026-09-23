---
name: maintain-design-diagram
description: Keep the design/ package in sync with the implemented datalab architecture — the draw.io diagrams (design/*.drawio), their exported images (design/images/*.png via `make design`), and the customer-facing design/OVERVIEW.md. Invoke whenever a code change adds/removes/renames a config artifact (a target table), changes how the framework is consumed/published (it is an external dependency), a domain @transform/@check_function/@snapshot_source, a medallion table (bronze/silver/gold/quarantine), an edge-lane job or notebook, an execution profile, a CI/CD workflow, or a bundle resource the diagrams reference; also when AGENTS.md's "Architecture" or "Codebase layout" changes. After editing a diagram, ALWAYS re-export images with `make design`, and refresh OVERVIEW.md when the customer narrative changes. Skip only for pure refactors that move no boxes/arrows and change no narrative.
---

# Maintain the design package

`design/` is the single living picture of what datalab actually builds. When the
architecture moves and the design is left stale, future contributors (human or
agent) trust a wrong map and make wrong decisions — so the design travels with
the code, in the same PR.

The package has four parts, with one source of truth:

| Part | File(s) | Role |
|---|---|---|
| **Living implementation map** | `design/02_implementation_end_to_end.drawio` | The single-page banded picture of the running system. **Edit this on most code changes.** |
| **Conceptual design spec** | `design/01_design_config_driven_medallion.drawio` | Multi-page Context → Author → Generate → Run → Ship. Edit only when the *design intent* changes. |
| **Exported images** | `design/images/*.png` | Generated from the `.drawio` sources by `make design`. Never hand-edit; re-export. The README, `docs/` and `OVERVIEW.md` embed these. |
| **Customer overview** | `design/OVERVIEW.md` | Customer-facing narrative that embeds the images. Refresh when a change alters the story (a new capability, layer behaviour, or value point). |
| **Pipeline inventory** | `design/PIPELINES.md` | GENERATED from the `config/` artifacts by `make design` (`scripts/design_inventory.py`): every table, its source, target kind and quality gate, plus a mermaid lineage graph. Never hand-edit; CI's `make check-design` fails while it is stale. |

<!-- adopter-if:template start -->
> `design/datalab-customer-overview.html` is a **published standalone snapshot**
> built out-of-band (not by this skill or by `make design`). If your change
> materially alters `OVERVIEW.md`, flag in the PR that the HTML snapshot needs
> regenerating — do not hand-edit it.
<!-- adopter-if:template end -->

The `.drawio` XML is the source of truth. The PNGs are derived; `make design`
regenerates them (it uses the draw.io Desktop CLI and is dev/agent-only — the
CLI is not in CI).

## When to invoke

YES — any of these in the same PR/work session:

- A new (or renamed) config artifact `config/<catalog>/<schema>/<table>.yml`
  — a new target table in the medallion.
- A change to how this repo consumes/publishes the framework (the pinned version,
  the wheel publish flow) — the framework itself is an external dependency.
- A new domain `@transform` / `@check_function` / `@snapshot_source`, or a new
  domain package surface (`src/<catalog>_etl/...`).
- A new medallion table or a changed target kind (streaming_table, +cdc,
  +cdc_from_snapshot, materialized_view, sink) or a new quarantine/metrics MV.
- A new edge-lane job (`spark_python_task`) or notebook (`notebook_task`) under
  `resources/*.yml`.
- A change to `datalab.profile` routing or a new execution profile.
- A new CI/CD workflow under `.github/workflows/` or a deploy step in
  `.github/actions/`.
- A new Databricks resource the bundle manages (pipeline, job), a new UC
  schema/volume, or a bootstrap grant the diagram references.

In each case: edit the diagram, **re-export images (`make design`)**, and
refresh `OVERVIEW.md` if the change alters the customer narrative.

NO — skip if:

- The change is a pure internal refactor (rename a private helper) and the
  boxes/arrows are still accurate.
- The change is documentation-only (README/AGENTS.md prose) with no structural
  move.
- The change is a dependency bump in `pyproject.toml`/`uv.lock` without code
  changes.

## Workflow

### 1. Identify the delta

Read the current diagram structure (it's plain XML — `grep` works):

```
grep '<mxCell id=' design/02_implementation_end_to_end.drawio | head -80
```

Compare to the change you just made. Decide:

- **New box** — a config artifact, framework module, domain surface, medallion
  table, edge job/notebook, or platform resource that has no existing node.
- **Edit box** — text on an existing box is now wrong (column list, target
  kind, profile caveats, scope list).
- **New edge** — a flow from one node to another that wasn't there.
- **Edit edge** — label wrong (flow renamed) or color wrong (lane changed).
- **Remove** — node or edge that no longer exists in code.

### 2. Find the right band

The left region (`x` 40–1300) is the data path top-to-bottom; the right region
(`x` 1340–2180) is the delivery column. **Don't straddle the gap** (1300–1340).

| Band id | y-range | Contents |
|---|---|---|
| (actors) | 100–160 | data engineer / analyst / steward / developer |
| `config_band` | 210–415 | `config/.../<table>.yml` artifacts + `domain.yml` |
| `framework_band` | 440–640 | models/loader, generator, dq/readers/writers, config/params |
| `domain_band` | 665–850 | `pipeline.py`, `transforms/`, `checks/`, jobs/notebooks |
| `pipeline_band` | 875–1130 | landing → bronze → silver (AUTO CDC) → gold; quarantine; dq_metrics |
| `edge_band` | 1155–1320 | refresh / export jobs + quarantine-report notebook |
| `cicd_band` (right col) | 210–1320 at x=1340 | profiles · GitHub Actions · Bundle · Bootstrap · Docs |

New boxes go into the band they conceptually belong to, on that band's row.

### 3. Edit the XML

Each cell needs a stable `id` (kebab/snake-case, ascii). Vertex pattern:

```xml
<mxCell id="<new_id>" parent="1" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#<fill>;strokeColor=#<stroke>;align=left;verticalAlign=top;fontSize=10;fontStyle=1;arcSize=3;" value="Title&#xa;subtitle line" vertex="1">
  <mxGeometry x="<x>" y="<y>" width="<w>" height="<h>" as="geometry" />
</mxCell>
```

Band color cheatsheet (match the band you're adding to):

- Config:     `fillColor=#ffe6cc strokeColor=#d79b00`  (domain.yml: `#fff8dc`)
- Framework:  `fillColor=#d5e8d4 strokeColor=#82b366`
- Domain:     `fillColor=#e1d5e7 strokeColor=#9673a6`
- Pipeline/UC:`fillColor=#cce5ff strokeColor=#36b`  (bronze `#fde9d9`, silver `#dcdcf0`, gold `#fff2cc`, quarantine `#f8cecc`/`#c0392b`)
- Edge lane:  `fillColor=#d1ecf1 strokeColor=#117a8b`
- Bundle:     `fillColor=#cce5ff strokeColor=#0056b3`
- Bootstrap:  `fillColor=#fef0d9 strokeColor=#fc8d59`
- Docs:       `fillColor=#fce4ec strokeColor=#d81b60`

Edge pattern (newline-encode with `&#xa;` inside labels):

```xml
<mxCell id="e_<src>_<dst>" edge="1" parent="1" source="<src_id>" target="<dst_id>" style="endArrow=classic;html=1;strokeColor=<color>;fontSize=9;fontColor=<color>" value="<label>">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

Edge color = the flow tier of the call (keep the legend in sync):

- Authoring (engineer → YAML): `#1976d2`
- Generate (framework → SDP):  `#7b1fa2`
- Medallion data flow / CDC:   `#388e3c`
- dqx quarantine (error rows): `#c0392b`
- Edge lane (read-only):       `#2e7d8a`
- Deploy / Bootstrap:          `#fc8d59`

Escape XML: `<` → `&lt;`, `>` → `&gt;`, `&` → `&amp;`, literal newline → `&#xa;`.
Don't put raw double-quotes inside a `value="..."` — use single quotes in any
inline HTML style.

### 4. Validate the XML and geometry

Always parse the XML and check geometry before re-exporting:

```bash
python3 - <<'PY'
import xml.etree.ElementTree as ET
f="design/02_implementation_end_to_end.drawio"
m=ET.parse(f).getroot().find('.//mxGraphModel')
pw=float(m.get('pageWidth')); ph=float(m.get('pageHeight'))
V={}; E=[]
for c in m.findall('.//mxCell'):
    if c.get('vertex')=='1':
        g=c.find('mxGeometry'); V[c.get('id')]=tuple(float(g.get(k,0)) for k in ('x','y','width','height'))
    if c.get('edge')=='1': E.append((c.get('source'),c.get('target')))
print("shapes",len(V),"edges",len(E))
print("dangling",[ (s,t) for s,t in E if s not in V or t not in V] or "none")
print("oob",[k for k,(x,y,w,h) in V.items() if x<0 or y<0 or x+w>pw or y+h>ph] or "none")
PY
```

- Left region boxes:  `x + width ≤ 1300`; right region: `1340 ≤ x` and
  `x + width ≤ 2180`.
- No two boxes in the same band overlap; every new edge's `source`/`target`
  points to an existing id.
- Band wrappers legitimately *contain* their children — compare siblings, not a
  child against its band.

### 5. Re-export the images

```
make design
```

This re-renders `design/PIPELINES.md` from the `config/` artifacts and
regenerates every `design/images/*.png` from the `.drawio` sources (it splits
the multi-page `01_*` file page by page, working around draw.io's unreliable
`--page-index`). Open the changed PNG to confirm it rendered, and **commit the
regenerated images and inventory alongside the `.drawio` edit** — a diagram edit
without its re-export leaves the embedded images stale. If `make design` reports
the CLI is missing, install draw.io Desktop or set `DRAWIO=/path/to/draw.io` (the
inventory is re-rendered either way; only the PNG export is skipped).

### 6. Refresh the customer overview

If the change alters the *story* the customer reads — a new medallion capability,
a changed layer behaviour, a new execution profile, a new value point — update
the matching prose in `design/OVERVIEW.md` (it embeds `images/01_*` and
`images/02_*`, so the re-exported images flow through automatically). A purely
structural diagram tweak that doesn't change the narrative needs no
`OVERVIEW.md` edit.
<!-- adopter-if:template start -->
When `OVERVIEW.md` changes materially, note in the PR that
`design/datalab-customer-overview.html` (the standalone share) needs
regenerating out-of-band.
<!-- adopter-if:template end -->

### 7. Cross-check AGENTS.md and docs

Scan AGENTS.md's "Architecture" and "Codebase layout" sections (and the relevant
`docs/`). If the change also affects those — a new framework module in the tree,
a new lane/profile — update them in the same PR. The diagram, images, OVERVIEW,
AGENTS.md and docs/ are the human-and-agent-facing descriptions of the system;
they must stay aligned. Framework behavior itself is documented in the
framework repo's `docs/FRAMEWORK.md` — change it there, not here.

### 8. Don't touch

- The TITLE / subtitle text — version it via diagram updates, not text edits.
- The legend — only change it if you introduce a new flow tier / edge color.
- The band wrapper rectangles (`config_band`, `framework_band`, etc.) — resize
  only if a row genuinely needs more vertical space.
- The exported PNGs or `design/PIPELINES.md` by hand — regenerate them (`make design`).
- The standalone HTML — it is regenerated out-of-band. <!-- adopter-if:template -->

## Common change → action recipes

**"Added a new table artifact"** → New box in `config_band`, plus the medallion
table box in `pipeline_band` and a green data-flow edge from its upstream. Edit
`cfg_*` text to match. `make design` (it also re-renders `design/PIPELINES.md`;
CI's `make check-design` fails without it). If it adds a customer-visible
capability, add a line to OVERVIEW.md's medallion section.

**"Added a new @transform / @check_function"** → Usually no new box — it lives
inside `dom_transforms` / `dom_checks`. Edit that box's text if the surface
changes; add a purple registry edge only if a new module appears. `make design`.

**"Changed how the framework is consumed/published"** → The framework is an
external dependency (one box in `framework_band`); edit that box or the
wheel/publish flow. `make design`. Update AGENTS.md "Codebase layout".

**"Added an edge-lane job / notebook"** → New box in `edge_band`; add a teal
read-only edge from the SDP table it consumes (never a write edge — single-
writer invariant). `make design`.

**"Added / changed an execution profile"** → Edit the `profiles` box (right
column) and the `fw_generate` text; adjust the dashed purple `e_profiles_gen`
edge label if routing changed. `make design`. Update OVERVIEW.md's "Run
anywhere" table.

**"New GitHub Action / workflow / bundle resource"** → Edit the `github` or
`bundle` box text; add a deploy (orange) edge if the deploy path changed.
`make design`.

## Anti-patterns

- Editing a `.drawio` source but forgetting `make design` — the README/docs
  embed stale images.
- Hand-editing a PNG or `design/PIPELINES.md` instead of regenerating.
- Hand-editing the standalone HTML instead of regenerating it. <!-- adopter-if:template -->
- Adding a box outside the bands (floating in whitespace).
- A write-edge from a job/notebook INTO an SDP-owned table — violates the
  single-writer invariant; edge lanes are read-only (teal).
- Drawing `import dlt` / hand-MERGE flows — this repo is `pyspark.pipelines` +
  AUTO CDC; the diagram must not imply otherwise.
- Stacking new boxes on existing ones because you didn't check geometry.
- Editing the legend without a corresponding edge-color change in the body.

## Done check

Before declaring the design updated, verify:

1. `xml.etree.ElementTree.parse` succeeds on every edited `.drawio` (no syntax
   errors).
2. Every new box has a unique `id`; every new edge's `source`/`target` exists.
3. No sibling boxes overlap by more than a few px; all boxes are in-bounds.
4. `make design` ran and the regenerated `design/images/*.png` and
   `design/PIPELINES.md` are staged with the `.drawio` edit (`make check-design`
   passes).
5. `design/OVERVIEW.md` still reads true (updated if the narrative changed).
   <!-- adopter-if:template start -->
   The standalone HTML is flagged in the PR if it needs regenerating.
   <!-- adopter-if:template end -->
6. The change is described in AGENTS.md in the same PR (framework behavior
   changes belong in the framework repo).
