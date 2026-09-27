#!/usr/bin/env python3
"""fetch_logos.py — get real brand marks for products the bundled pack lacks.

The bundled pack covers the Databricks/lakehouse world. The moment a diagram
needs Kafka, Snowflake, Looker, SAP or anything else, you need marks from
somewhere — and the usual logo CDNs are blocked by egress policy here. The npm
registry is not, and `simple-icons` ships ~3,500 official monochrome SVG marks
with each brand's hex colour, CC0-licensed.

    python fetch_logos.py kafka flink snowflake looker sap --out logos.json

Names are fuzzy-matched against the pack's titles, slugs and aliases, so
"kafka" finds "Apache Kafka". Each mark is tinted to its brand colour and
written as a draw.io data URI. Then in your page module:

    load_logos("logos.json")
    p.logocard(..., L["kafka"], "Kafka", ["topic orders.v2"])

Some marks get removed from current releases after trademark requests (dbt,
Salesforce, Power BI and the Azure marks are gone as of writing). The script
tells you which names it could not resolve — for those, either try an older
release with --version, or draw a stroke icon with drawio_kit.svg_mark(). Do
not approximate a brand freehand; a wrong logo is worse than a neutral glyph.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


def install(version, workdir):
    spec = "simple-icons" + ("@" + version if version else "")
    print("installing %s ..." % spec, file=sys.stderr)
    r = subprocess.run(["npm", "install", spec, "--silent", "--no-audit",
                        "--no-fund"], cwd=workdir, capture_output=True,
                       text=True, timeout=420)
    root = os.path.join(workdir, "node_modules", "simple-icons")
    if not os.path.isdir(root):
        sys.exit("npm install failed:\n" + (r.stderr or r.stdout)[-1500:])
    return root


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def build_index(root):
    with open(os.path.join(root, "data", "simple-icons.json")) as fh:
        data = json.load(fh)
    if isinstance(data, dict):                      # older releases
        data = data.get("icons", [])
    idx = {}
    for item in data:
        title = item.get("title", "")
        slug = item.get("slug") or norm(title)
        keys = {norm(title), norm(slug)}
        aka = (item.get("aliases") or {})
        for group in ("aka", "old", "dup"):
            for alt in aka.get(group, []) or []:
                keys.add(norm(alt if isinstance(alt, str)
                              else alt.get("title", "")))
        for k in keys:
            if k:
                idx.setdefault(k, (slug, title, item.get("hex", "525252")))
    return idx


def resolve(name, idx):
    """Exact, then prefix, then substring — never the reverse.

    Matching a catalogue key *inside* the query is what makes "kafka" resolve
    to "F#": one-letter titles are substrings of everything. Only ever look for
    the query inside a key, and require enough characters to mean something.
    """
    n = norm(name)
    if not n:
        return None
    if n in idx:
        return idx[n]
    if len(n) >= 3:
        pre = [(k, v) for k, v in idx.items() if k.startswith(n)]
        if pre:
            return sorted(pre, key=lambda kv: len(kv[0]))[0][1]
    if len(n) >= 4:
        sub = [(k, v) for k, v in idx.items() if n in k]
        if sub:
            return sorted(sub, key=lambda kv: len(kv[0]))[0][1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="product names, e.g. kafka snowflake")
    ap.add_argument("--out", default="logos.json")
    ap.add_argument("--version", default="",
                    help="pin a simple-icons release, e.g. 11.14.0 — useful "
                         "for marks removed from the current one")
    ap.add_argument("--keep-mono", action="store_true",
                    help="leave marks black instead of tinting to brand colour")
    a = ap.parse_args()

    work = tempfile.mkdtemp(prefix="siconv-")
    try:
        root = install(a.version, work)
        idx = build_index(root)
        pack, missing = {}, []
        for name in a.names:
            if norm(name).replace("_", "") in ("unitycatalog", "uc"):
                print("skip %s - Unity Catalog always uses the official "
                      "assets/unity_catalog.jpg (L['unity_catalog'])" % name)
                continue
            hit = resolve(name, idx)
            if not hit:
                missing.append(name)
                continue
            slug, title, hexcol = hit
            path = os.path.join(root, "icons", slug + ".svg")
            if not os.path.exists(path):
                missing.append(name)
                continue
            svg = open(path, encoding="utf-8").read()
            if not a.keep_mono:
                # simple-icons ships unfilled paths that inherit currentColor;
                # set an explicit fill so the mark shows its brand colour in
                # both draw.io and the HTML preview.
                svg = svg.replace("<svg ", '<svg fill="#%s" ' % hexcol, 1)
            pack[norm(name)] = ("data:image/svg+xml,"
                                + base64.b64encode(svg.encode()).decode())
            print("  %-14s -> %s (#%s)" % (name, title, hexcol))
        if os.path.exists(a.out):
            pack = {**json.load(open(a.out)), **pack}
        json.dump(pack, open(a.out, "w"), indent=0)
        print("\nwrote %s — %d marks" % (a.out, len(pack)))
        if missing:
            print("NOT FOUND: %s" % ", ".join(missing))
            print("Either retry with --version <older release>, or draw these "
                  "with drawio_kit.svg_mark() in the same stroke style as the "
                  "other generic icons. Never approximate a brand by hand.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
