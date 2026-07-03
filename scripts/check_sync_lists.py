"""Assert databricks.yml `sync.exclude` and .databricksignore stay aligned.

Two exclusion lists exist because two different tools read them: `bundle deploy`
honors ONLY `sync.exclude` in databricks.yml, while `databricks sync` and the
IDE extension honor ONLY `.databricksignore`. Both are meant to exclude the same
dev-only surfaces, and both files carry a "keep aligned" comment — this check
makes CI enforce it instead (divergence silently deploys, or drops, files).

Comparison is on normalized entries (trailing `/` stripped; comments/blank
lines ignored). Needs pyyaml (dev venv):

    make check-sync-lists
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def bundle_excludes() -> set[str]:
    data = yaml.safe_load((REPO_ROOT / "databricks.yml").read_text())
    return {entry.rstrip("/") for entry in (data.get("sync", {}).get("exclude") or [])}


def ignore_entries() -> set[str]:
    entries = set()
    for line in (REPO_ROOT / ".databricksignore").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line.rstrip("/"))
    return entries


def main() -> int:
    bundle = bundle_excludes()
    ignore = ignore_entries()
    problems = [
        f"in databricks.yml sync.exclude but not .databricksignore: {entry}"
        for entry in sorted(bundle - ignore)
    ] + [
        f"in .databricksignore but not databricks.yml sync.exclude: {entry}"
        for entry in sorted(ignore - bundle)
    ]
    if problems:
        print("the two deploy-exclusion lists have DIVERGED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nadd the entry to the other list (or remove it from both): "
            "databricks.yml `sync.exclude` drives `bundle deploy`, "
            ".databricksignore drives `databricks sync`/the IDE extension.",
            file=sys.stderr,
        )
        return 1
    print(f"sync.exclude and .databricksignore are aligned ({len(bundle)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
