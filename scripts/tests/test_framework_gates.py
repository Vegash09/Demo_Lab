"""The mandatory framework-bump gates: check_framework_current, check_framework_surface,
and the framework-doc link pinning shared by bump_framework / check_lockstep / scaffold.
Stdlib scripts, no Spark, no network."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # check_lockstep imports bump_framework
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


current = _load("check_framework_current")
surface = _load("check_framework_surface")
bump = _load("bump_framework")
lockstep = _load("check_lockstep")


# ---- check_framework_current ------------------------------------------------
def test_latest_release_orders_numerically_and_ignores_prereleases():
    tags = ["v0.9.0", "v0.10.0", "v1.0.0-rc1", "v1.0.0", "latest", "v2.0.0-rc1"]
    assert current.latest_release(tags) == "v1.0.0"
    assert current.latest_release(["main"]) is None


def test_current_pin_passes():
    code, message = current.evaluate("v1.0.0", "v1.0.0", "enforce")
    assert code == 0 and "latest release" in message


def test_stale_pin_is_mandatory_to_fix_when_enforced():
    code, message = current.evaluate("v0.10.0", "v1.0.0", "enforce")
    assert code == 1
    assert "MANDATORY" in message and "v1.0.0 is released" in message
    assert "make bump-framework VERSION=1.0.0" in message


def test_warn_mode_reports_but_does_not_fail():
    code, message = current.evaluate("v0.10.0", "v1.0.0", "warn")
    assert code == 0 and "DATALAB_FRAMEWORK_MANDATE=warn" in message


def test_unreadable_releases_fail_even_in_warn_mode():
    code, message = current.evaluate("v1.0.0", None, "warn")
    assert code == 1 and "UNKNOWN" in message


def test_mode_defaults_to_enforce_in_the_template_and_warn_in_adopters(tmp_path):
    template, adopter = tmp_path / "template", tmp_path / "adopter"
    (template / "projects").mkdir(parents=True)
    adopter.mkdir()
    assert current.mode(template, env={}) == "enforce"
    assert current.mode(adopter, env={}) == "warn"
    # the variable wins either way: opt-in for adopters, break-glass for the template
    assert current.mode(adopter, env={"DATALAB_FRAMEWORK_MANDATE": "enforce"}) == "enforce"
    assert current.mode(template, env={"DATALAB_FRAMEWORK_MANDATE": "WARN"}) == "warn"
    assert current.mode(template, env={"DATALAB_FRAMEWORK_MANDATE": "bogus"}) == "enforce"


def test_releases_fall_back_to_tags_when_unreadable(monkeypatch):
    monkeypatch.setattr(current, "published_releases", lambda: None)
    monkeypatch.setattr(current, "framework_tags", lambda: ["v0.10.0", "v1.0.0"])
    assert current.latest_framework_release() == ("v1.0.0", "git tags (GitHub Releases unreadable)")
    monkeypatch.setattr(current, "published_releases", lambda: ["v0.10.0"])  # v1.0.0 tagged, not published
    assert current.latest_framework_release() == ("v0.10.0", "published GitHub Releases")


# ---- check_framework_surface ------------------------------------------------
SCHEMA = {
    "properties": {
        "source": {
            "anyOf": [
                {"discriminator": {"mapping": {"table": "#/a", "kafka": "#/b"}, "propertyName": "kind"}},
                {"type": "null"},
            ]
        },
        "target": {
            "discriminator": {"mapping": {"streaming_table": "#/c", "managed_table": "#/d"}},
            "oneOf": [],
        },
    }
}


def test_kinds_come_from_the_schema_discriminators():
    assert surface.discriminator_kinds(SCHEMA, "source") == {"table", "kafka"}
    assert surface.discriminator_kinds(SCHEMA, "target") == {"streaming_table", "managed_table"}


def test_a_kind_counts_only_when_named_explicitly():
    assert surface.documented("kafka", "use `kafka` for topics")
    assert surface.documented("kafka", "source:\n  kind: kafka\n")
    assert not surface.documented("managed_table", "managed tables are great")
    # a longer kind must not satisfy a shorter one
    assert not surface.documented("table", "`managed_table` only")


def test_missing_kinds_names_every_gap():
    skill = "`table` and `streaming_table`"
    assert surface.missing_kinds(SCHEMA, skill) == {"target": ["managed_table"], "source": ["kafka"]}


def test_surface_gate_passes_on_this_repo():
    assert surface.main() == 0


def test_surface_gap_fails_in_the_template_and_warns_in_adopters(tmp_path, monkeypatch, capsys):
    import json

    for name, is_template in (("template", True), ("adopter", False)):
        root = tmp_path / name
        (root / "schemas").mkdir(parents=True)
        (root / ".agents/skills/author-ldp-artifact").mkdir(parents=True)
        (root / "schemas/table_config.schema.json").write_text(json.dumps(SCHEMA))
        (root / ".agents/skills/author-ldp-artifact/SKILL.md").write_text("`table` `kafka` `streaming_table`")
        if is_template:
            (root / "projects").mkdir()
    monkeypatch.delenv("DATALAB_FRAMEWORK_MANDATE", raising=False)
    assert surface.main(tmp_path / "template") == 1
    assert surface.main(tmp_path / "adopter") == 0
    assert "::warning" in capsys.readouterr().out


# ---- framework-doc link pinning ------------------------------------------------
def test_links_are_repinned_and_expressions_left_alone(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "[ref](https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md)\n"
        "tree: https://github.com/dediggibyte/datalab-framework/tree/v0.9.0/src/\n"
        "shell: https://github.com/dediggibyte/datalab-framework/blob/$LATEST/CHANGELOG.md\n"
        "tmpl: https://github.com/dediggibyte/datalab-framework/blob/@@FRAMEWORK_TAG@@/docs/\n"
        "other repo: https://github.com/dediggibyte/datalab/blob/main/README.md\n"
    )
    assert bump.pin_framework_links([doc], "v1.0.0") == [doc]
    text = doc.read_text()
    assert "datalab-framework/blob/v1.0.0/docs/FRAMEWORK.md" in text
    assert "datalab-framework/tree/v1.0.0/src/" in text
    assert "blob/$LATEST/" in text and "blob/@@FRAMEWORK_TAG@@/" in text
    assert "dediggibyte/datalab/blob/main/README.md" in text
    assert bump.pin_framework_links([doc], "v1.0.0") == []  # idempotent


def test_lockstep_flags_links_off_the_pin(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("see https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md\n")
    (problem,) = lockstep.stale_framework_links([doc], "v1.0.0", tmp_path)
    assert problem.startswith("doc.md:1 links the framework at 'main', not the pinned v1.0.0")
    bump.pin_framework_links([doc], "v1.0.0")
    assert lockstep.stale_framework_links([doc], "v1.0.0", tmp_path) == []


def test_non_git_trees_are_walked_and_workflows_skipped(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".venv/lib").mkdir(parents=True)
    for rel in ("docs/a.md", ".github/workflows/w.yml", ".venv/lib/x.md", "CHANGELOG.md"):
        (tmp_path / rel).write_text("https://github.com/dediggibyte/datalab-framework/blob/main/x\n")
    found = [p.relative_to(tmp_path).as_posix() for p in bump.tracked_text_files(tmp_path)]
    assert found == ["docs/a.md"]  # not a git repo: a filesystem walk, same exclusions


def test_gate_test_fixtures_are_never_repinned():
    root = SCRIPTS.parent
    tracked = {p.relative_to(root).as_posix() for p in bump.tracked_text_files(root)}
    assert "scripts/tests/test_framework_gates.py" not in tracked
    assert "AGENTS.md" in tracked and "CHANGELOG.md" not in tracked


@pytest.mark.parametrize("ref,pinnable", [("main", True), ("v0.9.0", True), ("$LATEST", False),
                                          ("@@FRAMEWORK_TAG@@", False), ("${{", False)])
def test_pinnable_refs(ref, pinnable):
    assert bump.is_pinnable_ref(ref) is pinnable
