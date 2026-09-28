"""scripts/release_changelog.py — the deploy-time changelog cut, its gates, and
the late-entry repair. Stdlib + git, no Spark, no network."""

import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import release_changelog as rc  # noqa: E402

PYPROJECT = '[project]\nname            = "demo_etl"\nversion         = "{v}"\ndependencies    = []\n'
LOCK = 'version = 1\n\n[[package]]\nname = "demo-etl"\nversion = "{v}"\nsource = {{ editable = "." }}\n'


def repo(tmp_path: Path, changelog: str, version: str = "0.3.0", lock: bool = True) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT.format(v=version))
    if lock:
        (tmp_path / "uv.lock").write_text(LOCK.format(v=version))
    return tmp_path


def changelog(unreleased: str, released: str = "## [0.3.0] — 2026-06-18\n\n### Added\n- old\n") -> str:
    return f"# Changelog\n\nPreamble.\n\n## [Unreleased]\n\n{unreleased}\n{released}"


def cut(root: Path, date: str = "2026-09-27") -> str | None:
    version, lines, _ = rc.plan_cut(root, date)
    if version:
        (root / "CHANGELOG.md").write_text("\n".join(lines) + "\n")
        rc.set_versions(root, "demo_etl", version)
    return version


def section(root: Path, title_prefix: str) -> str:
    lines = (root / "CHANGELOG.md").read_text().splitlines()
    sec = next(s for s in rc.split_sections(lines)[1] if s.title.startswith(title_prefix))
    return "\n".join(lines[sec.start : sec.end]).strip()


# ------------------------------------------------------------------- the real file
def test_real_changelog_passes_check():
    assert rc.check(REPO) == []


def test_cutting_the_real_changelog_loses_nothing(tmp_path):
    for name in ("CHANGELOG.md", "pyproject.toml", "uv.lock"):
        shutil.copy(REPO / name, tmp_path / name)
    before = (tmp_path / "CHANGELOG.md").read_text().splitlines()
    version, after, _ = rc.plan_cut(tmp_path, "2026-09-27")
    if version is None:
        pytest.skip("[Unreleased] is empty right now")
    _, old = rc.split_sections(before)
    _, new = rc.split_sections(after)

    def entries(lines):
        return Counter(line.rstrip() for line in lines if line.strip() and not line.startswith("#"))

    assert entries(before[old[0].start : old[0].end]) == entries(after[new[1].start : new[1].end])
    assert before[old[1].start :] == after[new[2].start :]  # released history is untouched


# ---------------------------------------------------------------------- versioning
@pytest.mark.parametrize(
    ("base", "unreleased", "expected"),
    [
        ("0.3.0", "### Fixed\n- a fix\n", "0.3.1"),
        ("0.3.0", "### Changed\n- tweak\n### Docs\n- words\n", "0.3.1"),
        ("0.3.0", "### Fixed\n- a fix\n### Added\n- a feature\n", "0.4.0"),
        ("0.3.0", "### Changed\n- **BREAKING:** renamed\n", "0.4.0"),  # 0.x: breaking bumps MINOR
        ("1.2.3", "### Changed\n- **BREAKING:** renamed\n", "2.0.0"),
        ("1.2.3", "### Removed\n- the old flag\n", "2.0.0"),
        ("1.2.3", "### Added\n- a feature\n", "1.3.0"),
    ],
)
def test_bump_follows_the_headings(tmp_path, base, unreleased, expected):
    root = repo(tmp_path, changelog(unreleased, f"## [{base}] — 2026-01-01\n\n### Added\n- old\n"), base)
    assert cut(root) == expected
    assert rc.project_name_version(root)[1] == expected
    assert rc.lock_version(root, "demo_etl") == expected
    assert rc.check(root) == []


def test_first_release_is_the_pyproject_version(tmp_path):
    root = repo(tmp_path, "# Changelog\n\n## [Unreleased]\n\n### Added\n- Initial repo.\n", "0.1.0", lock=False)
    assert cut(root) == "0.1.0"
    assert section(root, "## [0.1.0]") == "## [0.1.0] — 2026-09-27\n\n### Added\n- Initial repo."


def test_cut_merges_duplicate_groups_in_canonical_order(tmp_path):
    unreleased = (
        "### Fixed\n- f1\n\n### Added\n- a1\n  continued\n\n### Changed\n- c1\n\n"
        "### Notes\n- n1\n\n### Added\n- a2\n\n  ```yaml\n  ## not a heading\n  - not a bullet\n  ```\n"
    )
    root = repo(tmp_path, changelog(unreleased))
    assert cut(root) == "0.4.0"
    assert section(root, "## [0.4.0]") == (
        "## [0.4.0] — 2026-09-27\n\n"
        "### Added\n- a1\n  continued\n- a2\n\n  ```yaml\n  ## not a heading\n  - not a bullet\n  ```\n\n"
        "### Changed\n- c1\n\n### Fixed\n- f1\n\n### Notes\n- n1"
    )
    assert section(root, "## [Unreleased]") == "## [Unreleased]\n\n_Nothing yet._"
    assert "Preamble." in (root / "CHANGELOG.md").read_text()


def test_nothing_pending_is_a_no_op(tmp_path, capsys):
    root = repo(tmp_path, changelog("_Nothing yet._\n"))
    before = (root / "CHANGELOG.md").read_text()
    out = tmp_path / "gh_output"
    assert rc.cut(root, "2026-09-27", apply=True, github_output=str(out)) == 0
    assert (root / "CHANGELOG.md").read_text() == before
    assert out.read_text() == "released=false\nversion=\n"


def test_dry_run_writes_nothing(tmp_path):
    root = repo(tmp_path, changelog("### Fixed\n- f\n"))
    before = {p.name: p.read_text() for p in tmp_path.iterdir()}
    assert rc.main(["--root", str(root), "cut"]) == 0
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == before


# --------------------------------------------------------------------------- check
@pytest.mark.parametrize(
    ("text", "version", "needle"),
    [
        (changelog("### Fixed\n- f\n"), "0.4.0", "never edit it by hand"),
        ("# Changelog\n\n## [0.3.0] — 2026-06-18\n\n## [Unreleased]\n", "0.3.0", "must be the first"),
        ("# Changelog\n\n## [Unreleased]\n\n## [0.2.0] — 2026-01-01\n\n## [0.3.0] — 2026-06-18\n",
         "0.2.0", "strictly descend"),
        ("# Changelog\n\n## [Unreleased]\n\n## Version 0.3.0\n", "0.3.0", "not a release heading"),
        ("# Notes\n\n## [Unreleased]\n", "0.3.0", "# Changelog"),
    ],
)
def test_check_rejects(tmp_path, text, version, needle):
    problems = rc.check(repo(tmp_path, text, version))
    assert any(needle in p for p in problems), problems


def test_check_rejects_lock_drift(tmp_path):
    root = repo(tmp_path, changelog("_Nothing yet._\n"))
    (root / "uv.lock").write_text(LOCK.format(v="0.2.0"))
    assert any("uv.lock records" in p for p in rc.check(root))


def test_cut_refuses_a_broken_changelog(tmp_path):
    root = repo(tmp_path, changelog("### Fixed\n- f\n"), "9.9.9")
    with pytest.raises(rc.ReleaseError, match="fails `check`"):
        rc.plan_cut(root, "2026-09-27")


# -------------------------------------------------------------------------- verify
def test_verify_accepts_a_cut_release_and_its_tags(tmp_path):
    root = repo(tmp_path, changelog("### Fixed\n- f\n"))
    cut(root)
    assert rc.verify(root, "v0.3.1") == []
    assert rc.verify(root, "v0.3.1-rc2") == []
    assert rc.verify(root, None) == []


@pytest.mark.parametrize(
    ("tag", "needle"), [("v0.3.0", "tag the `chore(release): v0.3.0` commit"), ("release-1", "is not vX.Y.Z")]
)
def test_verify_rejects_a_mismatched_tag(tmp_path, tag, needle):
    root = repo(tmp_path, changelog("### Fixed\n- f\n"))
    cut(root)
    assert any(needle in p for p in rc.verify(root, tag))


def test_verify_rejects_pending_entries(tmp_path):
    root = repo(tmp_path, changelog("### Fixed\n- not released yet\n"))
    assert any("not a cut release" in p for p in rc.verify(root, "v0.3.0"))


# ------------------------------------------------------- late entries (real git)
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, env=GIT_ENV).stdout


def add_bullet(root: Path, after: str, bullet: str) -> None:
    path = root / "CHANGELOG.md"
    path.write_text(path.read_text().replace(after + "\n", f"{after}\n{bullet}\n", 1))


@pytest.fixture
def released_with_stale_pr(tmp_path):
    """main cuts 0.4.0 (as the release job does) while a PR branched before the
    cut adds a bullet under the same `### Added`; merging the PR is CLEAN and
    lands its bullet inside the released section."""
    root = repo(tmp_path, changelog("### Added\n- merged first\n\n### Fixed\n- a fix\n"))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-qm", "feat: first")
    git(root, "switch", "-qc", "pr")
    add_bullet(root, "### Added", "- merged late")
    git(root, "commit", "-qam", "feat: late")
    git(root, "switch", "-q", "main")
    assert cut(root) == "0.4.0"
    git(root, "commit", "-qam", "chore(release): v0.4.0")
    git(root, "merge", "-q", "--no-edit", "pr")  # clean — that is the hazard
    assert "- merged late" in section(root, "## [0.4.0]")
    return root


def test_late_entries_move_into_the_next_release(released_with_stale_pr):
    root = released_with_stale_pr
    version, _, notes = rc.plan_cut(root, "2026-09-28")
    assert version == "0.5.0"  # the late bullet is an `### Added`
    assert any("[0.4.0] gained 1" in n for n in notes)
    assert cut(root, "2026-09-28") == "0.5.0"
    assert section(root, "## [0.5.0]") == "## [0.5.0] — 2026-09-28\n\n### Added\n- merged late"
    assert section(root, "## [0.4.0]") == (
        "## [0.4.0] — 2026-09-27\n\n### Added\n- merged first\n\n### Fixed\n- a fix"
    )
    assert rc.check(root) == []


def test_a_deliberate_edit_of_a_released_section_is_left_alone(released_with_stale_pr):
    root = released_with_stale_pr
    path = root / "CHANGELOG.md"
    path.write_text(path.read_text().replace("- a fix", "- a fix (typo corrected)"))
    version, lines, notes = rc.plan_cut(root, "2026-09-28")
    assert version is None
    assert any("edited after its release commit" in n for n in notes)
    assert "- merged late" in "\n".join(lines)  # not moved, not dropped


def test_new_entries_and_late_entries_release_together(released_with_stale_pr):
    root = released_with_stale_pr
    add_bullet(root, "_Nothing yet._", "\n### Fixed\n- next fix")
    assert cut(root, "2026-09-28") == "0.5.0"
    assert section(root, "## [0.5.0]") == (
        "## [0.5.0] — 2026-09-28\n\n### Added\n- merged late\n\n### Fixed\n- next fix"
    )
