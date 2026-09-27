#!/usr/bin/env python3
"""MANDATORY guard: the design/ diagrams are generated, never hand-edited.

`design/*.drawio` and `design/images/*.png` are build outputs of
`scripts/design_diagram.py` (the estate pages) and `scripts/design_spec.py`
(the conceptual spec), laid out through the vendored drawio-architecture-designer
kit (`scripts/drawio_kit/`). Hand-edited XML is how the old implementation map
ended up with arrows through cards, clipped labels and a second domain bolted
onto the bottom, so an agent may not write those files directly - it changes
the SOURCE and runs `make design`. `make check-design` (CI + pre-commit) is the
backstop: it regenerates the files and fails on any drift or layout finding.

Wired for every harness, one script, the cross-harness deny contract (exit 2 +
reason on stderr) - the same as `.cursor/hooks/branch_guard.py`:

  * Claude Code - PreToolUse (Edit/Write/MultiEdit + Bash) in .claude/settings.json
  * Codex       - PreToolUse in .codex/hooks.json
  * Cursor      - preToolUse (edit tools) + beforeShellExecution in .cursor/hooks.json

It lives beside branch_guard.py so every hooked harness ships it (the scaffold
keeps it only in adopters that chose the `design` component).

A shell command is denied when it names a generated design file AND writes to
it (sed -i, perl -i, a redirect, tee, cp/mv onto it, an inline python/node
write) - unless it is the generator itself (make design, design_diagram.py,
export_design.py). Anything it cannot parse passes: the CI gate still holds.
"""
from __future__ import annotations

import json
import re
import sys

GEN = r"""['"]?(?:\./)?design/(?:[^\s'";|&]*\.drawio|images/[^\s'";|&]*\.png)['"]?"""
GENERATED_PATH = re.compile(r"(^|/)design/([^/]+\.drawio|images/[^/]+\.png)$")
GENERATOR = re.compile(r"\bmake\s+(design|check-design|design-preview)\b|design_diagram\.py|export_design\.py")
# a write whose TARGET is a generated file (reading one - grep, cat, diff - passes)
WRITES_GEN = [
    re.compile(r">>?\s*" + GEN),                                    # redirect onto it
    re.compile(r"\btee\s+(?:-a\s+)?" + GEN),                        # tee into it
    re.compile(r"\b(?:sed|perl)\s+[^|;&]*-[a-zA-Z]*i[^|;&]*" + GEN),  # in-place edit
    re.compile(r"\b(?:cp|mv|install|rsync|ln)\s+[^|;&]*\s" + GEN + r"\s*(?:$|[;&|])"),  # dest
    re.compile(r"\b(?:python3?|node|ruby)\b[^|;&]*" + GEN + r"[^|;&]*(?:['\"][wa]b?['\"]|write_text|write_bytes|writeFile)"),
    re.compile(r"\b(?:python3?|node|ruby)\b[^|;&]*(?:['\"][wa]b?['\"]|write_text|write_bytes|writeFile)[^|;&]*" + GEN),
]

GUIDE = """BLOCKED - {what} is GENERATED, never edited by hand.

The design/ diagrams are build outputs of the drawio-architecture-designer
method (.agents/skills/drawio-architecture-designer + the maintain-design-diagram
skill). Change the SOURCE, then regenerate:

  * the estate (tables, pipelines, jobs)  -> config/, resources/*.yml
  * systems / consumers / job reads-writes -> design/estate.yml
  * layout or look of the estate pages     -> scripts/design_diagram.py
  * the conceptual spec text or layout     -> scripts/design_spec.py

  make design            # regenerate .drawio + PNGs (+ PIPELINES.md)
  make design-preview    # HTML twin + PNGs to LOOK at before committing
  make check-design      # what CI runs: stale, hand-edited or unclean fails
"""


def _deny(what: str) -> None:
    sys.stderr.write(GUIDE.format(what=what))
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}

    command = payload.get("command") or tool_input.get("command") or ""
    if command:
        if not GENERATOR.search(command) and any(r.search(command) for r in WRITES_GEN):
            _deny("a design/*.drawio or design/images/*.png file")
        sys.exit(0)

    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or payload.get("file_path")
        or ""
    )
    if file_path and GENERATED_PATH.search(str(file_path).replace("\\", "/")):
        _deny(str(file_path))
    sys.exit(0)


if __name__ == "__main__":
    main()
