#!/usr/bin/env python3
"""Assert the COMMITTED agent-harness configs are machine-independent.

`.claude/settings.json`, `.cursor/hooks.json` and `.codex/hooks.json` are
tracked, shared with every developer, and copied verbatim into every generated
adopter repo. So anything machine-specific in them is wrong twice: it does
nothing on a teammate's laptop, and it leaks the author's local paths into a
customer's repository.

That is exactly what happened. Claude Code appends "always allow" grants to a
settings file, and a run of them landed in the TRACKED `.claude/settings.json`
instead of the gitignored local one:

    Bash(/Users/<someone>/datalab/.venv/bin/python /private/tmp/claude-502/<dead
    session id>/scratchpad/acme-datalab/scripts/bootstrap_uc.py --target dev)

alongside one-shot session noise (`Bash(exit 1)`, `Bash(awk -F: '$1<200')`).
None of it can ever match on another machine.

The split this enforces:

* `.claude/settings.json` (tracked)      — the hooks that enforce repo policy,
  plus READ-ONLY verification grants that mean the same thing on any machine.
* `.claude/settings.local.json` (ignored) — everything personal or
  machine-specific: absolute paths, scratch dirs, and any command that WRITES.

Checks run per tracked file:

1. no home-directory or temp/scratch absolute path anywhere in the file;
2. hook commands locate their scripts through `$CLAUDE_PROJECT_DIR` or a
   repo-relative path, never an absolute one;
3. every path a hook command references actually exists in the repo, so a
   renamed guard script fails here instead of silently never running;
4. every `permissions.allow` grant is a READ-ONLY `make` verification target.
   The first three checks let a portable WRITE grant through — and one did:
   `Bash(PROTECTED_EDIT_OK=1 git commit …)` (a commit that skips the
   protected-files guard) sat in the tracked file, shipping to every adopter,
   while the commit that "moved the write grants to the local file" said
   otherwise.

    make check-agent-settings      # CI + pre-commit
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

TRACKED_CONFIGS = (
    ".claude/settings.json",
    ".cursor/hooks.json",
    ".codex/hooks.json",
)

LOCAL_FILE = ".claude/settings.local.json"

# Absolute paths that are meaningful on exactly one machine. Windows drive
# paths are included so a Windows-authored grant fails the same way.
MACHINE_PATHS = (
    (r"/Users/[^/\s\"']+", "a macOS home directory"),
    (r"/home/[^/\s\"']+", "a Linux home directory"),
    (r"[A-Za-z]:\\\\?Users", "a Windows home directory"),
    (r"/private/tmp/claude-\d+", "a Claude Code session scratch directory"),
    (r"/tmp/claude-\d+", "a Claude Code session scratch directory"),
    (r"/var/folders/", "a macOS per-session temp directory"),
)

# A hook command may name a script; these are the forms that travel.
PORTABLE_PREFIXES = ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/")

# The only grants a TRACKED allow-list may carry: read-only verification `make`
# targets that mean the same thing on every machine (optionally with trailing
# arguments). Anything else — commits, deploys, shell one-offs — is personal.
READ_ONLY_GRANT = re.compile(
    r"^Bash\(make (help|lint|test|validate|validate-configs|dry-run-local|run-local"
    r"|check-[a-z-]+)( \*)?\)$"
)

# Repo-relative script path inside a hook command, e.g. ".cursor/hooks/x.py"
SCRIPT_RE = re.compile(r"(?:\$\{?CLAUDE_PROJECT_DIR\}?/)?((?:\.[\w-]+/)[\w./-]+\.py)")


def walk_strings(node, path="$"):
    """Yield (json-path, string) for every string in a JSON document."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from walk_strings(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, f"{path}.{key}")


def check_config(rel: str) -> list[str]:
    path = REPO_ROOT / rel
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [
            f"{rel}: invalid JSON ({exc}). A malformed settings file silently "
            f"disables EVERY setting in it, hooks included."
        ]

    problems: list[str] = []

    # 1. No machine-specific absolute path, anywhere.
    for where, text in walk_strings(data):
        for pattern, what in MACHINE_PATHS:
            match = re.search(pattern, text)
            if match:
                problems.append(
                    f"{rel} at {where}: {match.group(0)!r} is {what}. This is a "
                    f"TRACKED file — it is shared with every developer and copied "
                    f"into every generated adopter repo, so a path from one machine "
                    f"can never match on another. Move this entry to {LOCAL_FILE} "
                    f"(gitignored, per-machine)."
                )
                break

    # 4. The tracked allow-list holds read-only verification grants only.
    allow = (data.get("permissions") or {}).get("allow") or [] if isinstance(data, dict) else []
    for i, grant in enumerate(allow):
        if isinstance(grant, str) and not READ_ONLY_GRANT.match(grant):
            problems.append(
                f"{rel} at $.permissions.allow[{i}]: {grant!r} is not a read-only `make` "
                f"verification grant. A TRACKED allow-list is shared with every developer "
                f"and copied into adopter repos; keep only `Bash(make help|lint|test|"
                f"validate-configs|check-*…)` here and move this one to {LOCAL_FILE}."
            )

    # 2 + 3. Hook commands must resolve portably, and to a file that exists.
    for where, text in walk_strings(data):
        if not where.endswith(".command"):
            continue
        for script in SCRIPT_RE.findall(text):
            if not (REPO_ROOT / script).exists():
                problems.append(
                    f"{rel} at {where}: references {script!r}, which does not exist. "
                    f"A hook pointing at a missing script never runs and never "
                    f"reports why — the policy it enforces is silently off."
                )
        if re.search(r'(?:^|["\s])/(?:Users|home|private|tmp|var)/', text):
            problems.append(
                f"{rel} at {where}: hook command uses an absolute path. Locate the "
                f"script through $CLAUDE_PROJECT_DIR instead, e.g. "
                f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/<script>.py".'
            )

    return problems


def main() -> int:
    problems: list[str] = []
    checked = []
    for rel in TRACKED_CONFIGS:
        if (REPO_ROOT / rel).exists():
            checked.append(rel)
            problems.extend(check_config(rel))

    if problems:
        print(
            "check-agent-settings: a committed agent-harness config carries something "
            "personal, machine-specific or broken.\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        print(
            f"Per-developer grants belong in {LOCAL_FILE}, which is gitignored and "
            "overrides the tracked file (settings load user -> project -> local).",
            file=sys.stderr,
        )
        return 1

    print(f"committed agent configs are machine-independent ({len(checked)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
