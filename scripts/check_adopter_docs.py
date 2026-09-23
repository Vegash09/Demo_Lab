#!/usr/bin/env python3
"""Fail if a GENERATED adopter repo carries template identity or dangling references.

The scaffold rewrites AGENTS.md, the Makefile and the bundle files, and CI has
long asserted those four are clean. Everything else an adopter reads was
unguarded — and had quietly drifted: `docs/AGENT_MCP.md` told a new customer to
`databricks auth login` against the TEMPLATE's workspace and to check the
template's SQL warehouse; `docs/NAMING.md` documented `sales_landing_path` and
`DATALAB_SALES_LANDING_PATH`, variables that do not exist in an adopter;
`docs/GETTING_STARTED.md` said "copy `projects/customer_sales/...`" from a
folder the scaffold deletes; `.cursor/rules/project.mdc` (auto-attached to every
Cursor edit) described the `projects/` layout as fact.

Since adopters choose their coding agents and components, "the files the
conversion deletes" is no longer a fixed list — a repo without `docs/` must not
link into it, one without Codex must not tell the agent about `.codex/`. So the
layout check is general: a path (or `make` target) that EXISTS IN THE TEMPLATE
but NOT in the adopter is a dangling reference.

Four classes of finding, because they need different escapes:

* **workspace identity** — the template's host, CLI profile, SQL warehouse and
  deploy service principal. Flagged unless THIS repo declares the same value in
  its own targets/, MCP config or bootstrap script: standing a second repo up in
  the same Databricks workspace is legitimate, and only an *unsubstituted* value
  is a leak.
* **identity with no adopter form** — the template's review team (a team in
  another org makes CODEOWNERS invalid) and its SECOND domain's bundle variables
  (`sales_*`, `DATALAB_SALES*`). No escape hatch.
* **layout** — `projects/`, `omnigent`, `customer_sales` (and `design/`, `make
  design` when the adopter has no design package): template material, in any
  checked file.
* **dangling references** (Markdown) — a repo path under a template directory
  (`docs/…`, `.cursor/…`, `scripts/….py`, …) or a `make` target the template
  has and the adopter does not.

Layout and dangling references are allowed where the surrounding paragraph
names the *template repo* or the *framework repo* (or links into them), so
worked examples can still be cited by address. Attribution is checked per
PARAGRAPH (a blank-line-separated block; a fenced code block counts as one) —
prose wraps, and a line-scoped grep forced awkward rewrites.

This checker is template-only tooling: it runs FROM the template against a
generated repo. The scaffold runs it on every adopter before writing it, and
the CI smoke test runs it on each generated profile:

    make check-adopter-docs ADOPTER=<dir>

Without ADOPTER it checks the current directory, and no-ops in the template
itself (a `projects/` directory at the root).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

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

# Allowed where the paragraph points at the repo the material lives in.
ATTRIBUTIONS = (
    "template repo",
    "framework repo",
    "github.com/dediggibyte/datalab/",
    "github.com/dediggibyte/datalab-framework",
)

# What an adopter actually reads. `scripts/*.py` is excluded on purpose: tools
# name paths in constants and regexes; scripts/README.md is the prose index.
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
    "design/*.md",
    "scripts/README.md",
    "variables/*.yml",
    "targets/*.yml",
    "resources/*.yml",
    ".cursor/rules/*.mdc",
    ".cursor/mcp.json",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/*.yml",
    ".github/actions/*/action.yml",
    ".agents/skills/*/SKILL.md",
    ".agents/skills/*/references/*.md",
    # .claude/skills is a byte-identical copy of .agents/skills (check-skills).
)

MARKDOWN = (".md", ".mdc")

# Repo paths under a directory the template has — the only kind that can
# dangle. The lookbehind skips URLs, other paths' tails and regexes (`^docs/…`,
# `\.claude/…` in the protected-file table).
PATH_TOKEN = re.compile(
    r"(?<![\w./\\^-])(?:\.\./)*"
    r"((?:\.agents|\.claude|\.cursor|\.codex|\.githooks|\.github|docs|design|schemas|"
    r"scripts|sample_data)/[\w./*<>{}@-]*"
    r"|CLAUDE\.md|\.mcp\.json|\.gitattributes)"
)
# `make <target> [<target> …]` in a code span, or a code-block line.
MAKE_SPAN = re.compile(r"`make\s+([^`]*)`")
MAKE_LINE = re.compile(r"^\s*make\s+(.*)$", re.M)
# Produced by a command, not committed — present as soon as its parent is.
GENERATED = ("design/images/",)


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


def makefile_targets(root: Path) -> set[str]:
    path = root / "Makefile"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return set(re.findall(r"^([A-Za-z][\w-]*):(?!=)", text, re.M))


def template_paths(template_root: Path) -> set[str]:
    """Every tracked template file plus each of its parent directories (with a
    trailing slash) — the universe of paths an adopter reference can dangle
    from. Tracked-only, so a developer's gitignored files never count."""
    out = subprocess.run(
        ["git", "-C", str(template_root), "ls-files", "-z"],
        capture_output=True, text=True, check=False,
    ).stdout
    paths: set[str] = set()
    for rel in filter(None, out.split("\0")):
        paths.add(rel)
        parts = rel.split("/")
        for i in range(1, len(parts)):
            paths.add("/".join(parts[:i]) + "/")
    return paths


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


def _make_targets_in(block: str) -> set[str]:
    found: set[str] = set()
    for args in [*MAKE_SPAN.findall(block), *MAKE_LINE.findall(block)]:
        for word in args.split():
            if word.startswith("#") or word in ("&&", "||", ";", "\\", "|"):
                break
            if "=" not in word and not word.startswith("-"):
                found.add(word.strip("`.,;:)"))
    return found


class Checker:
    def __init__(self, root: Path, template_root: Path, template_files: set[str] | None = None):
        self.root = root
        self.template = template_files if template_files is not None else template_paths(template_root)
        self.adopter_targets = makefile_targets(root)
        self.template_targets = makefile_targets(template_root)
        declared = configured_identity(root)
        self.identity = dict(IDENTITY)
        self.shared: list[str] = []
        for token, what in WORKSPACE_IDENTITY.items():
            if token in declared:
                self.shared.append(token)
            else:
                self.identity[token] = what
        # Markdown gets the general dangling-reference check below; other files
        # (Makefile, workflows, bundle YAML) keep the fixed layout tokens.
        self.layout = ("projects/", "omnigent", "customer_sales")
        self.layout_non_md = () if (root / "design").is_dir() else ("design/", "make design")

    def _dangles(self, token: str) -> bool:
        """Does a path token name template material this repo lacks?"""
        token = token.rstrip(".,;:)`'\"")
        cut = re.search(r"[<*{]", token)
        if cut:  # a placeholder: check the directory it lives in
            token = token[: cut.start()]
            token = token if token.endswith("/") else token.rsplit("/", 1)[0] + "/"
        if not token.strip("/"):
            return False
        if token not in self.template and token.rstrip("/") + "/" not in self.template:
            return False  # generic or placeholder path — not template material
        if any(token.startswith(g) for g in GENERATED) and (self.root / token.split("/")[0]).is_dir():
            return False
        return not (self.root / token.rstrip("/")).exists()

    def check_file(self, path: Path, rel: str) -> list[str]:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return []
        problems: list[str] = []
        markdown = path.suffix in MARKDOWN
        for line_no, block in units(text):
            for token, what in self.identity.items():
                if token not in block:
                    continue
                remedy = (
                    "this repo does not declare that value anywhere, so it was left "
                    "UNSUBSTITUTED"
                    if token in WORKSPACE_IDENTITY
                    else "there is no valid adopter form of this"
                )
                problems.append(
                    f"{rel}:{line_no}: {token!r} — {what}. {remedy}; add or extend the "
                    f"substitution in scripts/scaffold_adopter.py."
                )
            if any(a in block for a in ATTRIBUTIONS):
                continue
            for token in self.layout + (() if markdown else self.layout_non_md):
                if token in block:
                    problems.append(
                        f"{rel}:{line_no}: {token!r} — template material this repo does not "
                        "have. Say it lives in the template repo (the paragraph must contain "
                        '"template repo"), fence it with an adopter-if / template-only '
                        "marker, or rewrite it for the adopter layout."
                    )
            if not markdown:
                continue
            for token in sorted(set(PATH_TOKEN.findall(block))):
                if self._dangles(token):
                    problems.append(
                        f"{rel}:{line_no}: {token!r} — this repo has no such path (a component "
                        "it did not choose, or template-only material). Fence the passage "
                        "with <!-- adopter-if:<feature> start/end -->, attribute it to the "
                        "template repo, or rewrite it."
                    )
            for target in sorted(_make_targets_in(block)):
                if target in self.template_targets and target not in self.adopter_targets:
                    problems.append(
                        f"{rel}:{line_no}: `make {target}` — this repo's Makefile has no such "
                        "target (its section was dropped with a component). Fence the passage "
                        "with an adopter-if marker, or attribute it to the template repo."
                    )
        return problems


def collect_problems(
    root: Path, template_root: Path = REPO_ROOT, template_files: set[str] | None = None
) -> list[str]:
    """Every finding for the adopter at `root` (the scaffold calls this on its
    staged output before writing anything)."""
    checker = Checker(root.resolve(), template_root.resolve(), template_files)
    problems: list[str] = []
    for pattern in CHECKED_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                problems.extend(checker.check_file(path, path.relative_to(root).as_posix()))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=".", help="generated adopter repo to check (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if (root / "projects").is_dir():
        print(
            "check-adopter-docs: this is the multi-domain template repo "
            "(projects/ exists) — its template references are legitimate, skipping. "
            "Point it at a generated adopter: make check-adopter-docs ADOPTER=<dir>."
        )
        return 0

    problems = collect_problems(root)
    checked = sum(1 for pattern in CHECKED_GLOBS for p in root.glob(pattern) if p.is_file())
    if problems:
        print(
            "check-adopter-docs: this generated adopter repo still carries the datalab "
            "template's identity, or points at material it does not have.\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s) across {checked} files.", file=sys.stderr)
        return 1

    shared = [t for t in WORKSPACE_IDENTITY if t in configured_identity(root)]
    note = (
        f" (this repo shares {', '.join(shared)} with the template, so those are"
        " treated as its own)"
        if shared
        else ""
    )
    print(
        f"adopter docs carry no template identity and no dangling references "
        f"({checked} files checked){note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
