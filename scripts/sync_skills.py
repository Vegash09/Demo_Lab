"""Mirror the canonical agent-skills tree into the Claude Code copy.

datalab ships ONE authored skills source — `.agents/skills/` (the cross-tool
`agentskills.io` standard location, read natively by Cursor and Codex). Claude
Code discovers skills only at `.claude/skills/` and does not reliably follow
symlinked skills, so a byte-identical copy is GENERATED there from canonical
rather than hand-maintained. (Databricks Genie loads the same skills from the
Workspace `.assistant/skills/` — published out-of-band by
`scripts/publish_genie_skills.py`, not mirrored here.)

    make sync-skills    # uv run python scripts/sync_skills.py --write
    make check-skills   # uv run python scripts/sync_skills.py --check  (CI + pre-commit)

`--write` makes the mirror an exact copy of canonical (add/update/delete).
`--check` is read-only: it asserts the mirror matches canonical byte-for-byte
and exits non-zero (listing the drift) otherwise. Stdlib only — runs with or
without the project venv.
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / ".agents" / "skills"
MIRRORS = (REPO_ROOT / ".claude" / "skills",)


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _files(root: Path) -> set[str]:
    """Every file under root, as paths relative to root (posix)."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def check() -> list[str]:
    """Return drift messages; an empty list means every mirror is in sync."""
    problems: list[str] = []
    canonical_files = _files(CANONICAL)
    for mirror in MIRRORS:
        if not mirror.is_dir():
            problems.append(f"{_rel(mirror)} is missing entirely")
            continue
        mirror_files = _files(mirror)
        for missing in sorted(canonical_files - mirror_files):
            problems.append(f"{_rel(mirror)}: missing {missing}")
        for extra in sorted(mirror_files - canonical_files):
            problems.append(f"{_rel(mirror)}: unexpected {extra}")
        for shared in sorted(canonical_files & mirror_files):
            if not filecmp.cmp(CANONICAL / shared, mirror / shared, shallow=False):
                problems.append(f"{_rel(mirror)}: {shared} differs from canonical")
    return problems


def write() -> None:
    """Make every mirror an exact copy of the canonical tree."""
    for mirror in MIRRORS:
        if mirror.exists():
            shutil.rmtree(mirror)
        shutil.copytree(CANONICAL, mirror)
        print(f"synced {_rel(mirror)} <- {_rel(CANONICAL)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync agent-skill mirrors.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate mirrors")
    mode.add_argument("--check", action="store_true", help="check for drift")
    args = parser.parse_args(argv)

    if not CANONICAL.is_dir():
        print(f"canonical skills dir not found: {_rel(CANONICAL)}", file=sys.stderr)
        return 2

    if args.write:
        write()
        return 0

    problems = check()
    if problems:
        print("agent-skill mirrors are OUT OF SYNC with .agents/skills/:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nrun `make sync-skills` to regenerate them.", file=sys.stderr)
        return 1
    print("agent-skill mirrors are in sync with .agents/skills/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
