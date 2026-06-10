#!/usr/bin/env python3
"""Enforce the unified PR template when an AI agent runs `gh pr create`.

This ONE script serves two agent harnesses (it auto-detects which one invoked
it from the stdin payload shape):

  * Cursor  — wired as a `beforeShellExecution` hook in `.cursor/hooks.json`.
              Input:  {"command": "<shell command>", ...}
              Output: {"permission": "allow" | "deny", "agent_message": ...,
                       "user_message": ...}

  * Claude Code — wired as a `PreToolUse` (matcher: Bash) hook in
              `.claude/settings.json`.
              Input:  {"tool_name": "Bash", "tool_input": {"command": "..."}}
              Output: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                       "permissionDecision": "allow" | "deny",
                       "permissionDecisionReason": ...}}

Goal: every PR uses the single template `.github/pull_request_template.md`
(which carries the `datalab-pr-template` marker). A `gh pr create` is allowed
only when it routes through that template:

  * `--web` / `-w`                      → browser form is pre-filled with the
                                          template → ALLOW
  * `--template`/`-T <…template…>`      → starts from the template → ALLOW
  * `--body-file`/`-F <file>`           → ALLOW iff the file is the template
                                          itself or its content has the marker
  * `--body`/`-b "<text>"`              → ALLOW iff the text has the marker
  * `--fill` / `-f` / `--fill-first`    → bypasses the template → DENY
  * no body provided                    → DENY (agents must pass the template)

Anything that is not a `gh pr create` is allowed untouched. Failures fail open
(the CI check in .github/workflows/pr-template-check.yml is the backstop).

Keep the MARKER below in sync with `.github/pull_request_template.md` and
`.github/workflows/pr-template-check.yml`.
"""
from __future__ import annotations

import json
import re
import shlex
import sys

MARKER = "datalab-pr-template"
TEMPLATE_PATH_HINT = "pull_request_template.md"

_GUIDE = (
    "UNIFIED PR FORMAT REQUIRED.\n"
    "All PRs must use the single template at .github/pull_request_template.md\n"
    "(it carries the `datalab-pr-template` marker). To open a PR from the CLI:\n\n"
    "  1) Start from the template and fill it in (KEEP the\n"
    "     `<!-- datalab-pr-template: v1 -->` line):\n"
    "       cp .github/pull_request_template.md /tmp/pr-body.md\n"
    "       # edit /tmp/pr-body.md — Summary / Changes / Test plan / Checklist\n"
    "  2) Create the PR with that body:\n"
    "       gh pr create --title \"<title>\" --body-file /tmp/pr-body.md\n\n"
    "  Or open the pre-filled browser form:\n"
    "       gh pr create --web\n\n"
    "CI (.github/workflows/pr-template-check.yml) rejects PRs whose body does\n"
    "not follow this template."
)


def _is_gh_pr_create(command: str) -> bool:
    return re.search(r"\bgh\b\s+pr\s+create\b", command) is not None


def _has_flag(tokens: list[str], *names: str) -> bool:
    return any(t in names for t in tokens)


def _flag_value(tokens: list[str], *names: str) -> str | None:
    for i, t in enumerate(tokens):
        if t in names and i + 1 < len(tokens):
            return tokens[i + 1]
        for n in names:
            if t.startswith(n + "="):
                return t[len(n) + 1 :]
    return None


def evaluate(command: str) -> tuple[str, str]:
    """Return (decision, reason). decision is 'allow' or 'deny'."""
    if not command or not _is_gh_pr_create(command):
        return "allow", ""

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    # Browser form is pre-filled with the template.
    if _has_flag(tokens, "--web", "-w"):
        return "allow", ""

    # `--fill*` builds the body from commits and bypasses the template.
    if _has_flag(tokens, "--fill", "-f", "--fill-first", "--fill-verbose"):
        return "deny", "`--fill` bypasses the unified PR template.\n\n" + _GUIDE

    # `--template/-T` explicitly starts from a template file.
    tmpl = _flag_value(tokens, "--template", "-T")
    if tmpl and TEMPLATE_PATH_HINT in tmpl:
        return "allow", ""

    # `--body-file/-F <path>`
    body_file = _flag_value(tokens, "--body-file", "-F")
    if body_file:
        if TEMPLATE_PATH_HINT in body_file:
            return "allow", ""
        try:
            with open(body_file, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            return "deny", (
                f"Could not read --body-file {body_file!r} to confirm it follows "
                f"the template.\n\n" + _GUIDE
            )
        if MARKER in content:
            return "allow", ""
        return "deny", (
            f"--body-file {body_file!r} does not contain the `datalab-pr-template` "
            f"marker.\n\n" + _GUIDE
        )

    # `--body/-b "<text>"`
    body = _flag_value(tokens, "--body", "-b")
    if body is not None:
        if MARKER in body:
            return "allow", ""
        return "deny", (
            "The --body text does not follow the unified template (missing the "
            "`datalab-pr-template` marker).\n\n" + _GUIDE
        )

    # No body at all — an agent must pass the filled template explicitly.
    return "deny", "No PR body provided.\n\n" + _GUIDE


def _emit_cursor(decision: str, reason: str) -> None:
    if decision == "deny":
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "agent_message": reason,
                    "user_message": (
                        "Blocked: PRs must use the unified template "
                        "(.github/pull_request_template.md)."
                    ),
                }
            )
        )
    else:
        print(json.dumps({"permission": "allow"}))


def _emit_claude(decision: str, reason: str) -> None:
    if decision == "deny":
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    # allow → no output; default permissions take over.


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    is_claude = (
        "tool_input" in payload or "tool_name" in payload or "hook_event_name" in payload
    )

    if is_claude:
        tool_name = payload.get("tool_name")
        if tool_name not in (None, "Bash"):
            sys.exit(0)  # only govern shell commands
        command = (payload.get("tool_input") or {}).get("command", "") or ""
        decision, reason = evaluate(command)
        _emit_claude(decision, reason)
    else:
        command = payload.get("command", "") or ""
        decision, reason = evaluate(command)
        _emit_cursor(decision, reason)

    sys.exit(0)


if __name__ == "__main__":
    main()
