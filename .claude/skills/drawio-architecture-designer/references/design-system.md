# Design system, components and layout grammar

Everything here is a default that produces a composed-looking diagram. Override
it when a house style says otherwise — `extract_drawio.py --palette` on the
reference file tells you what to override it *to*.

## Palette

All names are importable from `drawio_kit`.

| Token | Hex | Use |
|---|---|---|
| `BLACK` / `TEXT` | `#000000` | **Every text colour** — see the rule below |
| `INK` | `#000000` | Headings, card titles, emphasis (alias of `BLACK`) |
| `MUTED` | `#000000` | Body copy, card detail lines (alias of `BLACK`) |
| `FAINT` | `#000000` | Kickers, captions, schema names (alias of `BLACK`) |
| `HEAD_FILL` | `#1C2B33` | Table-header **fill** (white text on it) |
| `LINE` | `#C9D2DC` | Standard card border |
| `CARD_LINE` | `#E0E3E6` | Inner-card border — lighter, for cards nested inside a zone |
| `PANEL` / `PANEL_LINE` | `#F7F8F9` / `#C2C8CD` | Grouping panel fill and border |
| `WHITE` | `#FFFFFF` | Card fill |
| `DARK` | `#0E1A20` | Platform title bar |
| `TEAL` | `#4E7A88` | Capability chip fill (white text) |
| `RED` | `#FF3621` | The short rule above a page title. One accent, used once |
| `FLOW` | `#FF8A00` | Data-flow arrows |
| `EDGE` | `#5A6B7B` | Control / secondary arrows |
| `BRONZE` `SILVER` `GOLD` | `#E8912A` `#9AA0A6` `#F2A900` | Medallion layer strips |

**Text colour rule.** All text — titles, labels, kickers, captions, body,
table cells, notes, annotations, legends and connector labels — is pure black
`#000000`, inline `<font color>` / `style="color:..."` included. The only
exception is white `#FFFFFF` text on a dark fill (table header, chip, `DARK`
title bar, medallion/step header strips). Hierarchy comes from size and weight,
not grey. The colours in this palette are for fills, strokes and arrows only.
`render.py` reports any other text colour as `COLOR`.

Zone tints, always used as a fill/border pair:

| Pair | Hex | Conventional meaning |
|---|---|---|
| `SKY` / `SKY_LINE` | `#E8F1F8` / `#B7CFE0` | Storage, object stores, volumes |
| `LILAC` / `LILAC_LINE` | `#EFEDF6` / `#B9B3D4` | Governance, access control, catalog |
| `BLUSH` / `BLUSH_LINE` | `#FDEDEB` / `#F0B9B1` | Exceptions, data quality, open items, risk |
| `MINT` / `MINT_LINE` | `#EAF6F4` / `#BFE3DD` | AI / ML |
| `SAND` / `SAND_LINE` | `#FDF6E9` / `#EBD6A8` | Neutral highlight |

Pick one tint per concern and hold it across every page. A reader who learns
"lilac means governance" on page 1 should not have to relearn it on page 4.

## Type scale

`FONT = "Helvetica"` throughout (installed wherever draw.io runs; a font the
viewer lacks silently substitutes and wrecks your line counts). `MONO =
"Courier New"` for paths, IDs and aligned key/value blocks.

| Size | Role |
|---|---|
| 30 | Page title |
| 13.5 | Page subtitle |
| 13 | Panel title, zone heading, card title |
| 12.5 | Metadata bar, `note` / `accentcard` titles |
| 11.5 | Chips, strip text, card body on hero pages |
| 11 | Card body on dense pages, table cells |
| 10.5 | Kickers, captions, table headers, faint schema labels |

Below 10.5 stops being readable when the diagram is projected. If content only
fits at 9px, the answer is less content, not smaller type.

## Components

### `p.head(x, y, w, title, subtitle)`
Page title block: a short red rule 14px above the title, then title, then a
one-line subtitle. Call it once per page at `(40, 54, …)`.

### `p.rect(x, y, w, h, …)`
The workhorse. Everything else is built on it. Key arguments: `fill`, `stroke`
(use `"none"` for no border), `radius`, `text` (HTML), `size`, `color`, `align`
(`left|center|right`), `valign` (`top|middle|bottom`), padding `pl/pr/pt/pb`,
`dashed`, `font`.

### `p.text(x, y, w, h, text, …)`
Borderless label. Unlike `rect`, draw.io does not clip it — overflow spills
visibly onto whatever is below, so still size it honestly.

### `p.panel(x, y, w, h, title, kicker=None)`
Light grouping container with a bold title and an optional small letter-spaced
kicker. Returns its id so you can point an arrow at the group rather than at
one card inside it. Contents start at `y + 48` when there is a kicker, `y + 36`
without.

### `p.logocard(x, y, w, h, logo, title, lines, lw, lh)`
White card, logo on the left, bold title, muted detail lines. The default card
for a system, product or service. Height 66 fits a title plus two detail lines.
The logo is emitted as a **separate image element**, not a `shape=label` image,
so draw.io and the HTML preview place it identically — see
`references/drawio-styles.md`.

### `p.accentcard(x, y, w, h, accent, title, lines, logo=None)`
White card with a coloured spine down the left edge. Use when cards belong to
categories that must be distinguishable at a glance — connections vs gateways
vs pipelines vs jobs in a matrix layout. Pick one accent colour per category
and repeat it down the column.

### `p.note(x, y, w, h, title, lines, logo=None, fill=…, stroke=…)`
Titled reference card: bold heading, then muted body lines. This is where
legends, cadences, exclusions, conventions, baselines and open items live. Tint
it (`fill=BLUSH, stroke=BLUSH_LINE`) to mark it as an exception or an action
item.

### `p.chip(x, y, w, h, label)`
Solid teal pill with white text. Capabilities, features, controls — things that
exist without needing explanation. A row of chips reads far better than a
comma-separated sentence.

### `p.kicker(x, y, w, label)`
Small uppercase letter-spaced label above a region. Cheap structure: it names a
column or a zone without spending a card on it.

### `p.table(x, y, colw, rowh, header, rows, colors=None, aligns=None)`
Real grid: dark header row, zebra body, per-cell colouring. Returns total
height. Use it for anything genuinely tabular — a persona access matrix, an
alert schedule, a schema inventory. A colour map turns a matrix into something
readable at a glance — the colour goes in the cell fill; the text stays black:

```python
YES = ("#E6F4EA", BLACK); OND = ("#FEF3E2", BLACK)   # (cell fill, text)
NO  = ("#F2F4F5", BLACK)                             # text stays black
p.table(40, 870, [340, 192, 192], 28, ["persona", "Silver", "Gold"],
        rows, colors={"Yes": YES, "On demand": OND, "No access": NO})
```

Tables beat monospace blocks whenever the content has columns. Monospace blocks
are for paths and IDs.

### `p.img(x, y, w, h, logo)`
Bare image. Use for logos in headers, zone marks, and the small mark in the
corner of a layer card.

Unity Catalog is always `p.img(x, y, w, h, L["unity_catalog"])` — the official
`assets/unity_catalog.jpg`, never a redrawn or fetched mark. Keep `w/h` at
`UNITY_CATALOG_RATIO` (~2.08, e.g. 56x27 in a zone header, 83x40 on a card,
125x60 as a hero mark); it has a white background, so it reads best on white
or a light tint.

### `p.edge(src, dst, color, sw, dashed, label, ex, ey, nx, ny, points)`
Orthogonal arrow between two element ids. `ex/ey` is the exit point as a
fraction of the source box, `nx/ny` the entry point on the target. `points` is
an explicit list of waypoints — supply them for anything that is not a straight
shot, because a route you specify is a route both renderers agree on.

## Sourcing marks

`assets/logos.json` covers the Databricks/lakehouse world. Beyond it:

1. Harvest from a reference `.drawio` — `extract_drawio.py --logos` — which is
   best, because it gives you exactly the marks the house diagrams already use.
2. `fetch_logos.py <names>` for anything on npm's `simple-icons`.
3. `svg_mark()` for concepts with no product behind them — a scheduler, an
   alert, a CI/CD step, an internal service. Stroke-based, 24px grid, one
   consistent weight so drawn icons and real logos sit together calmly.

Never approximate a brand by hand and never substitute an emoji. An internal
service gets a neutral glyph, not the logo of the language it is written in.

## Layout grammar

- **Page margin** 40px on every side.
- **Columns** 20–30px apart. Panels 16px of inner padding; cards 12–14px apart
  vertically.
- **Shared rows.** When two columns of cards sit side by side, put them on the
  same `y` values (`ROW = [244, 322, 400]`). Arrows between them then run
  straight, and straight arrows are the difference between a diagram and a
  plate of spaghetti.
- **Arrow gutters.** ≥26px between two boxes you connect directly. For a long
  crossing arrow, reserve an empty horizontal band and route through it with
  explicit waypoints.
- **Card heights.** 66 for a logo card, 100–120 for a spec card with four
  lines, 130–180 for a note. Size to content; let columns end unevenly.
- **Page size** falls out of the content; `render.py` prints it. A hero page
  around 2200×1000 prints and projects well.

## Page patterns that work

**Hero / end-to-end.** Left-to-right: sources → capture → a dark-barred
platform container holding zones (orchestration, medallion, storage,
governance) → consumption. Notes below the narrow left columns, a legend strip
across the bottom.

**Matrix / pipeline detail.** Columns are lifecycle stages (connection →
gateway → pipeline → job), rows are instances. Group rows into tinted panels by
family. `accentcard` with one colour per stage. Sidebar column for compute,
ownership and operating notes.

**Layer detail.** One column per layer, each with a coloured header strip, a
main card, then supporting notes underneath. Inventory tables where the content
is tabular.

**Consumption / governance.** Three columns of what-is-served, then a full-width
access matrix and a deployment card across the bottom.

## Metadata bar

Under the title, a full-width white strip carrying the identifiers that let a
reader trust the diagram — environment, catalog, workspace, region, "as-built"
date. It costs 36px and answers the first question every reviewer asks.
