---
name: drawio-architecture-designer
description: "Build, rebuild or restyle draw.io diagrams - current-state, future-state, or CI/CD pipeline - clean, branded and logo-bearing, with every arrow routed shape to shape, verified through an HTML twin before delivery. MANDATORY in this repo for every change to design/*.drawio, scripts/design_diagram.py, scripts/design_spec.py or scripts/drawio_kit/ - the diagrams are generated through this kit and never hand-edited."
---

# draw.io architecture designer

> **In this repo (datalab).** This skill is vendored so every coding agent -
> Claude Code, Cursor, Codex, Genie Code - applies the same method. It is
> **mandatory** for any change to the `design/` diagrams, and it is used through
> the repo's generator rather than as a free-standing exercise:
>
> - `design/*.drawio` are **build outputs**. Never edit their XML (a hook blocks
>   it and `make check-design` fails CI on any drift). Change the source instead:
>   the estate itself (`config/`, `resources/*.yml`), the overlay
>   `design/estate.yml`, `scripts/design_diagram.py` (the generated estate
>   pages) or `scripts/design_spec.py` (the conceptual spec pages) - then run
>   `make design`.
> - The kit lives at `scripts/drawio_kit/` (`drawio_kit.py`, `arrows.py`,
>   `render.py`, `extract_drawio.py`, `fetch_logos.py`, `assets/`). Paths below
>   point there.
> - Step 1's questions are already answered here: the estate pages follow the
>   **future-state / target** pattern, the delivery page the **CI/CD** pattern;
>   deliverables are the committed `.drawio` plus `design/images/*.png`; density
>   is "every table, job and pipeline, one line of substance each". Do not ask.
> - Steps 5-6 are enforced: `python scripts/design_diagram.py --check` runs the
>   layout audit and `audit_arrows` on every page and fails on `OVERFLOW`,
>   `COLOR`, `COLLIDE` or an arrow crossing a card. `python
>   scripts/design_diagram.py --preview <dir>` writes the HTML twin and PNGs -
>   **read them** before you commit a layout change.
> - Step 8 (delivery) means: commit the regenerated `design/*.drawio`,
>   `design/images/*.png` and `design/PIPELINES.md` in the same PR. The
>   `maintain-design-diagram` skill has the repo workflow.

You are producing a diagram someone will put in front of a client or a
handover meeting. Two things separate a good one from a bad one: it is
*factually exact* (every count, ID and path traceable to a source), and it is
*visually resolved* (nothing clipped, nothing colliding, nothing floating in
dead space, and every arrow leaving one shape and landing on another). This
skill gives you a way to guarantee all of it.

## The central problem, and the trick that solves it

draw.io has no headless renderer available here. You cannot open the `.drawio`
you just wrote and see whether the text fits. Building a large diagram blind,
by hand-editing XML, reliably produces overlapping cards and clipped labels.

So don't. Describe the diagram **once** in Python as absolutely positioned
boxes, and let `scripts/drawio_kit/drawio_kit.py` emit two things from that one model:

- the real `.drawio` file, and
- an HTML page that renders the same boxes with the same fonts and padding.

Screenshot the HTML, read the PNG, fix what looks wrong, re-render. That loop
is the whole method. `scripts/drawio_kit/render.py` runs it end to end and adds a static
audit for the two failures that actually happen: text taller than its card, and
cards that collide. The arrow audit below adds the third: a line drawn across a
card it does not connect.

## Non-negotiable output rules

These hold on every page and every mode unless a rule below names the
exception explicitly.

1. **All text is pure black - `#000000`.** Titles, subtitles, panel titles,
   kickers, captions, card titles and body lines, table cells, notes,
   annotations, legends and connector (edge) labels all use `fontColor=#000000`,
   including any inline `<font color>` or `style="color:..."` inside a label.
   No grey, navy or brand-tinted text, even when a reference file uses it -
   carry the reference's fills and strokes, not its text colours. Hierarchy
   comes from size and weight. `INK`, `MUTED`, `FAINT` and `TEXT` in
   `drawio_kit` are all `#000000`; use them or `BLACK`, never a hex of your own.
   **The one defined exception:** text on a dark filled shape (table header,
   capability chip, dark platform title bar, coloured step/env header) is white
   `#FFFFFF` so it stays legible. `render.py` flags any other text colour as
   `COLOR`, and a `COLOR` finding must be fixed like `OVERFLOW`.
2. **Page View is off when the file opens.** Every `<mxGraphModel>` is written
   with `page="0"` (Page View disabled - no page outline or page breaks) and
   `grid="0"` (grid hidden). `pageWidth`/`pageHeight` stay in the file so
   printing still fits if the user turns Page View back on. `to_drawio` does
   this; if you ever hand-write or post-process XML, keep both at `"0"`.
3. **Unity Catalog always uses the official asset.** Whenever a Unity Catalog
   logo is needed, use `L["unity_catalog"]`, which the kit loads byte-for-byte
   from `scripts/drawio_kit/assets/unity_catalog.jpg` (the official logo supplied by the user; it
   overrides any `unity_catalog` key in any logo pack you merge). Never draw,
   trace, regenerate, recolour, crop-and-rebuild, fetch or approximate a Unity
   Catalog mark, and never swap in `svg_mark()` for it. The image is 1268x610
   (~2.08:1) with white margin and a white background, so size its box at that
   ratio (`UNITY_CATALOG_RATIO`, e.g. 56x27, 83x40, 125x60) and prefer placing
   it on a white or very light surface.

## Workflow

### 1. Ask which diagram this is, then ask that mode's questions

Do this **first**, before reading sources or laying anything out - the answer
changes the layout grammar, the questions worth asking, and what counts as a
fact. Two rounds of `AskUserQuestion`, or one round if the request already
names the kind ("redo our CI/CD pipeline" needs no mode question).

**Round A - which kind?**

| Kind | What it is | Layout it wants |
|---|---|---|
| **Current state** | What exists today, warts included | Systems-and-gaps: sources, the tools actually in use, blush-tinted pain points |
| **Future state / target** | What we are proposing to build | Hero left-to-right: sources -> ingest -> platform -> consumption |
| **CI/CD / deployment** | How code gets from a laptop to production | Numbered step chain through dark-barred environment boxes |

If they want more than one (a current-state and a future-state pair is common),
build them as separate pages in one `.drawio` so the set reads as one system.

**Round B - the mode's own questions.** Always ask **deliverables** (`.drawio`
alone, PNG exports for slides, or PDF) and **detail density** (keep every fact,
or trim exhaustive listings to headlines - a page listing 42 table names is a
reference sheet, a page saying "42 tables, these domains" is a diagram; only
they know which they need). Then, by mode:

- **Current state** - Which pain points go on the page (they are the reason the
  diagram exists, so name them rather than implying them)? Anything deliberately
  out of scope? Are volumes and refresh cadences known, or unknown-and-to-be-
  confirmed?
- **Future state** - Cloud and platform (AWS / Azure / GCP, Databricks /
  Snowflake / Fabric)? Which ingestion tools by name? Is governance (Unity
  Catalog, RBAC, masking) on the page or a separate one? Are the ML/AI and
  consumption use cases decided, or placeholders?
- **CI/CD** - Git host and branching model (trunk / GitFlow / feature-to-develop)?
  Which environments, and in order (Dev -> QA -> Staging -> Prod, or just two)?
  What packages and deploys (Databricks Asset Bundles, Terraform, dbt,
  GitHub Actions, Azure DevOps)? Which gates are **manual approvals** versus
  automated - approvals are the whole point of the picture, so get them right.
  Do they want the steps numbered end to end?

Skip the asking only if the session is clearly unattended - then pick the most
likely mode, say which you picked at the top of your reply, and carry on.

### 2. Inventory the source before drawing anything

If there is an existing diagram, dump its full contents:

```bash
python scripts/drawio_kit/extract_drawio.py --text source.drawio > inventory.txt
```

Read all of it. Never work from a screenshot or from the page-1 preview - the
entire value of a rebuild is that no fact is lost, and offscreen cells are
exactly the ones you'd drop. If the source is a document rather than a diagram,
read the document the same way.

Keep the inventory file. You will diff against it at the end.

### 3. Take the brand from the reference, not from your taste

When someone says "make it look like this other file", find out what "this"
actually is:

```bash
python scripts/drawio_kit/extract_drawio.py --palette reference.drawio
python scripts/drawio_kit/extract_drawio.py --logos reference.drawio \
       --out logos.json --sheet logo_sheet.png
```

The palette dump frequency-counts fills, strokes, fonts and sizes - the top few
entries *are* the design system (fills, strokes, fonts and sizes only: text
stays `#000000` whatever the reference's `fontColor` counts say). The logo harvest pulls out every embedded
base64 mark, deduplicates and downsamples them, and writes a contact sheet.
Read the sheet, rename the hash keys to readable names in `logos.json`, then
`load_logos("logos.json")` in your page module.

With no reference file, the defaults in `drawio_kit` are a neutral cloud-
platform system that already looks composed, and `scripts/drawio_kit/assets/logos.json` ships 15
real marks (Databricks, Delta Lake, MySQL, HubSpot, Google Sheets, AWS S3,
MLflow, Lakeflow, Lakebase, Genie, dashboards, models, model serving) plus
drawn icons for generic concepts. Unity Catalog is *not* in `logos.json`: it
comes from the official `scripts/drawio_kit/assets/unity_catalog.jpg` (see the output rules). Read
`references/design-system.md` for the palette, the card anatomy and the layout
grammar before you place the first box.

For a product outside that pack - Kafka, Snowflake, Looker, SAP, GitHub - the
usual logo CDNs are blocked here but the npm registry is not:

```bash
python scripts/drawio_kit/fetch_logos.py kafka snowflake github sap --out logos.json
```

That pulls official marks from `simple-icons` (CC0), tints each to its brand
colour, and reports what it could not find. A few marks have been withdrawn
from current releases after trademark requests (dbt, Salesforce, Power BI, the
Azure family, the AWS product family) - for those either try `--version` with
an older release, or draw a neutral stroke icon with `svg_mark()`. Never
approximate a brand freehand; a wrong logo is worse than an honest glyph.

Client and partner wordmarks that exist only inside a supplied PNG can be
cropped out of it, alpha-matted and embedded as a `data:image/png,` logo - a
6x LANCZOS upscale of a tight bounding box holds up fine at header size.

### 4. Write one Python module per page

Copy `scripts/drawio_kit/assets/example_page.py` as a starting point - it is a working page that
uses every component. Each module exposes `build()` returning a
`drawio_kit.Page`.

```python
from drawio_kit import *

def build():
    p = Page("1 - End-to-End Architecture")
    p.head(40, 54, 1400, "Title", "one-line subtitle")
    card = p.logocard(40, 244, 232, 66, L["mysql"], "MySQL - orders",
                      ["14 tables - CDC enabled"])
    ...
    return p
```

Hold the layout in named variables (`SRC_X, SRC_W = 40, 260`) rather than
scattering magic numbers, so a column can be moved in one edit. Work from a
grid you decide up front: 40px page margin, **40px between columns that arrows
will cross** (30px only where a single bus runs), 16px padding inside a panel,
12-14px between stacked cards, and **26px or more between two stacked cards an
arrow will join**.

Keep the id of every shape an arrow will touch. `logocard`, `rect`, `panel`
and friends all return the id; put them in dicts keyed by a short name
(`src["sap"]`, `ing["cds"]`, `med[0]`) so the arrow section at the end of the
module reads as a list of relationships.

The component vocabulary - `head`, `panel`, `logocard`, `accentcard`, `note`,
`chip`, `kicker`, `table`, `rect`, `text`, `img`, `edge` - is documented in
`references/design-system.md` with guidance on which to reach for. Then pick
the page pattern for your mode from **Page patterns** below.

### 5. Draw the arrows shape to shape

Arrows are the part reviewers point at first, and the part the draw.io router
gets wrong on its own. The contract, for every diagram this skill produces:

- **Every arrow connects one shape to one shape.** Never a panel to a panel,
  never a panel to a card, never a card into the empty middle of a container.
  A source system points at the ingestion path that reads it; each ingestion
  path points at the layer it lands in; Bronze points at Silver, Silver at
  Gold; Gold points at the objects that serve it; each serving object points at
  the people or tools that consume it. If you cannot name the relationship,
  there is no arrow.
- **Fixed ports.** Left-to-right flow leaves the source's right edge and enters
  the target's left edge (`ex=1, ey=0.5, nx=0, ny=0.5`). A stacked pair
  leaves the bottom centre and enters the top centre. draw.io keeps these
  because the kit writes `exitX/exitY/entryX/entryY`; the HTML twin draws the
  same points, so what you see is what the client opens.
- **Explicit waypoints, always.** Route the vertical run of every arrow into
  the **gutter** between its two columns, with one **lane** per distinct
  target so parallel arrows never sit on top of each other. Arrows into the
  same target share a lane and an entry point and merge into a single bus with
  one arrowhead; that is the correct look for many-to-one, not a fan of nine
  lines. Two lanes need a 30px gutter, three to five need 40px.
- **Skipping a column means a corridor.** When a flow must pass a column it
  does not touch (Gold to the consumption tools, past the AI column), do not
  draw across it. Reserve an empty horizontal band - below the panels, or
  between a container's header bar and its sub-panels - and route down the
  first gutter, along the corridor, and up the next gutter. Shorten the panels
  the corridor passes under so the band is empty.
- **No line crosses a card it does not connect.** Right-angle crossings
  between two arrows in a gutter are acceptable; a line through a card, a
  label or a chip is not. An arrow may cross the border of a container that
  holds its own target.
- **Stacked cards get an arrow only if they are 26px apart.** Otherwise
  reorder or respace the stack; never draw through the card in between.
- **Colour carries meaning.** `FLOW` orange for data flow, `INK` for control
  flow (CI/CD), dashed for optional or conditional paths. One arrow weight per
  page (2.5 for hero pages).

`scripts/drawio_kit/arrows.py` does the routing and the check:
`Lanes` allocates lane positions across a gutter or corridor, `flow` routes a
left-to-right arrow through them, `down` joins a stacked pair, and
`audit_arrows(p)` prints every arrow that passes through a shape it does not
connect. Call the audit as the last line of `build()` and do not deliver until
it prints `ARROW AUDIT clean`.

```python
from arrows import Lanes, flow, down, audit_arrows

G1 = Lanes(C1X + C1W, C2X, ["cds", "lfc", "auto", "zb"])   # gutter, one lane per target
for s, t in [("sap", "cds"), ("sf", "lfc"), ("ps", "auto"), ("ot", "zb")]:
    flow(p, src[s], ing[t], G1[t])                             # adjacent columns
for k in ("cds", "lfc", "auto", "zb"):
    flow(p, ing[k], de["pipes"], G2["pipes"])                  # many-to-one: one bus
down(p, med[0], med[1]); down(p, med[1], med[2])              # Bronze -> Silver -> Gold
flow(p, med[2], srv["sql"], GB["sql"], corridor=CORR, lane2=G4["sql"])  # skips a column
audit_arrows(p)
```

Then look at the PNG for the two things the audit cannot judge: an arrowhead
that lands on a border rather than floating short of it, and lanes that read
as separate lines rather than a smear (zoom the gutter to 2x before deciding).

### 6. Render, audit, and actually look

```bash
python scripts/drawio_kit/render.py --pages p1 p2 p3 --out ../out \
       --name my_architecture.drawio --scale 2
```

This writes the `.drawio`, the preview, and a PNG per page, and prints the
audit. `OVERFLOW` means text will clip in draw.io - fix it. `COLOR` means a
label is not pure black (or is white on a light fill) - fix it. `SLACK` and
`COLLIDE` are judgement calls. `ARROW ... crosses ...` is a fault.

Then **read the PNGs with the Read tool**. Downscale wide pages first
(PIL `resize` to 1500px wide) so a whole page fits in one look, and crop into
regions you are unsure about - always the gutters. The audit finds size
mistakes; only looking finds ugly - ragged column bottoms, an arrow bisecting a
label, a card that is three-quarters empty, a legend running off the edge, an
arrow entering a card from below because its target sat at a different height
from its source.

Expect two or three rounds. That is normal and cheap.

### 7. Fact-check before you deliver

Rebuilding drifts. Numbers get transposed, IDs mistyped, and - most often -
you fill a gap with something plausible that the source never said. Before
handing over, run a check against the inventory from step 2. A subagent is
ideal because it reads with fresh eyes; brief it to report only, in four
categories:

1. numbers that disagree
2. identifiers that disagree or are mistyped
3. claims in the rebuild that appear nowhere in the source
4. material facts dropped that a reader would miss (excluding listings the
   user asked you to trim)

Category 3 is the one that matters most. On a real run it caught "Unity Catalog
Volumes **on Amazon S3**" where the source only ever said "Unity Catalog
Volumes" - true in general, unstated here, and exactly the kind of thing that
gets challenged in a client review. On a CI/CD page it is usually an invented
gate ("automated rollback") that nobody actually has. Cut inferred claims or
soften them to what the source supports, and tell the user what you cut.

When a diagram is being **updated** rather than built, the same discipline
applies to the arrows: an arrow is a claim that A feeds B. Re-check every one
against the source or the SOW before re-rendering, and remove any that no
longer describe a real path (a replaced message bus, a source moved to a
later phase, a tool dropped from scope).

### 8. Deliver

Before sending, confirm the three output rules held: the audit shows no
`COLOR` findings, `grep -o 'page="[01]"' file.drawio` prints only `page="0"`,
and any Unity Catalog mark on the page is the bundled asset.

Send the `.drawio` and the PNGs with `SendUserFile`, then write them into the
user's connected folder with `device_commit_files` if one exists - a diagram
they cannot open in draw.io is not delivered. Put PNGs in a named subfolder so
the working file stays easy to find. When the diagram is a figure inside a SOW
or a deck, rebuild that document too; a fixed PNG that never reaches the
document fixes nothing.

Say one honest sentence about verification: these were rendered through the
HTML twin, not draw.io itself, so ask them to open the file once and report any
label that wraps oddly. That is a real limitation and hiding it costs trust.

## Page patterns

### Future state / target architecture

Left-to-right hero: sources -> capture -> a dark-barred platform container
holding zones (orchestration, medallion, storage, governance) -> ML/AI ->
consumption. Notes below the narrow left columns; full-width service strips
(cloud services, platform services) across the bottom, each led by a solid
`INK` label block. Number the columns in their kickers when the source does
("STEP 1", "STEP 2") so a reader can follow the flow without tracing arrows.

Arrows on this pattern, in order: each source to its ingestion path (lanes in
gutter 1); every ingestion path to the pipeline or landing layer (one bus in
gutter 2); Bronze to Silver to Gold (stacked with 26px gaps, or side by side
with straight arrows); Gold to the semantic and AI objects next door (lanes in
the gap between sub-panels); Gold or the semantic layer to the serving objects
through a corridor if a column sits between them; each serving object to the
tool or person that consumes it. Storage and governance strips at the foot of
the platform carry no arrows; they are what everything above sits on.

When many sources feed one target, do not draw a fan of long arrows. Route them
onto a **bus**: `flow` with the same lane for every one, so the vertical
segments coincide into a single line and the arrowheads stack at one point.

### Current state

Same left-to-right spine, but the honest one: what is actually in use, with
pain points as `BLUSH`-tinted notes placed against the stage they hurt, and
unknowns marked as unknown rather than guessed. A "not modelled / out of scope"
note in `PANEL` grey at the bottom of a column is worth more than an extra card.
A current-state page with no integration layer has few or no arrows, and that
is the point; do not invent flows to make it look connected.

### CI/CD / deployment pipeline

A numbered chain, left to right, that starts at a person and ends in
production. Anatomy, and the geometry that has been rendered and checked:

- **Left rail** (x 40-520, page ~2040x890). A `Developer` card, a `GitHub`
  card with a small `Feature Branch` caption and branch glyph floating above
  it, then the review chain stacked below the Git host - `Pull Request`,
  `Code Review Approval` - as short icon-left cards.
- **Environment boxes.** One `envbox` per environment: a `PANEL` container with
  a full-width `DARK` bar carrying a centred `DEV ENVIRONMENT - Databricks`
  title and the platform mark. Dev sits high and wide, Prod sits lower and
  starts further right, so the eye reads a descending staircase.
- **Step cards** inside each box: white, centred 32px icon, bold title, one or
  two 11px muted detail lines, and a `DARK` numbered badge half-overlapping the
  top-left corner. 196px tall, 28px apart.
- **The promotion gate** between environments is a solid green pill
  (`GREEN = "#137333"`) carrying its own step number - `10 - Promotion / merge
  to main`. Make it a **node in the chain** (edge in, edge out), never a label
  sitting on a line: edges render above rectangles, so a line routed under the
  pill draws straight through its text.
- **Arrows are control flow, not data flow** - use `INK`, not the orange `FLOW`.
- **Number every step once, in execution order**, and put the number on the
  card badge or in the edge label (`1 - Write code & commit`), never both.
  Follow the source's numbering even where it skips.

These three helpers are verified against the renderer - paste them into the
page module:

```python
GREEN = "#137333"

def badge(p, x, y, n):
    p.rect(x - 12, y - 14, 32, 32, fill=DARK, stroke="none", radius=8,
           text="<b>%s</b>" % n, size=12.5, color=WHITE)

def stepcard(p, x, y, w, h, n, icon, title, lines=()):
    cid = p.rect(x, y, w, h, fill=WHITE, stroke=LINE, radius=10)
    p.img(x + w / 2.0 - 16, y + 34, 32, 32, icon)
    p.text(x, y + 84, w, 22, "<b>%s</b>" % title, size=13, color=INK,
           align="center")
    for i, ln in enumerate(lines):
        p.text(x, y + 110 + i * 20, w, 18, ln, size=11, color=MUTED,
               align="center")
    badge(p, x, y, n)
    return cid

def envbox(p, x, y, w, h, title, logo=None):
    bid = p.rect(x, y, w, h, fill=PANEL, stroke=PANEL_LINE, radius=12)
    p.rect(x, y, w, 48, fill=DARK, stroke="none", radius=12,
           text="<b>%s</b>" % title, size=14, color=WHITE)
    if logo:                                   # sits left of the centred title
        p.img(x + w / 2.0 - len(title) * 4.1 - 38, y + 12, 24, 24, logo)
    return bid, y + 48
```

Cards are laid out inside a box by dividing its inner width:

```python
DX, DW = 580, 1420
cw = (DW - 32 - (n - 1) * 28) / float(n)
cards = [stepcard(p, DX + 16 + i * (cw + 28), 248, cw, 196, *step)
         for i, step in enumerate(steps)]
for a, b in zip(cards, cards[1:]):
    p.edge(a, b, color=INK, sw=2)
```

Stroke marks worth drawing for this mode (`svg_mark()`, 24px grid,
stroke-width 1.6, `#525252`): developer-at-a-monitor, pull request, review
check, CI checks, package, deploy-to-server, integration test, approval circle,
release cube, smoke test. Fetch the real `github` mark; the kit already ships
`git`, `shield`, `clock` and `bell`.

### Matrix / pipeline detail, layer detail, consumption

Columns are lifecycle stages, rows are instances; `accentcard` with one colour
per stage; sidebar column for compute, ownership and operating notes. Layer
pages get one column per layer with a coloured header strip. Consumption pages
get three columns of what-is-served plus a full-width access matrix.

## Judgement that keeps coming up

**Logos earn their place.** Unity Catalog is always `L["unity_catalog"]`, the
official bundled asset - never a redraw. Otherwise use a real product mark for a real product, a drawn
SVG icon (`svg_mark()`) for a generic concept like "scheduler" or "alert", and
never an emoji. If a needed mark is missing and you cannot harvest it, draw a
clean stroke icon in the same 24px style rather than approximating a brand.

**Density is a decision, not a default.** Dense monospace blocks belong on
reference pages. A hero page wants counts, names and one line of substance per
card. When you trim, trim listings - never schedules, alerts, open items,
approval gates, governance rules or ownership, because those are what people
came to check.

**Colour carries meaning or it carries nothing.** Give each concern one tint
and stay consistent across pages: storage sky, governance lilac, exceptions
blush, AI/ML mint, capability chips teal, medallion layers bronze/silver/gold,
promotion gates green. Then a legend is honest rather than decorative.

**Ragged column bottoms are fine; dead space inside a card is not.** Size each
card to its content and let columns end unevenly. A card sized for text it does
not contain reads as a mistake. When a container is much taller than the cards
inside it, split its content into inner mini-cards rather than stretching one.

**Arrows need room, and they need a target.** Leave at least 26px between two
boxes you want to connect so the arrowhead is visible, give every arrow that
must cross the diagram an explicit corridor, and never let a panel stand in
for the shape inside it. A single stub between two panels tells the reader
nothing about which system feeds which path; that is the arrow that gets
sent back. Edge labels need a segment long enough to hold them; if there isn't
one, put the information in a kicker or a pill instead.

## Gotchas that cost a render

- **`from drawio_kit import *` exports `HERE`.** If your page module defines
  `HERE = os.path.dirname(...)` above that import, the star-import silently
  overwrites it with the scripts directory and your `load_logos` path breaks.
  Name your own constant something else (`MYDIR`).
- **`render.py` changes the working directory**, so `os.path.abspath(__file__)`
  in a page module is unreliable. Use an absolute path to your page folder,
  and add that folder to `sys.path` before importing `arrows`.
- **Edge labels are escaped for you.** Write `label="1 - Write code & commit"`,
  not `&amp;` - pre-escaping renders the entity literally. Everywhere else
  (`rect`, `text`, card titles and body lines) the text *is* HTML, so `&amp;`
  is correct there.
- **Edges render above rectangles.** Anything you want a line to appear behind
  must be a node the line connects to, not a box you draw afterwards.
- **The kit's default router bends at the target's y, not in the gutter.** Two
  arrows from different heights into one card therefore share a vertical
  segment somewhere over the source column and cross whatever sits there. That
  is why waypoints are not optional; `flow` sets them for you.
- **Clear `__pycache__`** in your page folder if an edit seems not to take.

## Reference files

- `references/design-system.md` - palette, component anatomy, layout grammar,
  page patterns. Read before laying out.
- `scripts/drawio_kit/fetch_logos.py` - official brand marks from the npm `simple-icons`
  package, for products the bundled pack doesn't cover.
- `references/drawio-styles.md` - the draw.io style-string details that bite:
  data-URI format, `absoluteArcSize`, HTML in labels, XML escaping, edge
  waypoints, and why logos must be separate elements. Read when you need a
  shape the kit doesn't already give you.
- `scripts/drawio_kit/assets/example_page.py` - a working page using every component.
- `scripts/drawio_kit/assets/logos.json` - the bundled mark pack.
- `scripts/drawio_kit/assets/unity_catalog.jpg` - the official Unity Catalog logo. The only
  permitted Unity Catalog mark; loaded as `L["unity_catalog"]`.
- `scripts/drawio_kit/arrows.py` - the routing and audit helper (`Lanes`, `flow`, `down`, `audit_arrows`).
