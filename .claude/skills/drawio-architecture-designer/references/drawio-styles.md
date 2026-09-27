# draw.io file format: the details that bite

Read this when you need a shape `drawio_kit` doesn't already provide, or when
something renders in the preview but not in draw.io. Every item here is a real
failure mode, most of them silent.

## File shape

```xml
<mxfile host="Claude" type="device" pages="2">
  <diagram id="p1" name="1 · Overview">
    <mxGraphModel dx="1400" dy="900" grid="0" gridSize="10" guides="1"
                  tooltips="1" connect="1" arrows="1" fold="1" page="0"
                  pageScale="1" pageWidth="2260" pageHeight="1030"
                  math="0" shadow="0">
      <root>
        <mxCell id="0" /><mxCell id="1" parent="0" />
        <mxCell id="c1" value="Label" style="…" vertex="1" parent="1">
          <mxGeometry x="40" y="40" width="200" height="60" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

`page="0"` is required: it opens the file with **Page View disabled** (an
infinite canvas with no page outline or page breaks), and `grid="0"` keeps the
grid hidden. Never emit `page="1"`. Still set `pageWidth`/`pageHeight` to the
content bounding box plus a margin, so that if the user turns Page View back on
(View > Page View) or prints, the page frame matches the drawing instead of
tiling it across A4s.

`id="0"` and `id="1"` are mandatory; every real cell has `parent="1"`.

## Images and data URIs

draw.io uses its **own** data-URI spelling, without the `;base64` marker:

```
image=data:image/png,iVBORw0KGgo…
image=data:image/svg+xml,PHN2ZyB4bWxucz0…      (still base64-encoded)
```

A browser will **not** display that form — it needs `data:image/png;base64,…`.
So the drawio emitter writes draw.io's spelling and the HTML emitter rewrites
it on the way out (`_uri()` in `drawio_kit.py`). If you add an image path
anywhere, respect that split or the preview silently shows a broken image and
you will "fix" a layout problem that does not exist.

Only `.png .jpg .jpeg .gif .webp .avif .svg` resolve. SVG styles also want
`editableCssRules=.*;` so the mark stays recolourable in draw.io.

Keep the pack small. Every mark is embedded in the file; downsample rasters to
~140px on the longest edge (`extract_drawio.py --logos` does this) or a
four-page diagram balloons past a megabyte.

## Why logos are separate elements, not `shape=label`

draw.io's `shape=label` can carry an `image=` plus `imageAlign` /
`imageVerticalAlign`, and it positions that image with its own internal rules.
The HTML preview cannot reproduce those rules exactly, so the two renderers
disagree — by a few pixels, which is enough to make a verified layout wrong.

`logocard` therefore emits a plain `rect` with left padding plus a separate
`shape=image` cell positioned explicitly. Both renderers place an absolutely
positioned box identically. Prefer that pattern for anything you add.

## Style strings

Semicolon-separated `key=value`. The ones that matter:

```
rounded=1;absoluteArcSize=1;arcSize=8;      corner radius in PIXELS
                                            (without absoluteArcSize it is a %)
whiteSpace=wrap;html=1;                     wrap text and interpret HTML
fillColor=#FFFFFF;strokeColor=none;strokeWidth=1;
fontColor=#000000;fontSize=13;fontFamily=Helvetica;fontStyle=1;   1 = bold
                                            (text is ALWAYS #000000; #FFFFFF
                                            only on a dark fill)
align=left;verticalAlign=top;
spacingLeft=16;spacingRight=14;spacingTop=12;spacingBottom=6;
dashed=1;dashPattern=6 5;
opacity=45;
```

A borderless text label is `text;html=1;strokeColor=none;fillColor=none;…`.
Note that a `text` cell does **not** clip its content — overflow spills onto
whatever sits below, so size it honestly even though nothing gets cut off.

Fractional font sizes (`11.5`) parse fine. Unknown style keys are ignored
rather than erroring, which is convenient and also means a typo fails silently.

## HTML inside labels

With `html=1`, labels accept a useful subset: `<b>`, `<i>`, `<br>`, `<font
color="…">`, and inline `style="font-size:11px;color:#1C2B33"`. That is how one
card holds a bold title over muted detail lines.

The escaping is two-layer and easy to get wrong. The label is *HTML inside an
XML attribute*, so the markup must be XML-escaped when written:

```python
value_html = '<b>Title</b><br>detail &amp; more'
attribute  = html.escape(value_html, quote=True)
# → &lt;b&gt;Title&lt;/b&gt;&lt;br&gt;detail &amp;amp; more
```

draw.io un-escapes the XML, gets the HTML back, and renders it. Write `&nbsp;`
for a non-breaking space and let the escaper handle it; write a literal `&` and
it survives too. Do not hand-escape.

## Edges

```
edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;
strokeColor=#FF8A00;strokeWidth=2;
exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;
```

`exitX/exitY` and `entryX/entryY` are fractions of the source and target boxes.
Always set them: without them draw.io picks a side, and the preview picks a
different one.

Waypoints go in the geometry, and supplying them is how you keep both renderers
honest about the route:

```xml
<mxCell id="e1" style="…" edge="1" parent="1" source="a" target="b">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="618" y="277" /><mxPoint x="618" y="469" />
    </Array>
  </mxGeometry>
</mxCell>
```

An edge label is a child cell parented to the edge:

```xml
<mxCell id="e1l" value="triggers" parent="e1" vertex="1" connectable="0"
        style="edgeLabel;html=1;align=center;verticalAlign=middle;
               resizable=0;points=[];labelBackgroundColor=#FFFFFF;">
  <mxGeometry x="-0.2" relative="1" as="geometry">
    <mxPoint x="0" y="-11" as="offset" />
  </mxGeometry>
</mxCell>
```

`x` on the geometry is the position along the edge from -1 to 1;
`labelBackgroundColor=#FFFFFF` punches a hole in the line so the text is
readable. A label needs a segment long enough to hold it — in a 24px gap it
will overlap both boxes, and the fix is to move the information into a kicker,
not to shrink the font.

## Line height

draw.io lays labels out at roughly 1.2 line-height; the HTML preview uses 1.32.
The preview is therefore slightly *taller* than reality, so a layout that fits
in the preview fits in draw.io. Keep that direction if you change either
renderer — erring the other way means shipping clipped text.

## Colours

Plain hex. draw.io also writes `light-dark(#aaa, #eee)` pairs for theme-aware
files; the preview does not understand them, so stick to plain hex and let dark
mode invert on its own.

`strokeColor=none` and `fillColor=none` are both valid and both useful.

## Things that do not work

- No CSS classes, no external stylesheets, no web fonts. Pick fonts that exist
  on the viewer's machine.
- No auto-layout worth relying on. Position everything absolutely.
- Containers (`container=1`) reparent children and shift their coordinates.
  This kit deliberately avoids them: everything is a sibling in absolute page
  coordinates, which keeps the two renderers in agreement and makes geometry
  easy to reason about.
