#!/usr/bin/env python3
"""extract_drawio.py — reverse-engineer an existing .drawio file.

Three jobs, all of which you want before you start drawing:

  --text FILE      Dump every cell's text, style and geometry, page by page.
                   This is your content inventory. Work from THIS, never from a
                   screenshot — the whole value of a rebuild is that no fact
                   gets lost, and a screenshot loses the ones behind the
                   scroll edge.

  --palette FILE   Frequency-count the fills, strokes, fonts and sizes. When
                   someone says "make it look like this file", this tells you
                   what "this" actually is in hex.

  --logos FILE     Harvest the base64-embedded images, deduplicate them,
                   downsample, and write a logo pack you can load with
                   drawio_kit.load_logos(). Also writes a contact sheet PNG so
                   you can see which mark is which — the pack keys are hashes
                   until you rename them, so look at the sheet and rename.

Examples
    python extract_drawio.py --text source.drawio > inventory.txt
    python extract_drawio.py --palette brand_reference.drawio
    python extract_drawio.py --logos brand_reference.drawio --out logos.json
"""
import argparse
import base64
import collections
import hashlib
import html as _html
import io
import json
import os
import re
import xml.etree.ElementTree as ET

IMG_RE = re.compile(r"image=data:image/([a-zA-Z+]+),([A-Za-z0-9+/=%]+)")
STYLE_RE = re.compile(r"([a-zA-Z]+)=([^;]*)")


def cells(path):
    root = ET.parse(path).getroot()
    for diagram in root.iter("diagram"):
        for c in diagram.iter():
            if c.tag in ("mxCell", "object"):
                yield diagram.get("name") or "Page", c


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dump_text(path):
    page = None
    for pname, c in cells(path):
        if pname != page:
            page = pname
            print("\n########## PAGE: %s" % page)
        raw = c.get("value") or c.get("label") or ""
        txt = re.sub(r"<br\s*/?>", "  |  ", raw)
        txt = re.sub(r"<[^>]+>", "", _html.unescape(txt)).strip()
        style = re.sub(r"image=data:[^;\"]+", "image=<EMBEDDED>",
                       c.get("style") or "")
        g = c.find("mxGeometry")
        geo = ""
        if g is not None:
            geo = "[%s,%s %sx%s]" % (g.get("x"), g.get("y"),
                                     g.get("width"), g.get("height"))
        if c.get("edge"):
            print("%s: EDGE %s -> %s" % (c.get("id"), c.get("source"),
                                         c.get("target")))
        elif txt or style:
            print("%s: %r" % (c.get("id"), txt))
        if style:
            print("    style: %s" % style[:220])
        if geo:
            print("    geo:   %s" % geo)


def dump_palette(path):
    buckets = collections.defaultdict(collections.Counter)
    keys = ("fillColor", "strokeColor", "fontColor", "fontFamily", "fontSize",
            "rounded", "arcSize", "strokeWidth", "align", "verticalAlign",
            "shape", "edgeStyle", "endArrow", "dashed")
    n = 0
    for _, c in cells(path):
        style = c.get("style") or ""
        if not style:
            continue
        n += 1
        for k, v in STYLE_RE.findall(style):
            if k in keys:
                buckets[k][v[:40]] += 1
    print("%s — %d styled cells\n" % (os.path.basename(path), n))
    for k in keys:
        if not buckets[k]:
            continue
        print("%s" % k)
        for v, cnt in buckets[k].most_common(14):
            print("   %5d  %s" % (cnt, v))
        print()


def dump_logos(path, out, max_px, sheet):
    raw = open(path, encoding="utf-8", errors="replace").read()
    seen, pack = {}, {}
    for m in IMG_RE.finditer(raw):
        fmt, dat = m.group(1), m.group(2)
        key = hashlib.md5(dat.encode()).hexdigest()[:8]
        if key in seen:
            continue
        seen[key] = True
        uri = "data:image/%s,%s" % (fmt, dat)
        if fmt == "svg+xml":
            pack[key] = uri
            continue
        try:
            from PIL import Image
            blob = base64.b64decode(dat + "=" * (-len(dat) % 4))
            im = Image.open(io.BytesIO(blob)).convert("RGBA")
            if max(im.size) > max_px:
                r = max_px / max(im.size)
                im = im.resize((max(1, int(im.width * r)),
                                max(1, int(im.height * r))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            pack[key] = ("data:image/png,"
                         + base64.b64encode(buf.getvalue()).decode())
        except ImportError:
            pack[key] = uri
    with open(out, "w") as fh:
        json.dump(pack, fh, indent=0)
    total = sum(len(v) for v in pack.values())
    print("wrote %s — %d marks, %.0f KB of base64" % (out, len(pack),
                                                      total / 1024))

    if sheet:
        write_sheet(pack, sheet)


def write_sheet(pack, sheet):
    """Render a labelled contact sheet so you can name the marks.

    Rendered through headless Chromium rather than Pillow, because Pillow
    cannot rasterise SVG at all and many marks are SVG. Every tile sets an
    explicit width and height: simple-icons style marks often declare
    width="1" height="1" and collapse to an invisible dot if you let the
    browser use their intrinsic size.
    """
    tiles = []
    for key, uri in pack.items():
        pre, dat = uri.split(",", 1)
        browser_uri = pre + ";base64," + dat if ";base64" not in pre else uri
        tiles.append(
            '<figure><img src="%s" width="120" height="72" alt="%s">'
            '<figcaption>%s</figcaption></figure>' % (browser_uri, key, key))
    html = ("<!doctype html><meta charset=utf-8><style>"
            "body{margin:0;background:#fff;font:12px Helvetica,Arial;"
            "display:grid;grid-template-columns:repeat(5,180px);}"
            "figure{margin:0;padding:14px 0;text-align:center}"
            "img{object-fit:contain}"
            "figcaption{margin-top:8px;color:#1C2B33}"
            "</style><div id=sheet style='display:contents'>%s</div>"
            % "".join(tiles))
    html_path = os.path.splitext(sheet)[0] + ".html"
    with open(html_path, "w") as fh:
        fh.write(html)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("wrote %s — open it in a browser to see the marks "
              "(playwright missing, no PNG)" % html_path)
        return
    exe = None
    for cand in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                 "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        if os.path.exists(cand):
            exe = cand
            break
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page(viewport={"width": 900, "height": 400})
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_timeout(700)
        pg.screenshot(path=sheet, full_page=True)
        b.close()
    print("wrote %s — look at it, then rename the hash keys in the pack to "
          "readable names (mysql, kafka, snowflake ...)" % sheet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--palette")
    ap.add_argument("--logos")
    ap.add_argument("--out", default="logos.json")
    ap.add_argument("--sheet", default="logo_sheet.png")
    ap.add_argument("--max-px", type=int, default=140,
                    help="downsample raster marks to this longest edge; the "
                         "whole pack rides inside the .drawio, so keep it small")
    a = ap.parse_args()
    if a.text:
        dump_text(a.text)
    if a.palette:
        dump_palette(a.palette)
    if a.logos:
        dump_logos(a.logos, a.out, a.max_px, a.sheet)
    if not (a.text or a.palette or a.logos):
        ap.error("give one of --text / --palette / --logos")


if __name__ == "__main__":
    main()
