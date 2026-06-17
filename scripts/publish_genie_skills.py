"""Publish the canonical agent skills into Databricks Genie Code.

Genie Code (the in-workspace coding assistant) discovers skills from a
`.assistant/skills/` directory inside the Databricks Workspace — NOT from the
git repo. This pushes the one canonical `.agents/skills/` tree there via the
Databricks CLI (`databricks workspace import-dir`), so Genie loads the SAME
skills as Claude Code / Cursor / Codex. (Genie additionally auto-discovers
`AGENTS.md` from the workspace with no setup; this script only delivers the
discrete skills.)

Default is a dry run that prints the import command + the skills it would push.
Apply it with:

    make publish-genie-skills APPLY=1

    # user-level (default target): /Users/<you>/.assistant/skills
    # workspace-level override:
    make publish-genie-skills APPLY=1 GENIE_SKILLS_PATH=/Workspace/.assistant/skills

Stdlib only — shells out to the `databricks` CLI (the same tool `make deploy`
uses), so it needs no project venv and adds nothing to uv.lock.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / ".agents" / "skills"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a `databricks` CLI command, surfacing a friendly error if it is
    missing. Returns the completed process (caller checks returncode)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:  # databricks CLI not on PATH
        raise SystemExit(
            "FAILED: the `databricks` CLI was not found on PATH.\n"
            "  Install it (see docs/CICD.md) and authenticate "
            "(`databricks auth login`)."
        ) from exc


def resolve_workspace_dir(profile: str | None) -> str:
    """Default target = the current user's Genie skills folder,
    /Users/<userName>/.assistant/skills, resolved from `databricks current-user me`."""
    cmd = ["databricks", "current-user", "me"]
    if profile:
        cmd += ["--profile", profile]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise SystemExit(
            "FAILED: could not resolve the current user "
            "(`databricks current-user me`).\n"
            f"  {proc.stderr.strip()}\n"
            "  Authenticate first, or pass --workspace-dir explicitly."
        )
    try:
        user_name = json.loads(proc.stdout)["userName"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise SystemExit(
            "FAILED: unexpected `databricks current-user me` output.\n"
            "  Pass --workspace-dir explicitly (e.g. /Users/<you>/.assistant/skills)."
        ) from exc
    return f"/Users/{user_name}/.assistant/skills"


def list_skills(source: Path) -> list[str]:
    """Skill names = immediate subdirectories of source that contain a SKILL.md."""
    if not source.is_dir():
        raise SystemExit(f"FAILED: source skills dir not found: {source}")
    return sorted(p.name for p in source.iterdir() if (p / "SKILL.md").is_file())


def import_cmd(source: Path, workspace_dir: str, profile: str | None, overwrite: bool) -> list[str]:
    cmd = ["databricks", "workspace", "import-dir", str(source), workspace_dir]
    if overwrite:
        cmd.append("--overwrite")
    if profile:
        cmd += ["--profile", profile]
    return cmd


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="execute (default: print the command only)")
    parser.add_argument(
        "--workspace-dir",
        default="",
        help="target Workspace path (default: /Users/<you>/.assistant/skills)",
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="canonical skills dir to publish (default: .agents/skills)",
    )
    parser.add_argument("--profile", default="", help="Databricks CLI profile (default: ambient auth)")
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="do not pass --overwrite (fail if files already exist)",
    )
    args = parser.parse_args(argv)

    source = Path(args.source)
    profile = args.profile or None
    skills = list_skills(source)
    workspace_dir = args.workspace_dir or resolve_workspace_dir(profile)
    cmd = import_cmd(source, workspace_dir, profile, overwrite=not args.no_overwrite)

    print(f"skills to publish ({len(skills)}): {', '.join(skills)}")
    print(f"target: {workspace_dir}")
    print(f"command: {' '.join(cmd)}\n")

    if not args.apply:
        print("dry run — re-run with --apply (or `make publish-genie-skills APPLY=1`) to execute")
        return

    proc = _run(cmd)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"FAILED: import-dir exited {proc.returncode}")
    print(f"\npublished {len(skills)} skill(s) to {workspace_dir}")


if __name__ == "__main__":
    main(sys.argv[1:])
