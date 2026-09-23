"""Assert the framework version pin is in LOCKSTEP everywhere it lives.

The datalab framework version is recorded in three functional places in this
repo, and every one of them must reference the same release:

    pyproject.toml            [tool.uv.sources].datalab  tag = "vX.Y.Z"
    variables/medallion.yml   datalab_version: default "X.Y.Z"  (the Volume wheel filename)
    uv.lock                   the resolved `datalab` package's git tag
    uv.lock                   the resolved `datalab` package VERSION (what the built
                              wheel is named after — the filename var.datalab_wheel
                              points at is composed from this, not from the tag)
    docs / skills / scaffold  every link into the framework repo
                              (…/datalab-framework/blob/<ref>/…) names the pinned
                              tag, so the reference an author follows matches the
                              framework this repo actually runs

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bump_framework import FRAMEWORK_LINK_RE, is_pinnable_ref, tracked_text_files  # noqa: E402

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


def lock_version() -> str:
    """The RESOLVED package version uv recorded for `datalab` in uv.lock.

    Distinct from the tag: the tag says which ref to fetch, this says what the
    built package calls itself — and the wheel filename
    (`datalab-<version>-py3-none-any.whl`) that `var.datalab_wheel` points at is
    composed from THIS. Nothing else in this repo compares the two, so a tag
    whose package version disagrees would pass every gate and fail only when a
    serverless environment tried to install a wheel that is not there."""
    data = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    for package in data.get("package", []):
        if package.get("name") == "datalab":
            version = package.get("version")
            if not version:
                raise SystemExit("uv.lock: datalab entry has no resolved `version`")
            return str(version)
    raise SystemExit("uv.lock: no `datalab` package entry found")


def stale_framework_links(paths, tag: str, root: Path) -> list[str]:
    """Every framework-repo link whose ref is not the pinned ``tag``."""
    problems = []
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in FRAMEWORK_LINK_RE.finditer(line):
                ref = m.group(2)
                if is_pinnable_ref(ref) and ref != tag:
                    problems.append(
                        f"{path.relative_to(root)}:{lineno} links the framework at "
                        f"{ref!r}, not the pinned {tag} — the reference must describe the "
                        "version this repo runs (`make bump-framework` re-pins it)"
                    )
    return problems


def target_overrides() -> dict[str, str]:
    """Per-target `datalab_version` overrides from targets/*.yml.

    A target may deliberately soak-test a newer framework release. That is
    legitimate, but it must be VISIBLE: the override changes which wheel that
    target installs, and `make publish-wheel TARGET=<t>` must have published that
    version. Stdlib-only parse (this script runs `uv run --no-project`)."""
    found: dict[str, str] = {}
    targets_dir = REPO_ROOT / "targets"
    for path in sorted(targets_dir.glob("*.yml")):
        for match in re.finditer(
            r"^[ \t]*datalab_version:[ \t]*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?[ \t]*$",
            path.read_text(),
            re.MULTILINE,
        ):
            found[path.stem] = match.group(1)
    return found


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
    # The wheel filename var.datalab_wheel resolves to is built from the PACKAGE
    # version, not the tag. If they disagree, every gate here is green and the
    # failure lands on a serverless environment install.
    packaged = lock_version()
    if packaged != version:
        problems.append(
            f"uv.lock resolves datalab to package version {packaged!r} but "
            f"variables/medallion.yml datalab_version is {version!r} — "
            f"var.datalab_wheel would point at datalab-{version}-py3-none-any.whl "
            f"while the built wheel is datalab-{packaged}-py3-none-any.whl"
        )

    problems += stale_framework_links(tracked_text_files(REPO_ROOT), tag, REPO_ROOT)

    if problems:
        print("framework version pin is OUT OF LOCKSTEP:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nrun `make bump-framework VERSION=x.y.z` to realign every site.", file=sys.stderr)
        return 1
    print(
        f"framework pin is in lockstep: {tag} "
        "(pyproject tag == var.datalab_version == uv.lock tag == uv.lock package version)"
    )
    for target, override in sorted(target_overrides().items()):
        if override != version:
            print(
                f"  note: target {target!r} overrides datalab_version to {override} — "
                f"publish it there first (`make publish-wheel TARGET={target} APPLY=1`), "
                "or that target's environments will install a wheel that is not on the Volume"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
