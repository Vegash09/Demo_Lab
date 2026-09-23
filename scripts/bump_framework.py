"""Rewrite the framework version pin at every functional site — one command.

Edits, anchor-guarded (fails loudly if a site's shape changed rather than
silently skipping it):

    pyproject.toml            [tool.uv.sources].datalab  tag = "vX.Y.Z"
    variables/medallion.yml   datalab_version default "X.Y.Z"
    every tracked doc/skill   links into the framework repo
                              (github.com/dediggibyte/datalab-framework/blob/<ref>/…)
                              are re-pinned to the tag, so the reference an
                              author follows describes THIS version (it said
                              `main`, which runs ahead of the pin)

The remaining lockstep sites are derived, not edited here: `make bump-framework`
(the caller) chains `uv lock`, `uv sync`, `scripts/sync_schemas.py --write` and
`scripts/check_lockstep.py` after this script. The scheduled framework-bump
workflow drives the same make target when the framework repo publishes a new
release tag.

Stdlib only — runs with `uv run --no-project`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# A link into the framework repo at some ref: .../datalab-framework/blob/<ref>/...
# check_lockstep.py and scaffold_adopter.py import these, so the three agree.
FRAMEWORK_LINK_RE = re.compile(
    r"(github\.com/dediggibyte/datalab-framework/(?:blob|tree)/)([^/\s)\]'\"`<>]+)(/)"
)
LINK_SUFFIXES = {".md", ".mdc", ".py", ".yml", ".yaml", ".toml", ".txt"}
# History records what WAS linked; it is never re-pinned. The gate tests'
# fixtures hold deliberately UNpinned links — data, not references. Workflows
# are never rewritten: the bump bot's GITHUB_TOKEN cannot push a change under
# .github/workflows/ (that needs the `workflows` permission).
LINK_EXCLUDED = {"CHANGELOG.md"}
LINK_EXCLUDED_PREFIXES = ("scripts/tests/", ".github/workflows/")
SKIP_DIRS = {".git", ".venv", "node_modules"}


def is_pinnable_ref(ref: str) -> bool:
    """False for template placeholders / shell or workflow expressions
    (`@@FRAMEWORK_TAG@@`, `$LATEST`, `${{ … }}`), which resolve elsewhere."""
    return not ref.startswith(("$", "@@", "{"))


def _link_candidate(rel: str) -> bool:
    path = Path(rel)
    return (
        path.suffix in LINK_SUFFIXES
        and path.name not in LINK_EXCLUDED
        and not rel.startswith(LINK_EXCLUDED_PREFIXES)
        and not SKIP_DIRS.intersection(path.parts)
    )


def tracked_text_files(root: Path) -> list[Path]:
    """The text files that may link the framework: git's view (tracked plus
    untracked-but-not-ignored, so a fresh `git init` is checked too) inside a
    repo, a filesystem walk outside one — a freshly generated adopter
    (`make new-adopter`) is not a repository yet."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, check=True, capture_output=True, text=True,
        ).stdout
        rels = [rel for rel in out.split("\0") if rel]
    except (subprocess.CalledProcessError, FileNotFoundError):
        rels = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return [root / rel for rel in dict.fromkeys(rels) if _link_candidate(rel) and (root / rel).is_file()]


def pin_framework_links(paths: Iterable[Path], tag: str) -> list[Path]:
    """Re-point every framework-repo link in ``paths`` at ``tag``; returns the
    files changed."""
    changed = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        new = FRAMEWORK_LINK_RE.sub(
            lambda m: m.group(1) + (tag if is_pinnable_ref(m.group(2)) else m.group(2)) + m.group(3),
            text,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed


def require_sub(pattern: str, replacement: str, path: Path) -> None:
    """Apply exactly one regex substitution in path or die — never edit silently."""
    text = path.read_text()
    new_text, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(REPO_ROOT)}: expected exactly 1 match for {pattern!r}, "
            f"found {count} — the file's shape changed; update scripts/bump_framework.py"
        )
    path.write_text(new_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite the datalab framework version pin.")
    parser.add_argument("--version", required=True, help="new framework version, e.g. 0.7.0 (or v0.7.0)")
    args = parser.parse_args(argv)

    version = args.version.lstrip("v")
    if not VERSION_RE.match(version):
        raise SystemExit(f"--version must be a release version like 0.7.0, got {args.version!r}")

    require_sub(
        r'(datalab = \{ git = "https://github\.com/dediggibyte/datalab-framework\.git", tag = ")v[^"]+(" \})',
        rf"\g<1>v{version}\g<2>",
        REPO_ROOT / "pyproject.toml",
    )
    require_sub(
        r'(datalab_version:\n(?:[ \t]+description:.*\n)?[ \t]+default: ")[^"]+(")',
        rf"\g<1>{version}\g<2>",
        REPO_ROOT / "variables" / "medallion.yml",
    )

    relinked = pin_framework_links(tracked_text_files(REPO_ROOT), f"v{version}")
    print(f"pinned framework v{version} in pyproject.toml + variables/medallion.yml")
    print(f"re-pinned framework doc links to v{version} in {len(relinked)} file(s)")
    print("next (make bump-framework runs these): uv lock && uv sync && "
          "python scripts/sync_schemas.py --write && python scripts/check_lockstep.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
