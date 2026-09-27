"""drawio_kit — one layout model, two renderers.

The whole point of this module: you describe a diagram ONCE as absolutely
positioned boxes, and it emits both a real .drawio file (what the user edits)
and an HTML page that looks the same (what you screenshot to check your work).
draw.io cannot be rendered headlessly, so the HTML preview is your only eye on
the layout — which is why every primitive here is written to render identically
in both. Do not add a feature to one emitter without adding it to the other.

Usage
-----
    from drawio_kit import *

    def build():
        p = Page("1 - Overview")
        p.head(40, 54, 1400, "My Platform", "subtitle line")
        card = p.logocard(40, 200, 260, 66, L["mysql"], "MySQL", ["3 instances"])
        ...
        return p

Then render with scripts/render.py, which also runs a layout audit.
"""
import html as _html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")  # repo layout: scripts/drawio_kit/assets

# ---------------------------------------------------------------- palette --
# A calm, neutral system that reads as "cloud platform architecture" without
# belonging to any one vendor. Override any of these before building a page if
# the house style differs (see references/design-system.md for how to lift a
# palette out of an existing .drawio with extract_drawio.py --palette).
# TEXT COLOUR RULE: every piece of text the kit emits — titles, subtitles,
# labels, kickers, captions, body lines, table cells, annotations and
# connector (edge) labels — is PURE BLACK (#000000). INK / MUTED / FAINT are
# kept as names so existing page modules still import, but all three are
# black; hierarchy comes from size and weight, never from grey text. The only
# exception is text sitting on a dark fill (table header, chip, dark title
# bar), which is WHITE so it stays legible. Do not pass any other fontColor.
BLACK      = "#000000"
TEXT       = BLACK       # the one text colour
INK        = BLACK       # primary text        (was #1C2B33 — now black)
MUTED      = BLACK       # body / secondary     (was #5A6B7B — now black)
FAINT      = BLACK       # kickers, captions    (was #8A97A3 — now black)
HEAD_FILL  = "#1C2B33"   # table-header FILL (a fill, not a text colour)
LINE       = "#C9D2DC"   # card border
PANEL      = "#F7F8F9"   # grouping-panel fill
PANEL_LINE = "#C2C8CD"   # grouping-panel border
CARD_LINE  = "#E0E3E6"   # inner-card border (lighter than LINE)
WHITE      = "#FFFFFF"
DARK       = "#0E1A20"   # platform title bar
TEAL       = "#4E7A88"   # capability chip
TEAL_DK    = "#1C5E57"
RED        = "#FF3621"   # accent rule under a page title
FLOW       = "#FF8A00"   # data-flow arrow
EDGE       = "#5A6B7B"   # control / secondary arrow
BRONZE     = "#E8912A"   # medallion bronze
SILVER     = "#9AA0A6"   # medallion silver
GOLD       = "#F2A900"   # medallion gold
MINT       = "#EAF6F4"; MINT_LINE  = "#BFE3DD"   # AI / ML zone
SKY        = "#E8F1F8"; SKY_LINE   = "#B7CFE0"   # storage zone
LILAC      = "#EFEDF6"; LILAC_LINE = "#B9B3D4"   # governance zone
BLUSH      = "#FDEDEB"; BLUSH_LINE = "#F0B9B1"   # exception / data-quality
SAND       = "#FDF6E9"; SAND_LINE  = "#EBD6A8"   # neutral highlight

FONT = "Helvetica"       # installed everywhere draw.io runs; safe default
MONO = "Courier New"

# ------------------------------------------------------------------ logos --
# Real product marks, base64-embedded so the .drawio is self-contained and
# needs no network. Keys are readable names; see assets/logos.json.
# Harvest more from any reference .drawio with:
#     python scripts/extract_drawio.py --logos ref.drawio --out extra.json
# then merge them with load_logos("extra.json").
def load_logos(path):
    """Merge a logo pack (name -> drawio data URI) into L. Returns L."""
    with open(path) as fh:
        L.update(json.load(fh))
    return L


L = {}
_default_pack = os.path.join(ASSETS, "logos.json")
if os.path.exists(_default_pack):
    load_logos(_default_pack)


# ---- official Unity Catalog logo -------------------------------------------
# assets/unity_catalog.jpg is the OFFICIAL Unity Catalog logo supplied by the
# user. It is embedded byte-for-byte (no re-encode, no crop, no recolour) and
# ALWAYS wins over anything in logos.json or any pack merged later via
# load_logos(). Never draw, trace, regenerate or approximate a Unity Catalog
# mark — use L["unity_catalog"]. The file is 1268x610 (ratio ~2.08:1) with
# white margin around the mark, so size the image box at that ratio
# (e.g. 125x60, 104x50, 83x40) or it will be letterboxed.
UNITY_CATALOG_FILE = os.path.join(ASSETS, "unity_catalog.jpg")
UNITY_CATALOG_RATIO = 1268 / 610.0


def _official_unity_catalog():
    import base64
    with open(UNITY_CATALOG_FILE, "rb") as fh:
        return "data:image/jpeg," + base64.b64encode(fh.read()).decode()


if os.path.exists(UNITY_CATALOG_FILE):
    L["unity_catalog"] = _official_unity_catalog()
    _orig_load_logos = load_logos

    def load_logos(path):  # noqa: F811 — keep the official UC mark on top
        _orig_load_logos(path)
        L["unity_catalog"] = _official_unity_catalog()
        return L


def svg_mark(body, w=24, h=24, vb="0 0 24 24"):
    """Build a data URI for an inline SVG icon.

    Use this when no real product mark exists for something (a generic
    "scheduler", "alert", "CI/CD" concept). Draw stroke-based icons on a 24px
    grid in one consistent style so they sit next to real logos without looking
    out of place. Never substitute an emoji.
    """
    import base64
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="%s" fill="none">%s</svg>' % (w, h, vb, body))
    return "data:image/svg+xml," + base64.b64encode(svg.encode()).decode()


_svg = svg_mark  # backwards-compatible alias

# hand-drawn marks for tools future_arch had no asset for
def _svg(body, w=24, h=24, vb="0 0 24 24"):
    s = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="%s" fill="none">%s</svg>' % (w, h, vb, body))
    import base64
    return "data:image/svg+xml," + base64.b64encode(s.encode()).decode()

L["slack"] = _svg(
    '<rect x="2" y="10" width="6" height="3" rx="1.5" fill="#36C5F0"/>'
    '<rect x="11" y="2" width="3" height="6" rx="1.5" fill="#2EB67D"/>'
    '<rect x="16" y="11" width="6" height="3" rx="1.5" fill="#ECB22E"/>'
    '<rect x="10" y="16" width="3" height="6" rx="1.5" fill="#E01E5A"/>'
    '<rect x="9" y="9" width="6" height="6" rx="1.5" fill="#5A6B7B"/>')
L["git"] = _svg(
    '<circle cx="6" cy="5" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<circle cx="6" cy="19" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<circle cx="18" cy="9" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<path d="M6 7.6v8.8M8.6 5H14a4 4 0 0 1 4 4v.5" stroke="#525252" '
    'stroke-width="1.6" stroke-linecap="round"/>')
L["shield"] = _svg(
    '<path d="M12 2.5 20 5.5v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z" '
    'stroke="#525252" stroke-width="1.6" stroke-linejoin="round"/>'
    '<path d="m8.6 12 2.4 2.4 4.4-4.6" stroke="#525252" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/>')
L["clock"] = _svg(
    '<circle cx="12" cy="12" r="9" stroke="#525252" stroke-width="1.6"/>'
    '<path d="M12 6.8V12l3.4 2" stroke="#525252" stroke-width="1.6" '
    'stroke-linecap="round"/>')
L["bell"] = _svg(
    '<path d="M6 10a6 6 0 1 1 12 0c0 4 1.6 5.6 1.6 5.6H4.4S6 14 6 10Z" '
    'stroke="#525252" stroke-width="1.6" stroke-linejoin="round"/>'
    '<path d="M10 19a2 2 0 0 0 4 0" stroke="#525252" stroke-width="1.6" '
    'stroke-linecap="round"/>')
L["share"] = _svg(
    '<circle cx="6" cy="12" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<circle cx="18" cy="6" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<circle cx="18" cy="18" r="2.6" stroke="#525252" stroke-width="1.6"/>'
    '<path d="m8.4 10.8 7.2-3.6M8.4 13.2l7.2 3.6" stroke="#525252" '
    'stroke-width="1.6"/>')


# ------------------------------------------------------------------ model --
class Page:
    def __init__(self, name):
        self.name = name
        self.items = []
        self._n = 0

    def _id(self, pref="c"):
        self._n += 1
        return "%s%d" % (pref, self._n)

    def add(self, **kw):
        kw.setdefault("id", self._id())
        self.items.append(kw)
        return kw["id"]

    # -- primitives ---------------------------------------------------------
    def rect(self, x, y, w, h, fill=WHITE, stroke=LINE, sw=1, radius=8,
             text="", size=13, color=INK, bold=False, align="center",
             valign="middle", pl=8, pr=8, pt=6, pb=6, font=FONT, dashed=False,
             image=None, iw=0, ih=0, ialign="left", ivalign="middle",
             id=None, opacity=None):
        return self.add(kind="rect", x=x, y=y, w=w, h=h, fill=fill,
                        stroke=stroke, sw=sw, radius=radius, text=text,
                        size=size, color=color, bold=bold, align=align,
                        valign=valign, pl=pl, pr=pr, pt=pt, pb=pb, font=font,
                        dashed=dashed, image=image, iw=iw, ih=ih,
                        ialign=ialign, ivalign=ivalign,
                        **({"id": id} if id else {}),
                        **({"opacity": opacity} if opacity else {}))

    def text(self, x, y, w, h, text, size=13, color=INK, bold=False,
             align="left", valign="middle", font=FONT, id=None, ls=0):
        return self.add(kind="text", x=x, y=y, w=w, h=h, text=text, size=size,
                        color=color, bold=bold, align=align, valign=valign,
                        font=font, ls=ls, **({"id": id} if id else {}))

    def img(self, x, y, w, h, image, id=None):
        return self.add(kind="image", x=x, y=y, w=w, h=h, image=image,
                        **({"id": id} if id else {}))

    def edge(self, src, dst, color=EDGE, sw=2, dashed=False, label="",
             ex=1.0, ey=0.5, nx=0.0, ny=0.5, points=None, lsize=11,
             lpos=None, ldx=0, ldy=-11):
        return self.add(kind="edge", src=src, dst=dst, color=color, sw=sw,
                        dashed=dashed, label=label, ex=ex, ey=ey, nx=nx,
                        ny=ny, points=points or [], lsize=lsize, lpos=lpos,
                        ldx=ldx, ldy=ldy)

    # -- composites ---------------------------------------------------------
    def panel(self, x, y, w, h, title, kicker=None):
        """Light grouping panel with a title, as in future_arch."""
        pid = self.rect(x, y, w, h, fill=PANEL, stroke=PANEL_LINE, radius=10,
                        text="", valign="top")
        self.text(x + 14, y + 10, w - 28, 20, title, size=13, bold=True,
                  color=INK, align="left")
        if kicker:
            self.text(x + 14, y + 28, w - 28, 16, kicker, size=10.5,
                      color=FAINT, align="left", ls=0.6)
        return pid

    def logocard(self, x, y, w, h, logo, title, lines=(), lw=30, lh=30,
                 fill=WHITE, stroke=LINE, id=None, size=12.5, pad=14):
        """White card with a logo on the left and stacked text.

        The logo is a separate element (not shape=label) so the drawio and
        HTML renderers place it identically.
        """
        body = "<b>%s</b>" % title
        for ln in lines:
            body += '<br><font color="%s" style="font-size:11px">%s</font>' % (
                MUTED, ln)
        cid = self.rect(x, y, w, h, fill=fill, stroke=stroke, radius=8,
                        text=body, size=size, align="left", valign="middle",
                        pl=pad + lw + 12, pr=12, id=id)
        if logo:
            self.img(x + pad, y + (h - lh) / 2.0, lw, lh, logo)
        return cid

    def accentcard(self, x, y, w, h, accent, title, lines=(), logo=None,
                   lw=22, lh=22, fill=WHITE, size=11.5, tsize=12.5, id=None):
        """White card with a coloured spine on the left."""
        cid = self.rect(x, y, w, h, fill=fill, stroke=LINE, radius=8,
                        text='<b style="font-size:%spx">%s</b><br>%s'
                             % (tsize, title,
                                "<br>".join('<font color="%s">%s</font>' % (MUTED, l)
                                            if l else "&nbsp;" for l in lines)),
                        size=size, align="left", valign="top",
                        pl=18 + (lw + 10 if logo else 0), pr=14, pt=12, id=id)
        self.rect(x, y + 10, 5, h - 20, fill=accent, stroke="none", radius=3)
        if logo:
            self.img(x + 18, y + 13, lw, lh, logo)
        return cid

    def table(self, x, y, colw, rowh, header, rows, headfill=HEAD_FILL,
              headcolor=WHITE, size=11, aligns=None, colors=None, bold0=True):
        """Compact grid table; returns total height."""
        aligns = aligns or (["left"] + ["center"] * (len(colw) - 1))
        cx = x
        for i, w in enumerate(colw):
            r = 6 if i == 0 else 0
            self.rect(cx, y, w, rowh, fill=headfill, stroke="none",
                      radius=6 if i in (0, len(colw) - 1) else 0,
                      text="<b>%s</b>" % header[i], size=size - 0.5,
                      color=headcolor, align=aligns[i], pl=12, pr=12)
            cx += w
        for r, row in enumerate(rows):
            cx = x
            yy = y + rowh * (r + 1)
            band = WHITE if r % 2 == 0 else "#FAFBFC"
            for i, w in enumerate(colw):
                col = INK if (i == 0 and bold0) else MUTED
                cell = row[i]
                fillc = band
                if colors and colors.get(cell):
                    fillc = colors[cell][0]
                    col = colors[cell][1]
                self.rect(cx, yy, w, rowh, fill=fillc, stroke=CARD_LINE,
                          radius=0, sw=1,
                          text=("<b>%s</b>" % cell) if (i == 0 and bold0)
                               else cell,
                          size=size, color=col, align=aligns[i], pl=12, pr=12)
                cx += w
        return rowh * (len(rows) + 1)

    def note(self, x, y, w, h, title, lines=(), fill=WHITE, stroke=LINE,
             size=11.5, logo=None, lw=22, lh=22, mono=False, lead=None):
        """Titled reference card: bold heading then muted body lines."""
        body = ['<b style="font-size:12.5px">%s</b>' % title]
        if lead:
            body.append('<font color="%s">%s</font>' % (MUTED, lead))
        for ln in lines:
            body.append('<font color="%s">%s</font>' % (MUTED, ln)
                        if ln else "&nbsp;")
        pl = 16 + (lw + 10 if logo else 0)
        cid = self.rect(x, y, w, h, fill=fill, stroke=stroke, radius=10,
                        text="<br>".join(body), size=size, align="left",
                        valign="top", pl=pl, pr=14, pt=12,
                        font=MONO if mono else FONT)
        if logo:
            self.img(x + 16, y + 13, lw, lh, logo)
        return cid

    def chip(self, x, y, w, h, label, fill=TEAL, color=WHITE, size=12):
        return self.rect(x, y, w, h, fill=fill, stroke="none", radius=6,
                         text=label, size=size, color=color, align="center")

    def kicker(self, x, y, w, label):
        return self.text(x, y, w, 16, label, size=10.5, bold=True,
                         color=FAINT, align="left", ls=1.1)

    def head(self, x, y, w, title, subtitle=None, size=30):
        self.text(x, y, w, size + 12, "<b>%s</b>" % title, size=size,
                  color=INK, align="left")
        if subtitle:
            self.text(x, y + size + 12, w, 22, subtitle, size=13.5,
                      color=MUTED, align="left")
        self.rect(x, y - 14, 54, 5, fill=RED, stroke="none", radius=3)


# --------------------------------------------------------------- emitters --
def _esc(s):
    return _html.escape(str(s), quote=True)


def _style(it):
    k = it["kind"]
    if k == "text":
        s = ("text;html=1;strokeColor=none;fillColor=none;align=%s;"
             "verticalAlign=%s;whiteSpace=wrap;fontSize=%s;fontColor=%s;"
             "fontFamily=%s;" % (it["align"], it["valign"], it["size"],
                                 it["color"], it["font"]))
        if it["bold"]:
            s += "fontStyle=1;"
        if it.get("ls"):
            s += "letterSpacing=%s;" % it["ls"]
        return s
    if k == "image":
        s = ("shape=image;imageAspect=0;aspect=fixed;verticalLabelPosition="
             "bottom;verticalAlign=top;labelBackgroundColor=default;"
             "image=%s;" % it["image"])
        if it["image"].startswith("data:image/svg"):
            s = "editableCssRules=.*;" + s
        return s
    # rect
    base = "shape=label;" if it.get("image") else ""
    s = (base + "rounded=1;absoluteArcSize=1;arcSize=%s;whiteSpace=wrap;"
         "html=1;fillColor=%s;strokeColor=%s;strokeWidth=%s;fontColor=%s;"
         "fontSize=%s;align=%s;verticalAlign=%s;spacingLeft=%s;"
         "spacingRight=%s;spacingTop=%s;spacingBottom=%s;fontFamily=%s;"
         % (it["radius"], it["fill"], it["stroke"], it["sw"], it["color"],
            it["size"], it["align"], it["valign"], it["pl"], it["pr"],
            it["pt"], it["pb"], it["font"]))
    if it["bold"]:
        s += "fontStyle=1;"
    if it["dashed"]:
        s += "dashed=1;dashPattern=6 5;"
    if it.get("opacity"):
        s += "opacity=%s;" % it["opacity"]
    if it.get("image"):
        s += ("image=%s;imageAlign=%s;imageVerticalAlign=%s;imageWidth=%s;"
              "imageHeight=%s;" % (it["image"], it["ialign"], it["ivalign"],
                                   it["iw"], it["ih"]))
        if it["image"].startswith("data:image/svg"):
            s = "editableCssRules=.*;" + s
    return s


def to_drawio(pages, path):
    out = ['<mxfile host="Claude" type="device" pages="%d">' % len(pages)]
    for pi, p in enumerate(pages):
        xs = [i["x"] for i in p.items if i["kind"] != "edge"]
        ys = [i["y"] for i in p.items if i["kind"] != "edge"]
        ws = [i["x"] + i["w"] for i in p.items if i["kind"] != "edge"]
        hs = [i["y"] + i["h"] for i in p.items if i["kind"] != "edge"]
        pw, ph = int(max(ws) + 40), int(max(hs) + 40)
        out.append('  <diagram id="xf-p%d" name="%s">' % (pi + 1, _esc(p.name)))
        # page="0" -> Page View is OFF when the file opens (infinite canvas,
        # no page outline / page breaks); grid="0" -> grid hidden. pageWidth /
        # pageHeight are still written so File > Print / Export still fit the
        # diagram if the user switches Page View back on. Keep both at "0".
        out.append('    <mxGraphModel dx="1400" dy="900" grid="0" gridSize="10"'
                   ' guides="1" tooltips="1" connect="1" arrows="1" fold="1"'
                   ' page="0" pageScale="1" pageWidth="%d" pageHeight="%d"'
                   ' math="0" shadow="0">' % (pw, ph))
        out.append('      <root><mxCell id="0" /><mxCell id="1" parent="0" />')
        for it in p.items:
            if it["kind"] == "edge":
                st = ("edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;"
                      "jettySize=auto;html=1;endArrow=block;endFill=1;"
                      "strokeColor=%s;strokeWidth=%s;exitX=%s;exitY=%s;exitDx=0;"
                      "exitDy=0;entryX=%s;entryY=%s;entryDx=0;entryDy=0;"
                      "fontFamily=%s;fontSize=%s;fontColor=%s;"
                      % (it["color"], it["sw"], it["ex"], it["ey"], it["nx"],
                         it["ny"], FONT, it["lsize"], MUTED))
                if it["dashed"]:
                    st += "dashed=1;dashPattern=6 5;"
                out.append('        <mxCell id="%s" style="%s" edge="1" '
                           'parent="1" source="%s" target="%s">'
                           % (it["id"], _esc(st), it["src"], it["dst"]))
                out.append('          <mxGeometry relative="1" as="geometry">')
                if it["points"]:
                    out.append('            <Array as="points">')
                    for (px, py) in it["points"]:
                        out.append('              <mxPoint x="%s" y="%s" />'
                                   % (px, py))
                    out.append('            </Array>')
                out.append('          </mxGeometry>')
                out.append('        </mxCell>')
                if it["label"]:
                    lst = ("edgeLabel;html=1;align=center;verticalAlign=middle;"
                           "resizable=0;points=[];labelBackgroundColor=#FFFFFF;"
                           "fontSize=%s;fontColor=%s;fontFamily=%s;"
                           % (it["lsize"], MUTED, FONT))
                    out.append('        <mxCell id="%sl" value="%s" style="%s" '
                               'vertex="1" connectable="0" parent="%s">'
                               % (it["id"], _esc(it["label"]), _esc(lst),
                                  it["id"]))
                    g = '<mxGeometry relative="1" as="geometry">'
                    if it["lpos"] is not None:
                        g = ('<mxGeometry x="%s" relative="1" as="geometry">'
                             % it["lpos"])
                    out.append('          %s' % g)
                    out.append('            <mxPoint x="%s" y="%s" as="offset" />'
                               % (it["ldx"], it["ldy"]))
                    out.append('          </mxGeometry>')
                    out.append('        </mxCell>')
                continue
            val = it.get("text", "") or ""
            out.append('        <mxCell id="%s" value="%s" style="%s" '
                       'vertex="1" parent="1">'
                       % (it["id"], _esc(val), _esc(_style(it))))
            out.append('          <mxGeometry x="%s" y="%s" width="%s" '
                       'height="%s" as="geometry" />'
                       % (it["x"], it["y"], it["w"], it["h"]))
            out.append('        </mxCell>')
        out.append('      </root>')
        out.append('    </mxGraphModel>')
        out.append('  </diagram>')
    out.append('</mxfile>')
    open(path, "w", encoding="utf-8").write("\n".join(out))
    return path


# ---- HTML preview (same model, rendered by the browser for visual check) ---
_FLEX = {"left": "flex-start", "center": "center", "right": "flex-end",
         "top": "flex-start", "middle": "center", "bottom": "flex-end"}


def _uri(u):
    """drawio stores `data:image/png,<b64>`; browsers need `;base64,`."""
    for pre in ("data:image/png,", "data:image/svg+xml,", "data:image/webp,",
                "data:image/jpeg,", "data:image/gif,"):
        if u.startswith(pre):
            return pre[:-1] + ";base64," + u[len(pre):]
    return u


def _rect_html(it):
    st = ["position:absolute", "left:%spx" % it["x"], "top:%spx" % it["y"],
          "width:%spx" % it["w"], "height:%spx" % it["h"],
          "box-sizing:border-box", "border-radius:%spx" % it["radius"]]
    if it["fill"] != "none":
        st.append("background:%s" % it["fill"])
    if it["stroke"] != "none":
        st.append("border:%spx %s %s" % (it["sw"],
                                         "dashed" if it["dashed"] else "solid",
                                         it["stroke"]))
    if it.get("opacity"):
        st.append("opacity:%s" % (float(it["opacity"]) / 100))
    # A rect with no label carries no padding: with box-sizing:border-box the
    # browser clamps the used width up to the padding sum, so a 5px accent
    # spine would paint ~20px wide while draw.io draws it at 5. That silent
    # disagreement is exactly what the preview exists to prevent.
    _pad = ("0" if not ((it.get("text") or "").strip() or it.get("image"))
            else "%spx %spx %spx %spx" % (it["pt"] + 2, it["pr"] + 2,
                                          it["pb"] + 2, it["pl"] + 2))
    st += ["display:flex", "align-items:%s" % _FLEX[it["valign"]],
           "justify-content:%s" % _FLEX[it["align"]],
           "padding:%s" % _pad,
           "font-family:%s,Helvetica,Arial,sans-serif" % it["font"],
           "font-size:%spx" % it["size"], "color:%s" % it["color"],
           "line-height:1.32", "overflow:hidden"]
    if it["bold"]:
        st.append("font-weight:700")
    inner = '<div style="text-align:%s;width:100%%">%s</div>' % (
        it["align"], it.get("text", "") or "")
    img = ""
    if it.get("image"):
        ix = {"left": "left:%spx" % (it["pl"] - it["iw"] - 8 + 10),
              "center": "left:%spx" % ((it["w"] - it["iw"]) / 2),
              "right": "right:12px"}[it["ialign"]]
        iy = {"top": "top:10px",
              "middle": "top:%spx" % ((it["h"] - it["ih"]) / 2),
              "bottom": "bottom:10px"}[it["ivalign"]]
        img = ('<img src="%s" style="position:absolute;%s;%s;width:%spx;'
               'height:%spx;object-fit:contain">'
               % (_uri(it["image"]), ix, iy, it["iw"], it["ih"]))
    return '<div style="%s">%s%s</div>' % (";".join(st), img, inner)


def _text_html(it):
    st = ["position:absolute", "left:%spx" % it["x"], "top:%spx" % it["y"],
          "width:%spx" % it["w"], "height:%spx" % it["h"], "display:flex",
          "align-items:%s" % _FLEX[it["valign"]],
          "justify-content:%s" % _FLEX[it["align"]],
          "font-family:%s,Helvetica,Arial,sans-serif" % it["font"],
          "font-size:%spx" % it["size"], "color:%s" % it["color"],
          "line-height:1.32", "box-sizing:border-box"]
    if it["bold"]:
        st.append("font-weight:700")
    if it.get("ls"):
        st.append("letter-spacing:%spx" % it["ls"])
    return '<div style="%s"><div style="width:100%%;text-align:%s">%s</div></div>' % (
        ";".join(st), it["align"], it["text"])


def _edge_svg(it, byid):
    a, b = byid.get(it["src"]), byid.get(it["dst"])
    if not a or not b:
        return ""
    x1 = a["x"] + a["w"] * it["ex"]
    y1 = a["y"] + a["h"] * it["ey"]
    x2 = b["x"] + b["w"] * it["nx"]
    y2 = b["y"] + b["h"] * it["ny"]
    pts = [(x1, y1)] + list(it["points"]) + [(x2, y2)]
    # orthogonalise: insert elbows between consecutive points
    path = [pts[0]]
    for p in pts[1:]:
        px, py = path[-1]
        if abs(p[0] - px) > 0.5 and abs(p[1] - py) > 0.5:
            path.append((p[0], py) if abs(p[0] - px) > abs(p[1] - py)
                        else (px, p[1]))
        path.append(p)
    d = "M " + " L ".join("%s %s" % (round(px, 1), round(py, 1))
                          for px, py in path)
    dash = ' stroke-dasharray="6 5"' if it["dashed"] else ""
    out = ('<path d="%s" fill="none" stroke="%s" stroke-width="%s"%s '
           'marker-end="url(#ah%s)"/>' % (d, it["color"], it["sw"], dash,
                                          it["color"].lstrip("#")))
    if it["label"]:
        segs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        (ax, ay), (bx, by) = max(segs, key=lambda s: abs(s[1][0] - s[0][0])
                                 + abs(s[1][1] - s[0][1]))
        t = it["lpos"] if it["lpos"] is not None else 0.5
        t = min(max((t + 1) / 2 if t < 0 else t, 0), 1)
        mx = ax + (bx - ax) * t + it["ldx"]
        my = ay + (by - ay) * t + it["ldy"]
        out += ('<text x="%s" y="%s" text-anchor="middle" font-size="%s" '
                'fill="%s" font-family="Helvetica" '
                'style="paint-order:stroke;stroke:#fff;stroke-width:5px">%s'
                '</text>' % (round(mx, 1), round(my, 1), it["lsize"], MUTED,
                             _html.escape(it["label"])))
    return out


def to_html(pages, path, scale=1.0):
    body = []
    for p in pages:
        ws = [i["x"] + i["w"] for i in p.items if i["kind"] != "edge"]
        hs = [i["y"] + i["h"] for i in p.items if i["kind"] != "edge"]
        pw, ph = int(max(ws) + 40), int(max(hs) + 40)
        byid = {i["id"]: i for i in p.items if i["kind"] != "edge"}
        colors = {i["color"] for i in p.items if i["kind"] == "edge"}
        defs = "".join(
            '<marker id="ah%s" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M0 0 L10 5 L0 10 z" fill="%s"/></marker>'
            % (c.lstrip("#"), c) for c in colors)
        edges = "".join(_edge_svg(i, byid) for i in p.items
                        if i["kind"] == "edge")
        parts = []
        for it in p.items:
            if it["kind"] == "rect":
                parts.append(_rect_html(it))
            elif it["kind"] == "text":
                parts.append(_text_html(it))
            elif it["kind"] == "image":
                parts.append('<img src="%s" style="position:absolute;left:%spx;'
                             'top:%spx;width:%spx;height:%spx;object-fit:'
                             'contain">' % (_uri(it["image"]), it["x"],
                                            it["y"], it["w"], it["h"]))
        body.append(
            '<div class="pg" data-name="%s" style="width:%spx;height:%spx">'
            '%s<svg style="position:absolute;inset:0;width:%spx;height:%spx;'
            'pointer-events:none"><defs>%s</defs>%s</svg></div>'
            % (_esc(p.name), pw, ph, "".join(parts), pw, ph, defs, edges))
    doc = ("<!doctype html><meta charset=utf-8><style>"
           "body{margin:0;background:#fff}"
           ".pg{position:relative;background:#fff;overflow:hidden}"
           "</style>" + "".join(body))
    open(path, "w", encoding="utf-8").write(doc)
    return path
