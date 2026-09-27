"""The generated design diagrams: scripts/design_diagram.py + the vendored
drawio-architecture-designer kit, and the guard that keeps agents off the XML.
Stdlib + PyYAML (dev venv), no Spark, no network, no browser."""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

yaml = pytest.importorskip("yaml")

import design_diagram as dd  # noqa: E402
import design_inventory as inventory  # noqa: E402

GUARD = REPO / ".cursor" / "hooks" / "design_drawio_guard.py"


def _dense_estate(seed: int) -> dd.Estate:
    """A synthetic 25-table domain with fan-in SQL, skip-layer reads, backward
    lookups, same-layer lookups, quarantine, overlay sources and consumers."""
    rnd = random.Random(seed)

    def spec(name, layer, srcs, kind="streaming_table", lookups=(), errors=False):
        s = {"name": name, "target": {"kind": kind}}
        if layer == "bronze":
            s["source"] = {"kind": "cloud_files", "path_conf": f"datalab.{name}_path"}
        elif len(srcs) == 1:
            s["source"] = {"kind": "table", "name": srcs[0][1], "layer": srcs[0][0],
                           "as_stream": True}
        else:
            s["source"] = {"kind": "sql", "query": "SELECT * FROM " + " JOIN ".join(n for _, n in srcs)}
        if lookups:
            s["transform"] = [{"function": "x.f", "tables": {
                f"t{i}": {"name": n, "layer": lay} for i, (lay, n) in enumerate(lookups)}}]
        if errors:
            s["columns"] = [{"name": "id", "quality": [
                {"criticality": "error", "check": {"function": "is_not_null"}}]}]
        return s

    specs = [("bronze", spec(f"raw_{i}", "bronze", []), f"c/raw_{i}") for i in range(8)]
    for i in range(10):
        lookups = [("gold", "agg_0")] if i == 3 else ([("silver", f"ent_{i - 1}")] if i in (5, 7) else [])
        specs.append(("silver", spec(f"ent_{i}", "silver", [("bronze", f"raw_{rnd.randrange(8)}")],
                                     lookups=lookups, errors=rnd.random() < 0.5), f"c/ent_{i}"))
    for i in range(7):
        srcs = [("silver", f"ent_{j}") for j in rnd.sample(range(10), rnd.randint(1, 3))]
        specs.append(("gold", spec(f"agg_{i}", "gold", [("bronze", "raw_1")] if i == 2 else srcs,
                                   kind="materialized_view"), f"c/agg_{i}"))
    dom = inventory.Domain(name="big", config_dir="config/big", layers=["bronze", "silver", "gold"])
    inventory.analyze(dom, specs)
    return dd.Estate(
        title="stress", domains=[dom],
        pipelines={"big_etl": dd.Pipeline("big_etl", "resources/big.yml", "config/big", True, "c")},
        jobs={"big_etl_refresh": dd.Job("big_etl_refresh", "resources/big.job.yml",
                                        [dd.Task("t", "pipeline", "big_etl")], "every day", True),
              "big_export": dd.Job("big_export", "resources/big.job.yml",
                                   [dd.Task("t", "python", "x.py")], "every week", False)},
        overlay={"sources": [{"name": "SAP S/4HANA", "feeds": ["big.bronze.raw_0", "big.bronze.raw_3"]}],
                 "consumers": [{"name": "Power BI", "logo": "dashboards",
                                "reads": ["big.gold.agg_1", "big.silver.ent_2"]}],
                 "jobs": {"big_export": {"reads": ["big.gold.agg_0"], "writes": "csv"}}},
        delivery={"targets": [], "workflows": [], "triggers": [], "make": {}},
    )


def test_the_committed_diagrams_are_current_and_clean():
    assert dd.main(["--check", "--root", str(REPO)]) == 0


@pytest.mark.parametrize("seed", range(6))
def test_a_dense_estate_lays_out_with_no_audit_finding(seed):
    est = _dense_estate(seed)
    assert dd.validate_overlay(est) == []
    assert dd.audit_pages(dd.implementation_pages(est)) == []


def test_the_generator_is_deterministic():
    est = _dense_estate(1)
    assert dd.emit(dd.implementation_pages(est)) == dd.emit(dd.implementation_pages(est))


def test_every_page_opens_with_page_view_off():
    files, _ = dd.render_files(REPO)
    for text in files.values():
        assert 'page="1"' not in text and 'page="0"' in text


def test_an_unknown_overlay_reference_fails_loudly():
    est = _dense_estate(0)
    est.overlay["consumers"].append({"name": "Ghost", "reads": ["big.gold.nope"]})
    assert any("big.gold.nope" in e for e in dd.validate_overlay(est))


def test_the_audit_catches_a_token_too_wide_for_its_card():
    page = dd.kit.Page("p")
    page.rect(0, 0, 120, 60, text="/Volumes/catalog/landing/a_very_long_unbroken_path/")
    assert any(m.startswith("OVERFLOW-X") for m in dd.wide_tokens(page))


def test_a_hand_edited_diagram_fails_the_check(tmp_path):
    for rel in ("projects", "targets", "design", "Makefile", "databricks.yml",
                ".github/workflows"):
        src = REPO / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
    assert dd.main(["--check", "--root", str(tmp_path)]) == 0
    drawio = tmp_path / dd.IMPL
    drawio.write_text(drawio.read_text().replace('width="', 'width="1', 1))
    assert dd.main(["--check", "--root", str(tmp_path)]) == 1


def _guard(payload: dict) -> int:
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          text=True, capture_output=True).returncode


@pytest.mark.parametrize("payload", [
    {"tool_input": {"file_path": "/r/design/02_implementation_end_to_end.drawio"}},
    {"tool_input": {"path": "design/images/02_1_estate.png"}},
    {"tool_input": {"command": "sed -i s/a/b/ design/02_implementation_end_to_end.drawio"}},
    {"tool_input": {"command": "cat x > design/01_design_config_driven_medallion.drawio"}},
    {"tool_input": {"command": "cp /tmp/n.drawio design/02_implementation_end_to_end.drawio"}},
    {"command": "echo x | tee design/images/02_1_estate.png"},
])
def test_the_guard_denies_writes_to_generated_design_files(payload):
    assert _guard(payload) == 2


@pytest.mark.parametrize("payload", [
    {"tool_input": {"file_path": "/r/design/estate.yml"}},
    {"tool_input": {"file_path": "/r/design/OVERVIEW.md"}},
    {"tool_input": {"command": "grep mxCell design/02_implementation_end_to_end.drawio > /tmp/x"}},
    {"tool_input": {"command": "cp design/02_implementation_end_to_end.drawio /tmp/old.drawio"}},
    {"tool_input": {"command": "make design"}},
    {"tool_input": {"command": "python3 scripts/design_diagram.py --write"}},
])
def test_the_guard_allows_reads_the_overlay_and_the_generator(payload):
    assert _guard(payload) == 0
