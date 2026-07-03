"""Rewrite the framework version pin at every functional site — one command.

Edits, anchor-guarded (fails loudly if a site's shape changed rather than
silently skipping it):

    pyproject.toml            [tool.uv.sources].datalab  tag = "vX.Y.Z"
    variables/medallion.yml   datalab_version default "X.Y.Z"

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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


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

    print(f"pinned framework v{version} in pyproject.toml + variables/medallion.yml")
    print("next (make bump-framework runs these): uv lock && uv sync && "
          "python scripts/sync_schemas.py --write && python scripts/check_lockstep.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
