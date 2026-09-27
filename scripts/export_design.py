#!/usr/bin/env python3
"""Re-export the design/ architecture diagrams to ``design/images/*.png``.

The draw.io sources in ``design/`` are the source of truth; this script renders
them to PNGs that the README, ``docs/`` and ``design/OVERVIEW.md`` embed (and
that the standalone customer overview is built from). Run it after editing any
``design/*.drawio`` source — or via ``make design`` — and commit the
regenerated images. See the ``maintain-design-diagram`` skill.

The draw.io Desktop CLI is located via, in order: the ``DRAWIO`` environment
variable, a ``drawio`` binary on ``PATH``, then the default macOS app path. The
CLI is not available in CI, so this is a developer/agent-only step.
``--if-available`` turns "CLI not found" into a note and a clean exit — what
``make design`` uses, since it also re-renders the pipeline inventory
(scripts/design_inventory.py), which needs no draw.io at all.

Without the CLI, ``--if-available`` falls back to the kit's HTML twin (the same
layout model scripts/design_diagram.py emits the .drawio from), screenshotted
with playwright when it is installed.

draw.io's ``--page-index`` export is unreliable for multi-page files (it can
silently re-export page 0), so multi-page sources are split into single-page
temporary files first and each is exported on its own.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESIGN = REPO_ROOT / "design"
IMAGES = DESIGN / "images"

# Stable export flags so re-runs produce comparable output.
EXPORT_FLAGS = ["-x", "-f", "png", "-s", "2", "--crop", "-b", "16"]
DEFAULT_MACOS_DRAWIO = "/Applications/draw.io.app/Contents/MacOS/draw.io"


def find_drawio() -> str | None:
    """Return a usable draw.io CLI path, or None when there is none."""
    candidate = os.environ.get("DRAWIO") or shutil.which("drawio") or DEFAULT_MACOS_DRAWIO
    if Path(candidate).exists() or shutil.which(candidate):
        return candidate
    return None


NOT_FOUND = (
    "draw.io Desktop CLI not found. Install draw.io Desktop or set "
    "DRAWIO=/path/to/draw.io (tried: $DRAWIO, `drawio` on PATH, "
    f"{DEFAULT_MACOS_DRAWIO})."
)


def page_stem(name: str, index: int, prefix: str = "01") -> str:
    """'2 - AUTHOR - lane router' -> '01_2_author' (for 01_*.drawio);
    '2 - customer_sales' -> '02_2_customer_sales' (for 02_*.drawio); falls
    back to a page index. `prefix` is the source file's leading number."""
    match = re.match(r"\s*(\d+)\s*-\s*([A-Za-z0-9_]+)", name)
    if match:
        return f"{prefix}_{match.group(1)}_{match.group(2).lower()}"
    return f"{prefix}_p{index + 1}"


def image_names(src: Path) -> list[str]:
    """The PNG stem per page of one source, in page order - one name for a
    single-page file, one per page otherwise (the same rule for both renderers)."""
    text = src.read_text()
    names = re.findall(r'<diagram\b[^>]*name="([^"]*)"', text)
    if len(names) <= 1:
        return [src.stem]
    prefix = src.stem.split("_", 1)[0]
    return [page_stem(n, i, prefix) for i, n in enumerate(names)]


def render(drawio: str, src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([drawio, *EXPORT_FLAGS, "-o", str(out), str(src)], check=True)
    print(f"  -> {out.relative_to(REPO_ROOT)}")


def export_source(drawio: str, src: Path) -> None:
    """Export one .drawio source; split multi-page files page by page."""
    text = src.read_text()
    diagrams = re.findall(r"<diagram\b.*?</diagram>", text, re.S)
    if len(diagrams) <= 1:
        render(drawio, src, IMAGES / f"{src.stem}.png")
        return
    header = re.search(r"<mxfile[^>]*>", text).group(0)
    with tempfile.TemporaryDirectory() as tmpdir:
        for diagram, stem in zip(diagrams, image_names(src), strict=True):
            page = Path(tmpdir) / f"{stem}.drawio"
            page.write_text(f"{header}\n{diagram}\n</mxfile>\n")
            render(drawio, page, IMAGES / f"{stem}.png")


def twin_export() -> bool:
    """Fallback when draw.io Desktop is absent: screenshot the kit's HTML twin
    (the same layout model the .drawio is emitted from - scripts/design_diagram.py)
    with playwright. Returns False when playwright or a browser is missing."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "drawio_kit"))
    import design_diagram
    import drawio_kit
    from render import shoot

    IMAGES.mkdir(parents=True, exist_ok=True)
    built = design_diagram.build_all(REPO_ROOT)
    print("draw.io Desktop not found - rendering the PNGs from the HTML twin instead")
    with tempfile.TemporaryDirectory() as tmpdir:
        for rel, pages in built.items():
            src = REPO_ROOT / rel
            html = Path(tmpdir) / f"{src.stem}.html"
            drawio_kit.to_html(pages, str(html))
            try:
                shots = shoot(str(html), tmpdir, 2, src.stem)
            except Exception as exc:  # no browser binary on this machine
                print(f"  twin render failed: {exc}")
                return False
            for shot, stem in zip(shots, image_names(src), strict=True):
                out = IMAGES / f"{stem}.png"
                shutil.move(shot, out)
                print(f"  -> {out.relative_to(REPO_ROOT)}")
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Re-export design/*.drawio to PNG.")
    parser.add_argument(
        "--if-available",
        action="store_true",
        help="skip with a note (exit 0) when the draw.io Desktop CLI is not installed",
    )
    args = parser.parse_args(argv)
    drawio = find_drawio()
    if drawio is None:
        if args.if_available:
            if twin_export():
                return
            print(f"skipping the PNG export — {NOT_FOUND}")
            return
        sys.exit(NOT_FOUND)
    sources = sorted(DESIGN.glob("*.drawio"))
    if not sources:
        sys.exit("no design/*.drawio sources found")
    IMAGES.mkdir(parents=True, exist_ok=True)
    print(f"draw.io: {drawio}")
    for src in sources:
        print(src.relative_to(REPO_ROOT))
        export_source(drawio, src)
    print("done -> design/images/")


if __name__ == "__main__":
    main()
