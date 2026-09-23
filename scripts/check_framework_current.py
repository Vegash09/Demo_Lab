"""MANDATE: the pinned datalab framework must be the LATEST framework release.

Every time dediggibyte/datalab-framework publishes a vX.Y.Z release, the datalab
TEMPLATE (this repo while it carries the reference domains under projects/)
must move to it — the pin (`make bump-framework VERSION=X.Y.Z`) together with
the changes that version needs (docs/CICD.md "Framework bumps"). The
framework-bump workflow opens that PR; this check fails CI until it merges, so
a release can never sit unadopted again (the pin sat at v0.6.0 while the
framework shipped v0.9.0, and 0.10.0 only arrived inside an unrelated PR).

"Latest release" = the newest PUBLISHED, non-draft, non-prerelease GitHub
Release (read with `gh api`, which in CI carries the reader App token as
GH_TOKEN). A bare tag is not a release: the framework's release workflow gates
the tag before publishing. Only when Releases are unreadable does the check
fall back to `git ls-remote` tags, and it says so. Nothing readable at all
FAILS — staleness would otherwise be unknown and pass silently, which is how
the bump bot once reported success for six weeks while seeing nothing.

Mode — the repo/org variable DATALAB_FRAMEWORK_MANDATE (CI maps it to the env
var of the same name):
  * enforce  a stale pin fails. Default in the TEMPLATE (projects/ present).
  * warn     a stale pin only warns. Default in a GENERATED adopter repo (no
             projects/): its owners decide when to adopt; set `enforce` there
             to opt in. In the template, `warn` is the incident BREAK-GLASS
             (ship a hotfix before a breaking release is adopted) — delete the
             variable as soon as the bump merges.

Stdlib only — runs with `uv run --no-project`:

    make check-framework-current
    python scripts/check_framework_current.py --latest   # print the latest release (bot)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_REPO = "dediggibyte/datalab-framework"
FRAMEWORK_URL = f"https://github.com/{FRAMEWORK_REPO}.git"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MODE_VAR = "DATALAB_FRAMEWORK_MANDATE"


def version_key(tag: str) -> tuple[int, int, int]:
    m = TAG_RE.match(tag)
    if not m:
        raise ValueError(f"{tag!r} is not a vX.Y.Z tag")
    major, minor, patch = (int(g) for g in m.groups())
    return major, minor, patch


def latest_release(tags: list[str]) -> str | None:
    """The highest vX.Y.Z (pre-releases such as v1.0.0-rc1 are ignored)."""
    releases = [t for t in tags if TAG_RE.match(t)]
    return max(releases, key=version_key) if releases else None


def pinned_tag(root: Path = REPO_ROOT) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text())
    return data["tool"]["uv"]["sources"]["datalab"]["tag"]


def mode(root: Path = REPO_ROOT, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    chosen = env.get(MODE_VAR, "").strip().lower()
    if chosen in {"enforce", "warn"}:
        return chosen
    return "enforce" if (root / "projects").is_dir() else "warn"


def published_releases() -> list[str] | None:
    """Tags of published, non-draft, non-prerelease GitHub Releases, or None
    when they can't be read (no gh, no access)."""
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{FRAMEWORK_REPO}/releases",
         "--jq", ".[] | select(.draft | not) | select(.prerelease | not) | .tag_name"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def framework_tags() -> list[str]:
    # `-c http.https://github.com/.extraheader=` is LOAD-BEARING in CI:
    # actions/checkout persists an Authorization header (the GITHUB_TOKEN, which
    # cannot see the private framework) into the repo-local git config, and an
    # explicit header beats the App token the insteadOf rewrite puts in the URL.
    result = subprocess.run(
        ["git", "-c", "http.https://github.com/.extraheader=",
         "ls-remote", "--tags", "--refs", FRAMEWORK_URL, "v*"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"::warning::git ls-remote failed: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [line.rsplit("/", 1)[-1] for line in result.stdout.splitlines() if line.strip()]


def latest_framework_release() -> tuple[str | None, str]:
    """(latest vX.Y.Z, where it came from)."""
    releases = published_releases()
    if releases is not None:
        return latest_release(releases), "published GitHub Releases"
    return latest_release(framework_tags()), "git tags (GitHub Releases unreadable)"


def evaluate(pinned: str, latest: str | None, gate_mode: str) -> tuple[int, str]:
    """(exit code, message) — pure, for the tests."""
    if latest is None:
        return 1, (
            f"could not read any vX.Y.Z release of {FRAMEWORK_REPO}, so whether the pin "
            f"({pinned}) is current is UNKNOWN. In CI: check the datalab-framework reader "
            "App credentials; locally: check your GitHub access (gh auth status)."
        )
    if version_key(pinned) >= version_key(latest):
        return 0, f"framework pin {pinned} is the latest release"
    message = (
        f"datalab-framework {latest} is released but this repo pins {pinned}. Merge the "
        f"`chore: bump datalab framework {pinned} -> {latest}` PR (the framework-bump "
        "workflow opens it; Actions > 'Bot · framework version bump' > Run workflow if it "
        f"is missing), or run `make bump-framework VERSION={latest.lstrip('v')}` and add "
        "the changes that version needs (docs/CICD.md \"Framework bumps\")."
    )
    if gate_mode == "warn":
        return 0, f"{MODE_VAR}=warn — not failing: {message}"
    return 1, f"adopting framework releases is MANDATORY here: {message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--latest", action="store_true", help="print the latest framework release tag and exit")
    args = parser.parse_args(argv)

    latest, source = latest_framework_release()
    if args.latest:
        if latest is None:
            print(f"no vX.Y.Z release readable ({source})", file=sys.stderr)
            return 1
        print(latest)
        return 0

    pinned, gate_mode = pinned_tag(), mode()
    code, message = evaluate(pinned, latest, gate_mode)
    if code:
        print(f"::error title=Framework pin is stale::{message}")
        return code
    if latest is not None and version_key(pinned) < version_key(latest):
        print(f"::warning title=Stale framework pin::{message}")
    else:
        print(f"{message} (latest per {source}; mode: {gate_mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
