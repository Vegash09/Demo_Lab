#!/usr/bin/env python3
"""render.py — build the .drawio, the HTML preview, the PNGs, and audit layout.

This is the loop. draw.io has no headless renderer, so you cannot see what you
just built by opening the .drawio. What you CAN do is emit an HTML page from the
same layout model and screenshot that — which is what this script does, plus a
static audit that catches the two mistakes that actually happen in practice:
text that overflows its card, and cards with a lot of dead space at the bottom.

    python render.py --pages p1 p2 p3 --out ../out --name my_architecture.drawio

Run it from the directory holding your page modules. Each module must expose
build() returning a drawio_kit.Page. Then LOOK at the PNGs with the Read tool —
the audit catches size mistakes, only your eyes catch ugly.

Flags
  --pages A B C     page modules, in order (required)
  --out DIR         output directory (default ./out)
  --name FILE       .drawio filename (default architecture.drawio)
  --scale N         PNG device scale factor (default 1.5; use 2 for print)
  --no-png          skip the browser step (fast; audit still runs)
  --quiet-audit     only print problems, not the per-page summary
"""
import argparse
import importlib
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drawio_kit import to_drawio, to_html  # noqa: E402

# Helvetica at 1em is roughly 0.52em per character averaged over mixed-case
# prose. Good enough to catch "this obviously does not fit", which is all we
# need — the browser screenshot is the real check.
AVG_CHAR_W = 0.52
LINE_H = 1.35          # slightly generous: draw.io uses 1.2, the preview 1.32


def _plain(html):
    """Strip markup so we can count characters the reader will actually see."""
    t = re.sub(r"<br\s*/?>", "\n", html or "")
    t = re.sub(r"<[^>]+>", "", t)
    return (t.replace("&nbsp;", " ").replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">"))


def estimate_text_height(it):
    """Wrapped height of a label, in px.

    Padding only counts on the side the text is anchored to: a vertically
    centred one-line label sits happily in a box shorter than pt+text+pb, and
    counting both would flag every chip and table cell on the page.
    """
    usable = max(1, it["w"] - it.get("pl", 0) - it.get("pr", 0) - 8)
    size = float(it["size"])
    lines = 0
    for seg in _plain(it.get("text", "")).split("\n"):
        if not seg.strip():
            lines += 1
            continue
        lines += max(1, math.ceil(len(seg) * size * AVG_CHAR_W / usable))
    need = lines * size * LINE_H + 4
    valign = it.get("valign", "middle")
    if valign == "top":
        need += it.get("pt", 0)
    elif valign == "bottom":
        need += it.get("pb", 0)
    return need


_INLINE_COLOR = re.compile(
    r"""(?:color\s*=\s*["']|color\s*:\s*)(#[0-9A-Fa-f]{3,6}|[a-zA-Z]+)""")


def _is_dark(fill):
    """True for a fill dark enough that black text would be illegible."""
    f = str(fill or "").lstrip("#")
    if len(f) == 3:
        f = "".join(ch * 2 for ch in f)
    if len(f) != 6:
        return False
    r, g, b = (int(f[i:i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 180


def audit(page, quiet=False):
    """Return a list of human-readable layout problems."""
    boxes = [i for i in page.items if i["kind"] != "edge"]
    problems = []

    for it in boxes:
        if it["kind"] == "image" or not (it.get("text") or "").strip():
            continue
        need = estimate_text_height(it)
        h = it["h"]
        # 15% tolerance: the character-width estimate is approximate and
        # draw.io packs lines slightly tighter than the preview, so a hair
        # over is not a real clip. Anything genuinely too tall clears this
        # margin easily.
        if need > h * 1.15 + 2:
            problems.append(
                "OVERFLOW  %-9s at (%d,%d) %dx%d needs ~%dpx of text height "
                "— %r" % (it["kind"], it["x"], it["y"], it["w"], h, need,
                          _plain(it["text"])[:60]))
        elif (it["kind"] == "rect" and it.get("valign") == "top"
              and h - need > 46 and h > 90):
            problems.append(
                "SLACK     rect at (%d,%d) %dx%d — text needs only ~%dpx, so "
                "~%dpx is dead space; shrink it or add a line — %r"
                % (it["x"], it["y"], it["w"], h, need, h - need,
                   _plain(it["text"])[:50]))

    # TEXT COLOUR RULE: all text is pure black (#000000). The one defined
    # exception is white text on a dark, filled rect (table header, chip,
    # dark title bar). Anything else — a grey kicker, a navy title, a coloured
    # inline <font color> or style="color:..." — is flagged.
    for it in boxes:
        if it["kind"] == "image" or not (it.get("text") or "").strip():
            continue
        base = str(it.get("color", "")).upper()
        inline = [c.upper() for c in _INLINE_COLOR.findall(it["text"])]
        for c in [base] + inline:
            if c in ("#000000", "#000", "BLACK"):
                continue
            if (c in ("#FFFFFF", "#FFF", "WHITE") and it["kind"] == "rect"
                    and _is_dark(it.get("fill"))):
                continue
            problems.append(
                "COLOR     %-9s at (%d,%d) uses text colour %s — all text must "
                "be #000000 (white only on a dark fill) — %r"
                % (it["kind"], it["x"], it["y"], c, _plain(it["text"])[:50]))
    for it in page.items:
        if it["kind"] == "edge" and it.get("label"):
            inline = [c.upper() for c in _INLINE_COLOR.findall(it["label"])]
            for c in inline:
                if c not in ("#000000", "#000", "BLACK"):
                    problems.append("COLOR     edge label %r uses %s — connector "
                                    "labels must be #000000"
                                    % (_plain(it["label"])[:40], c))

    # containers legitimately overlap their children, so only flag same-size-
    # ish rects that collide — that is the signature of a placement mistake.
    rects = [i for i in boxes if i["kind"] == "rect"]
    for ia, a in enumerate(rects):
        for b in rects[ia + 1:]:
            ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
            bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
            ox = min(ax2, bx2) - max(a["x"], b["x"])
            oy = min(ay2, by2) - max(a["y"], b["y"])
            if ox <= 2 or oy <= 2:
                continue
            area_a, area_b = a["w"] * a["h"], b["w"] * b["h"]
            overlap = ox * oy
            small = min(area_a, area_b)
            # containment (a panel holding a card) is fine; partial collision
            # between two similarly sized boxes is not.
            if overlap > 0.9 * small:
                continue
            if 0.4 < area_a / area_b < 2.5:
                problems.append(
                    "COLLIDE   rect (%d,%d %dx%d) and rect (%d,%d %dx%d) "
                    "overlap by %dx%d px"
                    % (a["x"], a["y"], a["w"], a["h"],
                       b["x"], b["y"], b["w"], b["h"], ox, oy))

    if not quiet:
        w = max(i["x"] + i["w"] for i in boxes) + 40
        h = max(i["y"] + i["h"] for i in boxes) + 40
        print("  %-38s %5d x %-5d  %3d elements  %d edges"
              % (page.name[:38], w, h, len(boxes),
                 len(page.items) - len(boxes)))
    return problems


def shoot(html_path, out_dir, scale, prefix):
    """Screenshot every .pg block in the preview to its own PNG."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("! playwright not installed — skipping PNGs "
              "(pip install playwright --break-system-packages)")
        return []
    exe = None
    for cand in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
                 "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        if os.path.exists(cand):
            exe = cand
            break
    files = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe)
        pg = browser.new_page(viewport={"width": 1600, "height": 1000},
                              device_scale_factor=scale)
        pg.goto("file://" + os.path.abspath(html_path))
        pg.wait_for_timeout(1200)          # let base64 images decode
        for i in range(pg.locator(".pg").count()):
            f = os.path.join(out_dir, "%s_page%d.png" % (prefix, i + 1))
            pg.locator(".pg").nth(i).screenshot(path=f)
            files.append(f)
        browser.close()
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--name", default="architecture.drawio")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--quiet-audit", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, os.getcwd())
    os.makedirs(a.out, exist_ok=True)
    pages = []
    for m in a.pages:
        mod = importlib.import_module(m)
        importlib.reload(mod)
        pages.append(mod.build())

    drawio = os.path.join(a.out, a.name)
    html = os.path.join(a.out, "preview.html")
    to_drawio(pages, drawio)
    to_html(pages, html)
    print("wrote %s (%.0f KB)" % (drawio, os.path.getsize(drawio) / 1024))

    all_problems = []
    for p in pages:
        probs = audit(p, a.quiet_audit)
        if probs:
            all_problems.append((p.name, probs))

    if all_problems:
        print("\nLAYOUT AUDIT")
        for name, probs in all_problems:
            print("  %s" % name)
            for pr in probs:
                print("    " + pr)
        print("\n%d issue(s). OVERFLOW clips text in draw.io and must be "
              "fixed, and so must COLOR (text is always #000000). SLACK and COLLIDE "
              "are judgement calls — check the PNG."
              % sum(len(p) for _, p in all_problems))
    else:
        print("\nLAYOUT AUDIT  clean")

    if not a.no_png:
        prefix = os.path.splitext(a.name)[0]
        for f in shoot(html, a.out, a.scale, prefix):
            print("wrote %s" % f)
        print("\nNow READ the PNGs. The audit finds size mistakes; only "
              "looking finds ugly.")


if __name__ == "__main__":
    main()
