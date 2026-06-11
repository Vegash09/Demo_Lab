#!/usr/bin/env python3
"""MANDATORY branch-first guard: no agent changes while `main` is checked out.

Repo policy (AGENTS.md "Branching & releases"): every change starts from a
fresh `feature/...`, `fix/...` or `debug/...` branch cut from `main` — work
is NEVER done on `main` directly. This hook turns that prose into an
enforced invariant for BOTH agent harnesses:

  * Cursor      — `preToolUse` (file-edit tools) and `beforeShellExecution`
                  in `.cursor/hooks.json`.
  * Claude Code — `PreToolUse` (Edit/Write/MultiEdit/NotebookEdit + Bash)
                  in `.claude/settings.json`.

Blocking mechanism: exit code 2 with the reason on stderr — the documented
cross-harness "deny" contract (Cursor and Claude Code both honor it), so one
script needs no per-harness JSON output and can never mis-detect the caller.

What is denied while HEAD is `main`/`master`:
  * any file-edit tool call (create your branch first — uncommitted edits
    carry over with `git switch -c`);
  * shell `git commit`, `git merge`, `git rebase`, `git cherry-pick`,
    `git revert`;
  * shell `git push` that would update main (bare `git push` on main, or an
    explicit main/master/HEAD refspec).

Everything else stays allowed — in particular `git pull` on main, `git
switch`/`checkout -b` (the fix this guard demands), and release tagging
(`git tag`, `git push origin v1.2.3`, `git push --tags`), which legitimately
happens on main.

The human-side counterpart lives in `.githooks/pre-commit` (blocks commits
on main). Failures fail open: a broken guard must never brick the session —
GitHub branch protection / PR review remain the backstop.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROTECTED_BRANCHES = {"main", "master"}

# `git` followed (after optional global flags like `-C <dir>`/`-c k=v`) by a
# history-mutating subcommand. Anchoring the subcommand right after `git`
# keeps read-only uses (`git log --grep merge`) out of the blast radius.
_GIT = r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?\S+)*\s+"
_COMMIT_LIKE = re.compile(_GIT + r"(commit|merge|rebase|cherry-pick|revert)\b")
_PUSH = re.compile(_GIT + r"push\b(?P<rest>[^|;&]*)")
_MAIN_REF = re.compile(r"^(main|master|HEAD)(:.*)?$|^[^:]*:(main|master)$")

_GUIDE = """BLOCKED — the repo is on '{branch}', and changes on {branch} are forbidden.

datalab policy (AGENTS.md "Branching & releases", enforced for every agent
session): EVERY change starts from a fresh branch cut from main —
feature/<slug>, fix/<slug>, or debug/<slug> depending on the work.

Do this first, then retry the blocked action:

    git switch main && git pull          # sync (skip if already current)
    git switch -c <feature|fix|debug>/<slug>

Uncommitted edits carry over to the new branch automatically. Open one PR
per branch with the unified template; merging via GitHub deletes the head
branch. Never commit or push to main directly — main only moves via PRs."""


def _branch(repo_dir: str) -> str | None:
    # symbolic-ref (not rev-parse --abbrev-ref) so an UNBORN branch — a repo
    # before its first commit — still reports main; detached HEAD returns None.
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _push_updates_main(command: str) -> bool:
    m = _PUSH.search(command)
    if m is None:
        return False
    rest = m.group("rest").split()
    if any(_MAIN_REF.fullmatch(tok) for tok in rest):
        return True  # explicit main/master/HEAD refspec (either side of `:`)
    if "--tags" in rest or "--follow-tags" in rest:
        return False  # tag-only push — the release flow, legitimate from main
    args = [tok for tok in rest if not tok.startswith("-")]
    # `git push` / `git push <remote>` push the CURRENT branch — i.e. main.
    return len(args) <= 1


def _deny(branch: str) -> None:
    sys.stderr.write(_GUIDE.format(branch=branch))
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    repo_dir = (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("CURSOR_PROJECT_DIR")
        or os.getcwd()
    )
    branch = _branch(repo_dir)
    if branch not in PROTECTED_BRANCHES:
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}

    # Shell command events (Cursor beforeShellExecution / Claude Bash).
    command = payload.get("command") or tool_input.get("command") or ""
    if command:
        if _COMMIT_LIKE.search(command) or _push_updates_main(command):
            _deny(branch)
        sys.exit(0)

    # File-edit events (Cursor preToolUse on edit tools / Claude PreToolUse).
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or payload.get("file_path")
    )
    if file_path:
        _deny(branch)

    sys.exit(0)


if __name__ == "__main__":
    main()
