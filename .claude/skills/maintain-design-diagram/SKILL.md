---
name: maintain-design-diagram
description: Keep design/02_implementation_end_to_end.drawio in sync with the implemented datalab architecture. Invoke whenever a code change adds/removes/renames a config artifact (a target table), a framework module under src/datalab/framework/, a domain @transform/@check_function/@snapshot_source, a medallion table (bronze/silver/gold/quarantine), an edge-lane job or notebook, an execution profile, a CI/CD workflow, or a bundle resource the diagram already references. Also invoke when AGENTS.md's "Architecture" or "Codebase layout" sections change. Skip for pure refactors that don't move boxes or arrows.
---

# Maintain the end-to-end design diagram

`design/02_implementation_end_to_end.drawio` is the single living picture of
what datalab actually builds. `design/01_design_config_driven_medallion.drawio`
is the multi-page conceptual spec (Context → Author → Generate → Run → Ship);
touch it only when the *design intent* changes, not on every code edit. If you
change the architecture, the implementation diagram must follow — otherwise
future contributors (human or agent) will trust a stale map and make wrong
decisions.

This skill walks you through detecting the change, deciding what shape it takes
in the diagram, and editing the drawio XML in place. Layout details matter —
apply them carefully so the diagram stays legible.

## When to invoke

YES — any of these in the same PR/work session:

- A new (or renamed) config artifact `config/<catalog>/<schema>/<table>.yml`
  — a new target table in the medallion.
- A new module under `src/datalab/framework/` that the generate path uses.
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

### 4. Validate

Always parse the XML and check geometry before saving:

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

Check that the new box's `x + width` doesn't exceed the region:

- Left region boxes:  `x + width ≤ 1300`
- Right region boxes: `1340 ≤ x` and `x + width ≤ 2180`

Check that no two boxes in the same band have overlapping rectangles, and that
every new edge's `source`/`target` points to an existing id.

### 5. Cross-check with AGENTS.md

After updating the diagram, scan AGENTS.md's "Architecture" and "Codebase
layout" sections (and the relevant `docs/`). If the change you made also
affects those — e.g. a new framework module that should appear in the tree, or
a new lane/profile — update them in the same PR. The diagram, AGENTS.md, and
docs/ are the human-and-agent-facing descriptions of the system; they must stay
aligned. Per the maintenance protocol, framework changes also update
`docs/FRAMEWORK.md`.

### 6. Don't touch

- The TITLE / subtitle text — version it via diagram updates, not text edits.
- The legend — only change it if you introduce a new flow tier / edge color.
- The band wrapper rectangles (`config_band`, `framework_band`, etc.) — resize
  only if a row genuinely needs more vertical space.

## Common change → diagram action recipes

**"Added a new table artifact"** → New box in `config_band` (the config row),
plus the corresponding medallion table box in `pipeline_band` and a green
data-flow edge from its upstream. Edit `cfg_*` text to match the columns/target.

**"Added a new @transform / @check_function"** → Usually no new box — it lives
inside `dom_transforms` / `dom_checks`. Edit that box's text if it changes the
surface; add a purple registry edge only if a new module appears.

**"Added a new framework module under src/datalab/framework/"** → Add or edit a
box in `framework_band`; wire purple generate edges from/to it. Update
AGENTS.md "Codebase layout" and `docs/FRAMEWORK.md`.

**"Added an edge-lane job / notebook"** → New box in `edge_band`; add a teal
read-only edge from the SDP table it consumes (never a write edge — single-
writer invariant).

**"Added / changed an execution profile"** → Edit the `profiles` box (right
column) and the `fw_generate` text; adjust the dashed purple
`e_profiles_gen` edge label if routing changed.

**"New GitHub Action / workflow / bundle resource"** → Edit the `github` or
`bundle` box text; add a deploy (orange) edge if it changes the deploy path.

## Anti-patterns

- Adding a box outside the bands (floating in whitespace) — it'll look
  disconnected from the architecture.
- A write-edge from a job/notebook INTO an SDP-owned table — violates the
  single-writer invariant; edge lanes are read-only (teal).
- Drawing `import dlt` / hand-MERGE flows — this repo is `pyspark.pipelines` +
  AUTO CDC; the diagram must not imply otherwise.
- Stacking new boxes on top of existing ones because you didn't check geometry.
  Always grep current x/y/w/h before placing.
- Editing the legend without a corresponding edge-color change in the body.

## Done check

Before declaring the diagram updated, verify:

1. `xml.etree.ElementTree.parse` succeeds (no syntax errors).
2. Every new box has a unique `id`.
3. Every new edge has both `source` and `target` pointing to existing ids.
4. No two boxes overlap by more than a few px; all boxes are in-bounds.
5. The change is described in AGENTS.md (and `docs/FRAMEWORK.md` for framework
   changes) in the same PR.
