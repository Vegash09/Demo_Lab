#!/usr/bin/env python3
"""Fail if a GENERATED adopter repo still carries the template's identity or layout.

The scaffold rewrites AGENTS.md, the Makefile and the bundle files, and CI has
long asserted those four are clean. Everything else an adopter reads was
unguarded — and had quietly drifted: `docs/AGENT_MCP.md` told a new customer to
`databricks auth login` against the TEMPLATE's workspace and to check the
template's SQL warehouse; `docs/NAMING.md` documented `sales_landing_path` and
`DATALAB_SALES_LANDING_PATH`, variables that do not exist in an adopter;
`docs/GETTING_STARTED.md` said "copy `projects/customer_sales/...`" from a
folder the scaffold deletes; `.cursor/rules/project.mdc` (auto-attached to every
Cursor edit) described the `projects/` layout as fact.

Three classes of finding, because they need different escapes:

* **workspace identity** — the template's host, CLI profile, SQL warehouse and
  deploy service principal. Flagged unless THIS repo declares the same value in
  its own targets/, MCP config or bootstrap script: standing a second repo up in
  the same Databricks workspace is legitimate, and only an *unsubstituted* value
  is a leak.
* **identity with no adopter form** — the template's review team (a team in
  another org makes CODEOWNERS invalid) and its SECOND domain's bundle variables
  (`sales_*`, `DATALAB_SALES*`). No escape hatch.
* **layout** — `projects/`, `design/`, `omnigent`, `make design`: material the
  conversion deletes. Allowed only where the surrounding paragraph names the
  *template repo*, so worked examples can still be cited by address.

Attribution is checked per PARAGRAPH (a blank-line-separated block; a fenced
code block counts as one), not per line — prose wraps, and a line-by-line grep
forced awkward rewrites to keep "template repo" on the offending line itself.

Runs against the repo it is invoked in. In the template repo itself every hit
is legitimate, so it detects that (a `projects/` directory at the root) and
skips.

    make check-adopter-docs
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The template's own workspace identity. Each entry is a leak UNLESS the adopter
# genuinely configured the same value — standing a second repo up in the SAME
# Databricks workspace is legitimate — so these are filtered against what this
# repo actually declares (see configured_identity).
WORKSPACE_IDENTITY = {
    "diggi_dev_aws": "the template's Databricks CLI profile",
    "c1cdbe2406e5cf04": "the template's SQL warehouse id",
    "dbc-425be768-f138": "the template's Databricks workspace host",
    "437346a1-0b53-418a-80d4-abaf2586ed97": "the template's CI/CD deploy service principal",
}

# No legitimate adopter form: a review team in another org, and the template's
# SECOND reference domain's bundle variables (an adopter has one domain, and
# patch_cd renames the CD plumbing). Kept in sync with scaffold_adopter.py.
IDENTITY = {
    "dediggibyte/datalab-approvers": "the template's code-review team",
    "sales_datalab_wheel": "the template's second-domain framework wheel variable",
    "sales_landing_path": "the template's second-domain landing-path variable",
    "sales_export_path": "the template's second-domain export-path variable",
    "sales_catalog": "the template's second-domain catalog variable",
    "DATALAB_SALES": "the template's second-domain GitHub variable",
}


def configured_identity(root: Path) -> str:
    """This repo's OWN declared workspace identity, as one searchable blob.

    Read from the files the scaffold writes or patches: the per-target hosts,
    the MCP grounding config (CLI profile + SQL warehouse) and the bootstrap
    deploy SP. A template value that matches one of these was CHOSEN, not
    leaked — an adopter may deliberately share the template's workspace."""
    blob: list[str] = []
    for rel in (
        "targets/dev.yml",
        "targets/stage.yml",
        "targets/prod.yml",
        ".mcp.json",
        ".cursor/mcp.json",
        "scripts/bootstrap_uc.py",
    ):
        path = root / rel
        if path.is_file():
            try:
                blob.append(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                pass
    return "\n".join(blob)


# Deleted by the conversion. Allowed when the paragraph names the template repo.
LAYOUT = ("projects/", "design/", "omnigent", "make design")
ATTRIBUTION = "template repo"

# What an adopter actually reads. `scripts/` is excluded on purpose: the scaffold
# engine and this checker legitimately name the template in constants, and the
# bootstrap-adopter-repo skill's whole job is describing the conversion.
CHECKED_GLOBS = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "CHANGELOG.md",
    "Makefile",
    "databricks.yml",
    "rbac.yml",
    ".databricksignore",
    ".mcp.json",
    "docs/*.md",
    "variables/*.yml",
    "targets/*.yml",
    "resources/*.yml",
    ".cursor/rules/*.mdc",
    ".cursor/mcp.json",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/workflows/*.yml",
    ".github/actions/*/action.yml",
    ".agents/skills/*/SKILL.md",
    ".claude/skills/*/SKILL.md",
)

# The conversion is this skill's subject matter — it must name the template.
EXCLUDE_SUBSTRINGS = ("skills/bootstrap-adopter-repo/",)


def units(text: str) -> list[tuple[int, str]]:
    """Split into (first-line-number, block) units: blank-line-separated
    paragraphs, with each fenced code block kept whole."""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 1
    fence: str | None = None
    for n, line in enumerate(lines, 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence is None and marker:
            if buf:
                out.append((start, "\n".join(buf)))
                buf = []
            fence, start = marker.group(1), n
            buf.append(line)
            continue
        if fence is not None:
            buf.append(line)
            if marker and marker.group(1).startswith(fence):
                out.append((start, "\n".join(buf)))
                buf, fence = [], None
            continue
        if not line.strip():
            if buf:
                out.append((start, "\n".join(buf)))
                buf = []
            continue
        if not buf:
            start = n
        buf.append(line)
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def check_file(
    path: Path, rel: str, identity: dict[str, str], workspace: set[str]
) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    problems: list[str] = []
    for line_no, block in units(text):
        attributed = ATTRIBUTION in block
        for token, what in identity.items():
            if token not in block:
                continue
            remedy = (
                "this repo does not declare that value anywhere, so it was left "
                "UNSUBSTITUTED"
                if token in workspace
                else "there is no valid adopter form of this"
            )
            problems.append(
                f"{rel}:{line_no}: {token!r} — {what}. {remedy}; add or extend the "
                f"substitution in scripts/scaffold_adopter.py."
            )
        if attributed:
            continue
        for token in LAYOUT:
            if token in block:
                problems.append(
                    f"{rel}:{line_no}: {token!r} — deleted by the conversion. Either "
                    f"say it lives in the template repo (the paragraph must contain "
                    f'"{ATTRIBUTION}"), fence it '
                    f"<!-- template-only:<name> start/end --> and swap it in "
                    f"scaffold_adopter.py's DOC_REGIONS, or rewrite it for the "
                    f"root-level layout."
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo to check (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if (root / "projects").is_dir():
        print(
            "check-adopter-docs: this is the multi-domain template repo "
            "(projects/ exists) — its template references are legitimate, skipping. "
            "The generated adopter is checked by the scaffold smoke test."
        )
        return 0

    # A template workspace value this repo genuinely configured for itself is
    # not a leak — only an UNsubstituted one is.
    declared = configured_identity(root)
    identity = dict(IDENTITY)
    shared = []
    for token, what in WORKSPACE_IDENTITY.items():
        if token in declared:
            shared.append(token)
        else:
            identity[token] = what

    problems: list[str] = []
    checked = 0
    for pattern in CHECKED_GLOBS:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or any(x in rel for x in EXCLUDE_SUBSTRINGS):
                continue
            checked += 1
            problems.extend(check_file(path, rel, identity, set(WORKSPACE_IDENTITY)))

    if problems:
        print(
            "check-adopter-docs: this generated adopter repo still carries the "
            "datalab template's identity or layout.\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s) across {checked} files.", file=sys.stderr)
        return 1

    note = (
        f" (this repo shares {', '.join(shared)} with the template, so those are"
        " treated as its own)"
        if shared
        else ""
    )
    print(
        f"adopter docs carry no template identity or layout "
        f"({checked} files checked){note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
