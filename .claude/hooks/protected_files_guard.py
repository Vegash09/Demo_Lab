#!/usr/bin/env python3
"""PreToolUse guard for production-sensitive files in datalab.

Emits `permissionDecision: "ask"` for Edit/Write/MultiEdit/NotebookEdit calls
that target files in the protected surface (deploy config, dependency
manifests, CI/CD, agent harness, documents-of-record). The user is then
prompted to confirm with a banner explaining which invariants apply.
Non-protected files pass through with no decision so default permissions take
over.

Wired into `.claude/settings.json`; also referenced by `.cursor/hooks.json` and
`.codex/hooks.json` (all three harnesses share this one canonical guard).

Keep the PROTECTED list below in sync with:
  * `.githooks/pre-commit`            (the human-commit counterpart)
  * AGENTS.md "Protected file surface" table
When you add a production-sensitive path, update all three in the same change.
"""
from __future__ import annotations

import json
import os
import re
import sys

PROTECTED: list[tuple[str, str]] = [
    (r"^databricks\.yml$|^rbac\.yml$|^(variables|targets)/.*\.ya?ml$|^(resources|projects/[^/]+/resources)/.*\.yml$",
     "Declarative Automation Bundle manifest / variables / targets / RBAC (deploy surface)"),
    (r"^pyproject\.toml$|^uv\.lock$",
     "dependency manifest (uv-managed; CI runs `uv sync --frozen`)"),
    (r"^\.databricksignore$",
     "controls which files ship to the workspace on deploy"),
    (r"^(config|projects/[^/]+/config)/.*\.ya?ml$",
     "dataset configs — the deployed pipeline definition (validate: make validate-configs)"),
    (r"^\.github/(workflows|actions)/.*",
     "CI/CD pipeline (GitHub OIDC federation, bundle deploy)"),
    # Entries fenced `# adopter-if:<feature>` are dropped from generated adopters
    # that did not choose the feature — the same rows as AGENTS.md's table and
    # .githooks/pre-commit's PATTERNS, so the three stay aligned there too.
    # adopter-if:pr-template start
    (r"^\.github/pull_request_template\.md$",
     "unified pull-request template (one format for all PRs)"),
    # adopter-if:pr-template end
    (r"^\.claude/(settings\.json|hooks/.*|skills/.*)",
     "coding-agent harness config (hooks, settings, + the GENERATED .claude/skills copy)"),
    (r"^\.cursor/(rules|hooks)/.*|^\.cursor/hooks\.json$",
     "Cursor rules + agent hooks (incl. the gh-pr-create template guard)"),
    (r"^\.codex/hooks\.json$|^\.agents/skills/.*",
     "Codex hooks.json + .agents/skills (the CANONICAL authored agent-skills source)"),
    # adopter-if:agent-claude start
    (r"^scripts/sync_skills\.py$",
     "agent-skills sync generator — canonical (.agents/skills) → .claude/skills copy contract"),
    # adopter-if:agent-claude end
    (r"^scripts/(sync_schemas|check_lockstep|bump_framework|domains|check_sync_lists|check_templates_doc|check_adopter_docs|check_agent_settings|check_framework_current|check_framework_surface|release_changelog)\.py$",
     "repo-integrity tooling: schema vendoring, framework-version lockstep, domain registry, sync-list check, changelog release cut"),
    # adopter-if:schemas start
    (r"^schemas/.*\.json$",
     "vendored editor schemas — GENERATED from the pinned framework (make sync-schemas), never hand-edited"),
    # adopter-if:schemas end
    # adopter-if:mcp start
    (r"^\.mcp\.json$|^\.cursor/mcp\.json$",
     "opt-in MCP server config (agent↔Databricks read-only query connection)"),
    # adopter-if:mcp end
    # adopter-if:design start
    (r"^scripts/(design_diagram|design_spec|design_inventory|export_design)\.py$|^scripts/drawio_kit/.*",
     "design generator + vendored drawio-architecture-designer kit (the diagrams are built by these, never hand-drawn)"),
    # adopter-if:design end
    # adopter-if:githooks start
    (r"^\.githooks/.*",
     "git pre-commit guard (human-side counterpart to this hook)"),
    # adopter-if:githooks end
    (r"^Makefile$",
     "developer + CI entrypoints"),
    (r"^\.env(\..*)?$",
     "secrets file — must never be committed"),
    (r"^(AGENTS|CLAUDE|README)\.md$|^docs/(ARCHITECTURE|CICD|MIGRATION|GETTING_STARTED|NAMING|NEW_ADOPTER|ADOPTING|AGENT_MCP)\.md$",
     "document-of-record for AI coding agents"),
]


def _relpath(file_path: str) -> str:
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if file_path.startswith(proj + os.sep):
        return file_path[len(proj) + 1 :]
    return file_path


def _reason(rel: str, category: str) -> str:
    return (
        f"PROTECTED FILE — {rel}\n"
        f"Category: {category}\n\n"
        "This file is part of the production-sensitive surface for datalab.\n"
        "Before approving the edit, confirm:\n"
        "  • The change is captured in AGENTS.md (Common tasks or Critical knowledge sections)\n"
        "  • For databricks.yml / resources/*.yml: validate locally (`make validate`)\n"
        "  • For pyproject.toml: run `make lock` and commit uv.lock in the same change\n"
        "  • For .github/**: keep OIDC auth + `uv sync --frozen` semantics intact\n"
        "  • For src/datalab/{config,params}.py: every pipeline and job lane depends on these contracts\n\n"
        "Approve if the change is intentional and matches the AGENTS.md protocol."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    candidates = [
        tool_input.get("file_path"),
        tool_input.get("notebook_path"),
    ]
    file_path = next((c for c in candidates if c), "")
    if not file_path:
        sys.exit(0)

    rel = _relpath(file_path)
    for pattern, category in PROTECTED:
        if re.match(pattern, rel):
            sys.stdout.write(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "ask",
                            "permissionDecisionReason": _reason(rel, category),
                        }
                    }
                )
            )
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
