"""Assert the framework version pin is in LOCKSTEP everywhere it lives.

The datalab framework version is recorded in three functional places in this
repo, and every one of them must reference the same release:

    pyproject.toml            [tool.uv.sources].datalab  tag = "vX.Y.Z"
    variables/medallion.yml   datalab_version: default "X.Y.Z"  (the Volume wheel filename)
    uv.lock                   the resolved `datalab` package's git tag

Historically this lockstep was enforced only by prose and a PR-template
checkbox, and it drifted (docs referenced 0.5.0 while the pin was 0.6.0, and
the vendored schemas lagged two releases). This check makes CI fail instead.

Stdlib only — runs with `uv run --no-project` (no venv needed):

    make check-lockstep

Exit 0 when all three agree, 1 with a per-site listing otherwise.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def pyproject_tag() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    source = data["tool"]["uv"]["sources"]["datalab"]
    tag = source.get("tag")
    if not tag:
        raise SystemExit(
            "pyproject.toml pins datalab without a `tag` (branch/rev pins break the "
            "wheel-filename contract: var.datalab_version must be a release version)."
        )
    return tag


def medallion_version() -> str:
    text = (REPO_ROOT / "variables" / "medallion.yml").read_text()
    match = re.search(r"datalab_version:\n(?:[ \t]+\w+:.*\n)*?[ \t]+default: \"([^\"]+)\"", text)
    if not match:
        raise SystemExit("variables/medallion.yml: could not locate datalab_version default")
    return match.group(1)


def lock_tag() -> str:
    data = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    for package in data.get("package", []):
        if package.get("name") == "datalab":
            git_url = package.get("source", {}).get("git", "")
            tags = parse_qs(urlparse(git_url).query).get("tag", [])
            if tags:
                return tags[0]
            raise SystemExit(f"uv.lock: datalab source has no tag pin: {git_url}")
    raise SystemExit("uv.lock: no `datalab` package entry found")


def main() -> int:
    tag = pyproject_tag()
    version = medallion_version()
    locked = lock_tag()

    problems: list[str] = []
    if not TAG_RE.match(tag):
        problems.append(f"pyproject.toml tag {tag!r} is not a vX.Y.Z release tag")
    if tag != f"v{version}":
        problems.append(
            f"pyproject.toml pins {tag} but variables/medallion.yml datalab_version is {version!r}"
        )
    if locked != tag:
        problems.append(f"uv.lock resolved {locked} but pyproject.toml pins {tag} (run `make lock`)")

    if problems:
        print("framework version pin is OUT OF LOCKSTEP:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nrun `make bump-framework VERSION=x.y.z` to realign every site.", file=sys.stderr)
        return 1
    print(f"framework pin is in lockstep: {tag} (pyproject tag == var.datalab_version == uv.lock)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
