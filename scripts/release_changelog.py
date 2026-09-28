"""Cut CHANGELOG.md's [Unreleased] section into a version when a deploy ships it.

The deploy IS the release. Every push to main deploys the bundle to dev
(.github/workflows/ci-cd.yml); once that deploy has SUCCEEDED, the `release` job
runs

    python3 scripts/release_changelog.py cut --apply

which moves everything under `## [Unreleased]` into a new
`## [X.Y.Z] — YYYY-MM-DD` section, sets pyproject.toml [project].version (and the
root package's version in uv.lock) to X.Y.Z in lockstep, and the job pushes that
to main as a `chore(release): vX.Y.Z` commit. Stage/prod promote a cut release
by tagging THAT commit `vX.Y.Z-rcN` / `vX.Y.Z`; `verify` gates those deploys.

Before this existed nothing ever cut the changelog: every dev deploy after 0.3.0
left its entries under [Unreleased] and the repo version at 0.3.0.

Modes:
    check   CI + pre-commit gate: CHANGELOG.md is well formed and the version in
            pyproject.toml / uv.lock equals the newest released section.
    cut     Release [Unreleased] (plus late entries, below) as the next version.
            A dry run that prints the section unless --apply is given.
    verify  Stage/prod gate: the checked-out tree IS a cut release — nothing
            pending, versions in lockstep, and --tag names that version.

Version bump (SemVer): a `### Removed` group or a `**BREAKING` bullet is
breaking, `### Added` is a feature, anything else is a patch. Breaking bumps
MAJOR (MINOR while the version is 0.x), a feature bumps MINOR, a patch bumps
PATCH. With no released section yet, the first release is pyproject's version.

Late entries: a PR branched before a cut can merge CLEANLY with its new bullet
inside the section that cut released — git anchors the insertion on the `###`
heading line, which now belongs to the release. `cut` compares every section an
earlier `chore(release): vX.Y.Z` commit wrote with that commit's copy: bullets
that appeared since, while everything the release commit wrote is still there
verbatim, merged after the release, so they move into the new one. Any other
edit of a released section is a deliberate human change and is left alone.

Stdlib only — runs with `python3` / `uv run --no-project`:

    make check-changelog              # the gate
    make release-changelog            # preview the release the next deploy cuts
    make release-changelog APPLY=1    # cut it locally (recovery only)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

UNRELEASED = "## [Unreleased]"
PLACEHOLDER = "_Nothing yet._"
# Keep a Changelog's group order; any other group (Docs, Notes, ...) follows.
CANONICAL = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: [—-] (\d{4}-\d{2}-\d{2}))?$")
H2_RE = re.compile(r"^## ")
H3_RE = re.compile(r"^### (.+?)\s*$")
BULLET_RE = re.compile(r"^[-*+] ")
BREAKING_RE = re.compile(r"^[-*+] \*\*BREAKING")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
PLACEHOLDER_RE = re.compile(r"^_nothing yet\._$", re.IGNORECASE)
RELEASE_SUBJECT_RE = re.compile(r"^chore\(release\): v(\d+\.\d+\.\d+)\b")
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)(?:-rc\d+)?$")
VERSION_LINE_RE = re.compile(r'^(version\s*=\s*")([^"]*)(".*)$', re.DOTALL)


class ReleaseError(Exception):
    """The repo is in a state no release can be cut from."""


@dataclass
class Block:
    """One entry: a top-level bullet with its continuation lines, or a paragraph."""

    heading: str | None  # its `###` group; None = prose right under the `##` title
    lines: list[str]

    @property
    def key(self) -> tuple[str | None, str]:
        return self.heading, "\n".join(line.rstrip() for line in self.lines)

    @property
    def is_bullet(self) -> bool:
        return bool(BULLET_RE.match(self.lines[0]))


@dataclass
class Section:
    title: str  # the `## ...` line
    start: int  # line index of the title
    end: int  # line index one past the section
    blocks: list[Block]

    @property
    def version(self) -> str | None:
        m = RELEASE_RE.match(self.title)
        return m.group(1) if m else None


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def canonical_heading(name: str) -> str:
    return next((c for c in CANONICAL if c.lower() == name.strip().lower()), name.strip())


# --------------------------------------------------------------------------- parse
def parse_blocks(body: list[str]) -> list[Block]:
    """Split a section body into entries, fence-aware. A new entry starts at a
    column-0 bullet or at unindented text after a blank line; `_Nothing yet._`
    placeholders and empty `###` groups carry no entries."""
    blocks: list[Block] = []
    heading: str | None = None
    current: list[str] | None = None
    in_fence = False
    prev_blank = True

    def close() -> None:
        nonlocal current
        if current:
            while current and not current[-1].strip():
                current.pop()
            if current and not (len(current) == 1 and PLACEHOLDER_RE.match(current[0].strip())):
                blocks.append(Block(heading, current))
        current = None

    for line in body:
        fence = bool(FENCE_RE.match(line))
        if not in_fence:
            h3 = H3_RE.match(line)
            if h3:
                close()
                heading = canonical_heading(h3.group(1))
                prev_blank = True
                continue
            if BULLET_RE.match(line) or (line.strip() and not line[0].isspace() and prev_blank):
                close()
                current = [line]
            elif current is not None:
                current.append(line)
            elif line.strip():
                current = [line]
        else:
            current = current if current is not None else []
            current.append(line)
        if fence:
            in_fence = not in_fence
        prev_blank = not line.strip()
    close()
    return blocks


def split_sections(lines: list[str]) -> tuple[list[str], list[Section]]:
    """The header (everything before the first `##`) and the `##` sections."""
    starts: list[int] = []
    in_fence = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and H2_RE.match(line):
            starts.append(i)
    sections = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        sections.append(Section(lines[start].rstrip(), start, end, parse_blocks(lines[start + 1 : end])))
    return lines[: starts[0]] if starts else list(lines), sections


# -------------------------------------------------------------------------- render
def render_blocks(blocks: list[Block]) -> list[str]:
    """A canonical section body: prose first, then one `###` group per heading in
    Keep a Changelog order — duplicate groups (one per PR) merge into one."""
    order: list[str | None] = [None, *CANONICAL]
    for block in blocks:
        if block.heading not in order:
            order.append(block.heading)
    out: list[str] = []
    for heading in order:
        group = [b for b in blocks if b.heading == heading]
        if not group:
            continue
        if heading is not None:
            out.append(f"### {heading}")
        prev: Block | None = None
        for block in group:
            if prev is not None and not (prev.is_bullet and block.is_bullet):
                out.append("")
            out.extend(block.lines)
            prev = block
        out.append("")
    return out


# ------------------------------------------------------------------------ versions
def project_name_version(root: Path) -> tuple[str, str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return project["name"], project["version"]


def lock_package_re(name: str) -> re.Pattern[str]:
    normalized = re.sub(r"[-_.]+", "-", name).lower()  # uv.lock names are PEP 503-normalized
    return re.compile(r'(\[\[package\]\]\nname = "' + re.escape(normalized) + r'"\nversion = ")([^"]+)(")')


def lock_version(root: Path, name: str) -> str | None:
    """The root package's version in uv.lock; None when the repo has no lock yet
    (a freshly generated adopter before its first `make lock`)."""
    lock = root / "uv.lock"
    if not lock.exists():
        return None
    m = lock_package_re(name).search(lock.read_text(encoding="utf-8"))
    if not m:
        raise ReleaseError(f"uv.lock has no [[package]] entry for the root project {name!r} (run `make lock`)")
    return m.group(2)


def set_versions(root: Path, name: str, version: str) -> None:
    """pyproject [project].version + the root package in uv.lock — the same edit
    `uv lock` makes for a version-only change, without needing the private
    framework repo on the release runner."""
    path = root / "pyproject.toml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    table = None
    for i, line in enumerate(lines):
        if re.match(r"^\[[^\]]+\]\]?\s*$", line):
            table = line.strip()
            continue
        m = VERSION_LINE_RE.match(line) if table == "[project]" else None
        if m:
            lines[i] = m.group(1) + version + m.group(3)
            path.write_text("".join(lines), encoding="utf-8")
            break
    else:
        raise ReleaseError("pyproject.toml has no [project] version line")
    if project_name_version(root)[1] != version:
        raise ReleaseError("rewriting pyproject.toml [project].version did not take")

    lock = root / "uv.lock"
    if lock.exists():
        text, count = lock_package_re(name).subn(rf"\g<1>{version}\g<3>", lock.read_text(encoding="utf-8"))
        if count != 1:
            raise ReleaseError(f"uv.lock: expected one [[package]] entry for {name!r}, found {count}")
        lock.write_text(text, encoding="utf-8")


def next_version(base: str, blocks: list[Block]) -> str:
    major, minor, patch = version_tuple(base)
    headings = {b.heading for b in blocks}
    breaking = "Removed" in headings or any(BREAKING_RE.match(b.lines[0]) for b in blocks)
    if breaking and major > 0:
        return f"{major + 1}.0.0"
    if breaking or "Added" in headings:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ----------------------------------------------------------------------- git state
def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def release_commits(root: Path) -> dict[str, str]:
    """version -> the `chore(release): vX.Y.Z` commit that cut it."""
    try:
        if git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
            print("warning: shallow clone — releases cut before its depth are not "
                  "checked for late entries (check out with fetch-depth: 0)", file=sys.stderr)
        log = git(root, "log", "--format=%H%x09%s", "--", "CHANGELOG.md")
    except (OSError, subprocess.CalledProcessError):
        return {}  # not a git checkout (tests, a tarball): nothing to compare against
    found: dict[str, str] = {}
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        m = RELEASE_SUBJECT_RE.match(subject)
        if m:
            found.setdefault(m.group(1), sha)
    return found


def late_entries(
    root: Path, sections: list[Section], commits: dict[str, str]
) -> tuple[list[Block], dict[int, list[Block]], list[str]]:
    """Entries merged into an already-released section after its release commit.

    Returns (late blocks in file order, {section index: the blocks it keeps},
    notes). A section counts only when every block its release commit wrote is
    still present verbatim — then the extra blocks can only be later insertions.
    """
    late: list[Block] = []
    keep: dict[int, list[Block]] = {}
    notes: list[str] = []
    for index, section in enumerate(sections):
        version = section.version
        if version not in commits:
            continue
        sha = commits[version]
        try:
            snapshot = git(root, "show", f"{sha}:CHANGELOG.md").splitlines()
        except subprocess.CalledProcessError:
            continue
        released = next((s for s in split_sections(snapshot)[1] if s.version == version), None)
        if released is None:
            continue
        wrote = Counter(b.key for b in released.blocks)
        has = Counter(b.key for b in section.blocks)
        if not has - wrote:
            continue
        if wrote - has:
            notes.append(
                f"[{version}] was edited after its release commit {sha[:7]}; left as is "
                "(its extra entries are not moved because the release's own entries changed too)"
            )
            continue
        budget, kept = Counter(wrote), []
        for block in section.blocks:
            if budget[block.key] > 0:
                budget[block.key] -= 1
                kept.append(block)
            else:
                late.append(block)
        keep[index] = kept
        notes.append(
            f"[{version}] gained {len(section.blocks) - len(kept)} entr(y/ies) after its release "
            f"commit {sha[:7]} — a PR that branched before that cut; moving them into this release"
        )
    return late, keep, notes


# -------------------------------------------------------------------------- modes
def read_changelog(root: Path) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.exists():
        raise ReleaseError("CHANGELOG.md is missing")
    return path.read_text(encoding="utf-8").splitlines()


def check(root: Path) -> list[str]:
    """Structural problems + version drift; empty when the changelog is sound."""
    lines = read_changelog(root)
    header, sections = split_sections(lines)
    problems: list[str] = []
    if not header or header[0].strip() != "# Changelog":
        problems.append("CHANGELOG.md must start with a `# Changelog` title")
    titles = [s.title for s in sections]
    if titles.count(UNRELEASED) != 1:
        problems.append(f"CHANGELOG.md needs exactly one `{UNRELEASED}` section (found {titles.count(UNRELEASED)})")
    elif titles[0] != UNRELEASED:
        problems.append(f"`{UNRELEASED}` must be the first `##` section — new entries go at the top")
    released = [s for s in sections if s.title != UNRELEASED]
    for section in released:
        if section.version is None:
            problems.append(
                f"CHANGELOG.md:{section.start + 1}: {section.title!r} is not a release heading "
                "(`## [X.Y.Z] — YYYY-MM-DD`)"
            )
    versions = [s.version for s in released if s.version]
    for newer, older in zip(versions, versions[1:], strict=False):
        if version_tuple(newer) <= version_tuple(older):
            problems.append(f"released versions must strictly descend: [{newer}] is listed above [{older}]")
    name, version = project_name_version(root)
    if versions and version != versions[0]:
        problems.append(
            f"pyproject.toml [project].version is {version} but the newest release in CHANGELOG.md "
            f"is [{versions[0]}] — the version moves only when a deploy cuts a release; never edit it by hand"
        )
    locked = lock_version(root, name)
    if locked is not None and locked != version:
        problems.append(f"uv.lock records {name} {locked} but pyproject.toml says {version} (run `make lock`)")
    return problems


def plan_cut(root: Path, date: str) -> tuple[str | None, list[str], list[str]]:
    """(the new version or None when nothing is pending, the new CHANGELOG.md
    lines, notes). Refuses to cut from a changelog that fails `check`."""
    problems = check(root)
    if problems:
        raise ReleaseError("CHANGELOG.md fails `check`:\n  - " + "\n  - ".join(problems))
    lines = read_changelog(root)
    header, sections = split_sections(lines)
    unreleased, released = sections[0], sections[1:]
    late, keep, notes = late_entries(root, released, release_commits(root))
    pending = unreleased.blocks + late
    if not pending:
        return None, lines, notes

    _, current = project_name_version(root)
    version = next_version(current, pending) if released else current
    out = [*header]
    while out and not out[-1].strip():
        out.pop()
    out += ["", UNRELEASED, "", PLACEHOLDER, "", f"## [{version}] — {date}", "", *render_blocks(pending)]
    for index, section in enumerate(released):
        if index in keep:
            out += [section.title, "", *render_blocks(keep[index])]
        else:
            out += lines[section.start : section.end]
    while out and not out[-1].strip():
        out.pop()
    return version, out, notes


def cut(root: Path, date: str, apply: bool, github_output: str | None) -> int:
    version, lines, notes = plan_cut(root, date)
    for note in notes:
        print(f"note: {note}")
    outputs = {"released": "false", "version": ""}
    if version is None:
        print("nothing to release — [Unreleased] is empty and no late entries were found")
    else:
        section = split_sections(lines)[1][1]
        print(f"release {version}:\n")
        print("\n".join(lines[section.start : section.end]).rstrip() + "\n")
        if apply:
            (root / "CHANGELOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            set_versions(root, project_name_version(root)[0], version)
            remaining = check(root)
            if remaining:
                raise ReleaseError("the cut left CHANGELOG.md failing `check`:\n  - " + "\n  - ".join(remaining))
            print(f"cut release {version}: CHANGELOG.md, pyproject.toml and uv.lock updated")
            outputs = {"released": "true", "version": version}
        else:
            print("dry run — re-run with --apply (make release-changelog APPLY=1) to write it")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in outputs.items())
    return 0


def verify(root: Path, tag: str | None) -> list[str]:
    """Problems that make this tree unfit to promote to stage/prod."""
    problems = check(root)
    sections = split_sections(read_changelog(root))[1]
    if sections and sections[0].title == UNRELEASED and sections[0].blocks:
        problems.append(
            f"[Unreleased] still holds {len(sections[0].blocks)} entr(y/ies): this commit is not a cut "
            "release. Promote the `chore(release): vX.Y.Z` commit the dev deploy pushed to main"
        )
    versions = [s.version for s in sections if s.version]
    if not versions:
        problems.append("CHANGELOG.md has no released version to promote yet — deploy to dev first")
    if tag is not None:
        m = TAG_RE.match(tag)
        if not m:
            problems.append(f"tag {tag!r} is not vX.Y.Z or vX.Y.Z-rcN")
        elif versions and m.group(1) != versions[0]:
            problems.append(
                f"tag {tag} names {m.group(1)} but this commit is release [{versions[0]}] — "
                f"tag the `chore(release): v{m.group(1)}` commit instead"
            )
    return problems


def report(problems: list[str], what: str) -> int:
    if not problems:
        return 0
    print(f"{what}:", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("check", help="fail if CHANGELOG.md is malformed or the repo version drifted")
    p_cut = sub.add_parser("cut", help="release [Unreleased] as the next version (dry run unless --apply)")
    p_cut.add_argument("--apply", action="store_true", help="write CHANGELOG.md, pyproject.toml and uv.lock")
    p_cut.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"), help="release date (UTC today)")
    p_cut.add_argument("--github-output", help="append released=/version= to this file ($GITHUB_OUTPUT)")
    p_verify = sub.add_parser("verify", help="fail unless this tree is a cut release (stage/prod gate)")
    p_verify.add_argument("--tag", help="the vX.Y.Z / vX.Y.Z-rcN tag being deployed")
    args = parser.parse_args(argv)

    try:
        if args.mode == "check":
            if report(check(args.root), "CHANGELOG.md is not releasable"):
                return 1
            _, version = project_name_version(args.root)
            print(f"CHANGELOG.md is well formed; version {version} is in lockstep")
            return 0
        if args.mode == "cut":
            return cut(args.root, args.date, args.apply, args.github_output)
        if report(verify(args.root, args.tag), "this commit is not a promotable release"):
            return 1
        print(f"release {project_name_version(args.root)[1]} verified for promotion")
        return 0
    except ReleaseError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
