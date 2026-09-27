#!/usr/bin/env python3
"""Generate the design/ draw.io diagrams from the estate - never hand-drawn.

The implementation map used to be hand-edited XML: every new table, job or
domain was patched in by an agent, arrows had no waypoints and ran through
cards, labels clipped, and a second domain was bolted on as a strip at the
bottom. This script replaces that with the drawio-architecture-designer method
(.agents/skills/drawio-architecture-designer): the diagram is a layout MODEL
built in Python from the repo itself, emitted to .drawio by the vendored kit
(scripts/drawio_kit/), and audited before it is written.

    design/02_implementation_end_to_end.drawio   GENERATED from the estate:
        1 - Estate overview    domains, pipelines, jobs + an inventory table
        N - <domain>           lineage: sources -> layers -> consumers, with
                               quarantine, orchestration and routed arrows
        last - Delivery        CI/CD triggers -> bundle targets, profiles
    design/01_design_config_driven_medallion.drawio   the conceptual spec,
        laid out by scripts/design_spec.py through the same kit

Estate facts come from the files that define it, nothing else:
  * config/ artifacts (via scripts/design_inventory.py discovery)
  * resources/*.yml and projects/*/resources/*.yml (pipelines + jobs)
  * design/estate.yml (optional overlay): source systems, consumers and job
    reads/writes that no YAML in the bundle states
  * targets/*.yml, .github/workflows/ci-cd.yml and the Makefile (delivery)

    make design          # --write: regenerate both .drawio files
    make check-design    # --check: fail (CI) if a .drawio is stale, hand-edited,
                         #          or its layout audit is not clean
    python scripts/design_diagram.py --preview out/   # HTML twin + PNGs to LOOK at

The audit is the kit's own (text overflow, text colour, colliding cards) plus
audit_arrows (a line through a card it does not connect) plus a collinear-
overlap check. Any finding fails --write and --check.
"""

from __future__ import annotations

import argparse
import difflib
import html
import io
import math
import re
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
KIT = SCRIPTS / "drawio_kit"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(KIT))

import design_inventory as inventory  # noqa: E402
import drawio_kit as kit  # noqa: E402
from arrows import Lanes, audit_arrows, flow  # noqa: E402
from render import audit as layout_audit  # noqa: E402
from render import estimate_text_height  # noqa: E402

IMPL = Path("design") / "02_implementation_end_to_end.drawio"
SPEC = Path("design") / "01_design_config_driven_medallion.drawio"
OVERLAY = Path("design") / "estate.yml"

FLOW = kit.FLOW
CONTROL = kit.EDGE
QUARANTINE = "#C0392B"
LAYER_ACCENT = {"bronze": kit.BRONZE, "silver": kit.SILVER, "gold": kit.GOLD}

# Geometry (px). Named once so a column can move in one edit.
MARGIN = 40
PANEL_PAD = 14            # card inset inside a column panel
PANEL_HEAD = 52           # panel title + kicker before the first card
CARD_GAP = 16             # between stacked cards
CHILD_GAP = 30            # parent -> quarantine card (a `down` arrow needs 26+)
CONTAINER_PAD = 16        # pipeline container around its layer panels
BAR_H = 44                # the pipeline's dark title bar
LANE_STEP = 10            # min distance between two lanes
LANE_EDGE = 12            # lane inset from the gutter sides
MIN_GUTTER = 44
COL_W = {"sources": 250, "layer": 270, "consumers": 260}
CARD_SIZE = 11.5


# --------------------------------------------------------------------------- #
# Estate model
# --------------------------------------------------------------------------- #

@dataclass
class Task:
    key: str
    kind: str  # pipeline | python | notebook | sql | other
    ref: str   # pipeline resource key, or the file / notebook path


@dataclass
class Job:
    key: str
    file: str
    tasks: list[Task]
    trigger: str
    alerts: bool
    params: dict[str, str] = field(default_factory=dict)

    @property
    def pipelines(self) -> list[str]:
        return [t.ref for t in self.tasks if t.kind == "pipeline"]

    @property
    def is_orchestration(self) -> bool:
        return bool(self.pipelines)


@dataclass
class Pipeline:
    key: str
    file: str
    config_dir: str
    serverless: bool
    catalog: str


@dataclass
class Estate:
    title: str
    domains: list[inventory.Domain]
    pipelines: dict[str, Pipeline]
    jobs: dict[str, Job]
    overlay: dict
    delivery: dict

    def pipeline_of(self, domain: inventory.Domain) -> Pipeline | None:
        for p in self.pipelines.values():
            if p.config_dir and p.config_dir.rstrip("/").endswith(domain.config_dir):
                return p
        return self.pipelines.get(f"{domain.name}_etl")

    def domain_of_job(self, job: Job) -> inventory.Domain | None:
        for d in self.domains:
            pipe = self.pipeline_of(d)
            if pipe and pipe.key in job.pipelines:
                return d
        candidates = []
        for d in self.domains:
            pipe = self.pipeline_of(d)
            if pipe and Path(pipe.file).parent == Path(job.file).parent:
                candidates.append(d)
        if len(candidates) == 1:
            return candidates[0]
        named = [d for d in candidates or self.domains if job.key.startswith(d.name)]
        return named[0] if len(named) == 1 else None


def _load_yaml(path: Path):
    import yaml  # dev-venv dependency, like design_inventory

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _trigger(job: dict) -> str:
    trig = job.get("trigger") or {}
    if trig.get("periodic"):
        per = trig["periodic"]
        n, unit = per.get("interval", 1), str(per.get("unit", "")).lower()
        unit = unit[:-1] if unit.endswith("s") and str(n) == "1" else unit
        return f"every {n} {unit}" if str(n) != "1" else f"every {unit}"
    if trig.get("file_arrival"):
        return "on file arrival"
    if trig.get("table_update"):
        return "on table update"
    sched = job.get("schedule") or {}
    if sched.get("quartz_cron_expression"):
        return f"cron {sched['quartz_cron_expression']}"
    if job.get("continuous"):
        return "continuous"
    return "on demand"


def discover_resources(root: Path) -> tuple[dict[str, Pipeline], dict[str, Job]]:
    files = sorted([*root.glob("resources/*.yml"), *root.glob("projects/*/resources/*.yml")])
    pipelines: dict[str, Pipeline] = {}
    jobs: dict[str, Job] = {}
    for path in files:
        data = (_load_yaml(path).get("resources") or {})
        rel = path.relative_to(root).as_posix()
        for key, spec in (data.get("pipelines") or {}).items():
            conf = spec.get("configuration") or {}
            cdir = str(conf.get("datalab.config_dir") or "")
            cdir = re.sub(r"^\$\{workspace\.file_path\}/?", "", cdir)
            pipelines[key] = Pipeline(key=key, file=rel, config_dir=cdir,
                                      serverless=bool(spec.get("serverless")),
                                      catalog=str(spec.get("catalog") or ""))
        for key, spec in (data.get("jobs") or {}).items():
            tasks = []
            for t in spec.get("tasks") or []:
                if t.get("pipeline_task"):
                    ref = str(t["pipeline_task"].get("pipeline_id", ""))
                    m = re.search(r"resources\.pipelines\.([\w-]+)\.id", ref)
                    tasks.append(Task(t.get("task_key", ""), "pipeline", m.group(1) if m else ref))
                elif t.get("spark_python_task"):
                    tasks.append(Task(t.get("task_key", ""), "python",
                                      str(t["spark_python_task"].get("python_file", ""))))
                elif t.get("notebook_task"):
                    tasks.append(Task(t.get("task_key", ""), "notebook",
                                      str(t["notebook_task"].get("notebook_path", ""))))
                elif t.get("sql_task"):
                    tasks.append(Task(t.get("task_key", ""), "sql", "sql_task"))
                else:
                    tasks.append(Task(t.get("task_key", ""), "other", ""))
            params = {str(p.get("name")): str(p.get("default", ""))
                      for p in spec.get("parameters") or [] if p.get("name")}
            jobs[key] = Job(key=key, file=rel, tasks=tasks, trigger=_trigger(spec),
                            alerts=bool(spec.get("email_notifications")), params=params)
    return pipelines, jobs


# ---- delivery facts: stdlib only (regex over the files that state them) ----

_CASE = re.compile(r"^\s*([a-z_]+)/(\S*)\)\s+target=\"?(\$?\w+)\"?;?\s*(?:deploy=(\w+))?", re.M)
_HELP = re.compile(r"^([A-Za-z0-9_.-]+):[^\n#]*##\s*(.+)$", re.M)


def _trigger_label(event: str, ref: str) -> str:
    if event == "pull_request":
        return "pull request"
    if event == "workflow_dispatch":
        return "manual dispatch"
    if ref.startswith("refs/heads/"):
        return f"push to {ref[len('refs/heads/'):]}"
    if ref.startswith("refs/tags/"):
        return f"tag {ref[len('refs/tags/'):]}"
    return f"{event} {ref}".strip()


def discover_delivery(root: Path) -> dict:
    targets = []
    for path in sorted((root / "targets").glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^\s*mode:\s*(\w+)", text, re.M)
        targets.append({"name": path.stem, "mode": m.group(1) if m else "",
                         "default": bool(re.search(r"^\s*default:\s*true", text, re.M))})
    wf_dir = root / ".github" / "workflows"
    workflows = sorted(p.name for p in wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []
    triggers = []
    cicd = wf_dir / "ci-cd.yml"
    if cicd.exists():
        for event, ref, target, deploy in _CASE.findall(cicd.read_text(encoding="utf-8")):
            if target.startswith("$"):
                continue  # workflow_dispatch: the operator picks the target
            triggers.append({"trigger": _trigger_label(event, ref), "target": target,
                             "deploy": deploy != "false"})
    chain, dispatch, auto = [], False, []
    if cicd.exists():
        text = cicd.read_text(encoding="utf-8")
        chain = list(dict.fromkeys(re.findall(r"uses:\s*\./\.github/workflows/([\w.-]+\.ya?ml)", text)))
        dispatch = "workflow_dispatch" in text
        auto = re.findall(r'\[ "\$target" = "(\w+)" \] && auto="true"', text)
    make_help = {}
    makefile = root / "Makefile"
    if makefile.exists():
        make_help = {t: h.strip() for t, h in _HELP.findall(makefile.read_text(encoding="utf-8"))}
    order = [t["target"] for t in triggers]
    targets.sort(key=lambda t: (order.index(t["name"]) if t["name"] in order else 99, t["name"]))
    return {"targets": targets, "workflows": workflows, "triggers": triggers, "make": make_help,
            "chain": chain, "dispatch": dispatch, "auto_approve": auto}


def load_overlay(root: Path) -> dict:
    path = root / OVERLAY
    return _load_yaml(path) if path.exists() else {}


def discover(root: Path) -> Estate:
    pipelines, jobs = discover_resources(root)
    overlay = load_overlay(root)
    title = str(overlay.get("title") or "")
    if not title:
        m = re.search(r"^bundle:\s*\n\s+name:\s*(\S+)", (root / "databricks.yml").read_text(
            encoding="utf-8"), re.M) if (root / "databricks.yml").exists() else None
        title = m.group(1) if m else root.name
    return Estate(title=title, domains=inventory.discover(root), pipelines=pipelines,
                  jobs=jobs, overlay=overlay, delivery=discover_delivery(root))


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #

_LONG = re.compile(r"[^\s]{22,}")


def esc(text: str) -> str:
    """HTML-escape a label; let long unbreakable tokens (paths, dotted names)
    wrap after / . _ so they never run past the card edge."""
    text = html.escape(str(text).replace("`", ""), quote=False)
    return _LONG.sub(lambda m: re.sub(r"([/._])", "\\1\u200b", m.group(0)), text)


def card_text(title: str, lines: list[str]) -> str:
    body = f'<b style="font-size:12.5px">{esc(title)}</b>'
    for ln in lines:
        body += f"<br>{esc(ln)}"
    return body


def card_height(w: float, text: str, pl: float, size: float = CARD_SIZE) -> int:
    probe = {"w": w, "pl": pl, "pr": 14, "size": size, "text": text, "valign": "top", "pt": 12}
    return int(math.ceil((estimate_text_height(probe) + 12) / 2.0) * 2)


def put_card(p: kit.Page, x: float, y: float, w: float, title: str, lines: list[str],
             accent: str | None = None, fill: str = kit.WHITE, stroke: str = kit.LINE,
             logo: str | None = None, cid: str | None = None) -> tuple[str, int]:
    pl = 18 + (32 if logo else 0) if accent else (16 + (32 if logo else 0))
    text = card_text(title, lines)
    h = max(48, card_height(w, text, pl))
    rid = p.rect(x, y, w, h, fill=fill, stroke=stroke, radius=8, text=text, size=CARD_SIZE,
                 align="left", valign="top", pl=pl, pr=14, pt=12, pb=10, id=cid)
    if accent:
        p.rect(x, y + 10, 5, h - 20, fill=accent, stroke="none", radius=3)
    if logo:
        p.img(x + (16 if accent else 12), y + 12, 24, 24, logo)
    return rid, h


def panel(p: kit.Page, x: float, y: float, w: float, h: float, title: str,
          kicker: str | None = None, fill: str = kit.PANEL, stroke: str = kit.PANEL_LINE) -> str:
    pid = p.rect(x, y, w, h, fill=fill, stroke=stroke, radius=10, text="", valign="top")
    p.text(x + 14, y + 10, w - 28, 20, f"<b>{esc(title)}</b>", size=13, align="left")
    if kicker:
        p.text(x + 14, y + 29, w - 28, 16, esc(kicker), size=10.5, align="left", ls=0.6)
    return pid


def gutter_width(n_lanes: int) -> int:
    return max(MIN_GUTTER, 2 * LANE_EDGE + LANE_STEP * max(0, n_lanes - 1))


def lanes_in(lo: float, hi: float, keys: list) -> dict:
    if not keys:
        return {}
    lo, hi = lo + LANE_EDGE - 6, hi - LANE_EDGE + 6  # Lanes pads 6 itself
    return Lanes(lo, hi, keys).pos


def short_target(table: inventory.Table) -> str:
    t = table.target.replace("`", "")
    t = t.replace("streaming table", "streaming table").replace(" · AUTO CDC", " · AUTO CDC")
    return t


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def count_kinds(domain: inventory.Domain) -> dict:
    views = sum(1 for t in domain.tables if "view" in t.target)
    sinks = sum(1 for t in domain.tables if "sink" in t.target)
    quarantines = sum(1 for t in domain.tables if t.quarantine)
    return {"tables": len(domain.tables) - views - sinks, "views": views, "sinks": sinks,
            "quarantine": quarantines}


def job_lines(job: Job) -> list[str]:
    kinds = sorted({t.kind for t in job.tasks})
    names = {"pipeline": "pipeline_task", "python": "spark_python_task",
             "notebook": "notebook_task", "sql": "sql_task", "other": "task"}
    lines = [" + ".join(names[k] for k in kinds) + f" · {job.trigger}"]
    if job.alerts:
        lines.append("failure alerts: email_notifications")
    lines.append(job.file)
    return lines


# --------------------------------------------------------------------------- #
# Edge routing - shape to shape, lanes in gutters, corridors for skips
# --------------------------------------------------------------------------- #

@dataclass
class LEdge:
    src: str
    dst: str
    kind: str  # data | lookup | quarantine | read
    ci: int = 0
    cj: int = 0

    @property
    def color(self) -> str:
        return QUARANTINE if self.kind == "quarantine" else FLOW

    @property
    def dashed(self) -> bool:
        return self.kind in ("lookup", "quarantine", "read")


def order_by_upstream(columns: list[list[str]], nodes: dict, edges: list[LEdge]) -> None:
    """Barycentric ordering, left to right: each card sits near the average
    position of what feeds it, which removes most crossings on a dense page.
    A quarantine card stays glued under its parent. Deterministic."""
    frac: dict[str, float] = {}
    for c, col in enumerate(columns):
        groups: list[list[str]] = []
        for nid in col:
            if nodes[nid]["kind"] == "quar" and groups:
                groups[-1].append(nid)
            else:
                groups.append([nid])
        if c > 0:
            n = len(groups)

            def key(item, c=c, n=n):
                i, grp = item
                ups = [frac[e.src] for e in edges
                       if e.dst == grp[0] and e.src in frac and e.ci < c]
                own = i / max(1, n)
                return (sum(ups) / len(ups) if ups else own, i)
            groups = [g for _, g in sorted(enumerate(groups), key=key)]
        col[:] = [nid for g in groups for nid in g]
        for i, nid in enumerate(col):
            frac[nid] = i / max(1, len(col))


def plan_lanes(edges: list[LEdge], ncols: int):
    """Lane keys per gutter and corridor lane keys, from topology alone."""
    gut: list[list] = [[] for _ in range(ncols)]
    corridor: list = []

    def add(g, key):
        if key not in gut[g]:
            gut[g].append(key)

    for e in edges:
        if e.kind == "quarantine":
            continue
        if e.cj == e.ci + 1:
            add(e.ci, ("in", e.dst))
        elif e.cj == e.ci:
            add(e.ci, ("self", e.dst))
        else:
            add(e.ci, ("out", e.src))
            add(e.cj - 1, ("in", e.dst))
            if e.dst not in corridor:
                corridor.append(e.dst)
    # departures left of arrivals keeps the source-side fan short
    for g in gut:
        g.sort(key=lambda k: {"out": 0, "self": 1, "in": 2}[k[0]])
    return gut, corridor


PORTS = [0.5, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6]


def route(p: kit.Page, edges: list[LEdge], lane_x: list[dict], corridor_y: dict,
          ports: dict) -> None:
    """Draw every logical edge. `ports` holds the attachment fraction per
    source ("out": right edge), per target ("in": left edge) and per self-loop
    target ("self": right edge) - per node, not per edge, so a fan-out still
    leaves from one point and a bus still lands on one arrowhead."""
    for e in edges:
        style = {"color": e.color, "dashed": e.dashed, "sw": 2}
        if e.kind == "quarantine":
            p.edge(e.src, e.dst, ex=0.5, ey=1, nx=0.5, ny=0, points=[], **style)
            continue
        ey = ports["out"].get(e.src, 0.5)
        ny = ports["in"].get(e.dst, 0.5)
        if e.cj == e.ci + 1:
            flow(p, e.src, e.dst, lane_x[e.ci][("in", e.dst)], ey=ey, ny=ny, **style)
        elif e.cj == e.ci:
            a = _geom(p, e.src)
            b = _geom(p, e.dst)
            lane = lane_x[e.ci][("self", e.dst)]
            sy = ports["self"].get(e.dst, 0.8)
            if abs(sy - ports["out"].get(e.dst, 0.5)) < 0.05:
                sy = 0.2 if sy > 0.5 else 0.8  # never land on the node's own exit port
            p.edge(e.src, e.dst, ex=1, ey=ey, nx=1, ny=sy,
                   points=[(lane, a["y"] + a["h"] * ey), (lane, b["y"] + b["h"] * sy)], **style)
        else:
            flow(p, e.src, e.dst, lane_x[e.ci][("out", e.src)], ey=ey, ny=ny,
                 corridor=corridor_y[e.dst], lane2=lane_x[e.cj - 1][("in", e.dst)], **style)


def resolve_ports(p: kit.Page, edges: list[LEdge], lane_x: list[dict],
                  corridor_y: dict, attempts: int = 24) -> dict:
    """Pick attachment fractions so no two unrelated edges share a run.
    Deterministic: the same estate always yields the same ports."""
    ports: dict = {"out": {}, "in": {}, "self": {}}
    by_name = {}
    for e in edges:
        by_name[(e.src, e.dst)] = e
    for attempt in range(attempts):
        trial = kit.Page(p.name)
        trial.items = [dict(it) for it in p.items]
        route(trial, edges, lane_x, corridor_y, ports)
        clashes = overlap_findings(trial)
        if not clashes:
            return ports
        m = re.match(r"OVERLAP\s+(\S+)->(\S+) and (\S+)->(\S+) ", clashes[0])
        if not m:
            return ports
        e1, e2 = by_name.get((m.group(1), m.group(2))), by_name.get((m.group(3), m.group(4)))
        # rotate one port of the pair per attempt: e1 exit, e2 exit, e1 entry, e2 entry
        choice = [("out", e1.src if e1 else None), ("out", e2.src if e2 else None),
                  ("in", e1.dst if e1 else None), ("in", e2.dst if e2 else None)][attempt % 4]
        side, node = choice
        if node is None:
            continue
        if e1 and e1.ci == e1.cj and side == "in":
            side = "self"
        cur = ports[side].get(node, 0.5)
        ports[side][node] = PORTS[(PORTS.index(cur) + 1) % len(PORTS)] if cur in PORTS else 0.3
    return ports


def _geom(p: kit.Page, cid: str) -> dict:
    for it in p.items:
        if it.get("id") == cid:
            return it
    raise KeyError(cid)


def edge_segments(p: kit.Page) -> list[tuple[dict, list]]:
    out = []
    for e in (i for i in p.items if i["kind"] == "edge"):
        a, b = _geom(p, e["src"]), _geom(p, e["dst"])
        x1, y1 = a["x"] + a["w"] * e["ex"], a["y"] + a["h"] * e["ey"]
        x2, y2 = b["x"] + b["w"] * e["nx"], b["y"] + b["h"] * e["ny"]
        pts = [(x1, y1)] + list(e["points"]) + [(x2, y2)]
        # the kit (and draw.io) insert an elbow between two points that differ
        # on both axes - mirror that so the check sees the drawn path
        path = [pts[0]]
        for q in pts[1:]:
            px, py = path[-1]
            if abs(q[0] - px) > 0.5 and abs(q[1] - py) > 0.5:
                path.append((q[0], py) if abs(q[0] - px) > abs(q[1] - py) else (px, q[1]))
            path.append(q)
        out.append((e, list(zip(path, path[1:], strict=False))))
    return out


def overlap_findings(p: kit.Page) -> list[str]:
    """Two different relationships drawn on top of each other read as one line.
    Collinear overlap is fine only when the two edges share a source (a fan-out)
    or a target (a bus)."""
    segs = edge_segments(p)
    found = []
    for i, (e1, s1) in enumerate(segs):
        for e2, s2 in segs[i + 1:]:
            if e1["src"] == e2["src"] or e1["dst"] == e2["dst"]:
                continue
            for (a1, b1) in s1:
                for (a2, b2) in s2:
                    if abs(a1[1] - b1[1]) < 0.5 and abs(a2[1] - b2[1]) < 0.5 \
                            and abs(a1[1] - a2[1]) < 3:
                        lo = max(min(a1[0], b1[0]), min(a2[0], b2[0]))
                        hi = min(max(a1[0], b1[0]), max(a2[0], b2[0]))
                        if hi - lo > 2:
                            found.append(f"OVERLAP   {e1['src']}->{e1['dst']} and "
                                         f"{e2['src']}->{e2['dst']} share a horizontal run")
                    if abs(a1[0] - b1[0]) < 0.5 and abs(a2[0] - b2[0]) < 0.5 \
                            and abs(a1[0] - a2[0]) < 3:
                        lo = max(min(a1[1], b1[1]), min(a2[1], b2[1]))
                        hi = min(max(a1[1], b1[1]), max(a2[1], b2[1]))
                        if hi - lo > 2:
                            found.append(f"OVERLAP   {e1['src']}->{e1['dst']} and "
                                         f"{e2['src']}->{e2['dst']} share a vertical run")
    return sorted(set(found))


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def _ref_index(est: Estate) -> dict[str, tuple[inventory.Domain, str]]:
    """`domain.layer.table` (and quarantine tables) -> (domain, node id)."""
    idx = {}
    for d in est.domains:
        for t in d.tables:
            idx[f"{d.name}.{t.layer}.{t.name}"] = (d, inventory.table_node(d.name, t.layer, t.name))
            if t.quarantine:
                idx[f"{d.name}.{t.layer}.{t.quarantine}"] = (
                    d, inventory.table_node(d.name, t.layer, t.quarantine))
    return idx


def validate_overlay(est: Estate) -> list[str]:
    idx = _ref_index(est)
    errors = []
    for section, key in (("sources", "feeds"), ("consumers", "reads")):
        for item in est.overlay.get(section) or []:
            if not item.get("name"):
                errors.append(f"design/estate.yml: a {section} entry has no name")
            for ref in item.get(key) or []:
                if ref not in idx:
                    errors.append(f"design/estate.yml: {section} '{item.get('name')}' "
                                  f"{key} unknown table '{ref}' (use domain.layer.table)")
    for job, spec in (est.overlay.get("jobs") or {}).items():
        if job not in est.jobs:
            errors.append(f"design/estate.yml: jobs.{job} is not a job in resources/*.yml")
        for ref in (spec or {}).get("reads") or []:
            if ref not in idx:
                errors.append(f"design/estate.yml: jobs.{job} reads unknown table '{ref}'")
    return errors


def domain_page(est: Estate, dom: inventory.Domain, number: int) -> kit.Page:
    pipe = est.pipeline_of(dom)
    counts = count_kinds(dom)
    jobs = [j for j in est.jobs.values() if est.domain_of_job(j) is dom]
    orch = [j for j in jobs if j.is_orchestration]
    edge_jobs = [j for j in jobs if not j.is_orchestration]
    idx = _ref_index(est)
    overlay_jobs = est.overlay.get("jobs") or {}

    p = kit.Page(f"{number} - {dom.name}")
    subtitle = " · ".join([plural(counts["tables"], "table"), plural(counts["views"], "view")]
                          + ([plural(counts["sinks"], "sink")] if counts["sinks"] else [])
                          + [f"{counts['quarantine']} quarantine", plural(len(jobs), "job"),
                             f"artifacts in {dom.config_dir}/"])
    p.head(MARGIN, 54, 1200, f"{esc(dom.name)} · lineage and orchestration", esc(subtitle))

    # ---- columns: sources | layers... | consumers ------------------------
    nodes: dict[str, dict] = {}
    columns: list[list[str]] = []
    src_col: list[str] = []
    for nid, label in dom.externals.items():
        nodes[nid] = {"title": label, "lines": [], "col": 0, "kind": "ext"}
        src_col.append(nid)
    for item in est.overlay.get("sources") or []:
        feeds = [idx[r] for r in item.get("feeds") or [] if r in idx and idx[r][0] is dom]
        if not feeds:
            continue
        nid = "ovsrc__" + re.sub(r"\W", "_", item["name"])
        nodes[nid] = {"title": item["name"], "lines": [item["detail"]] if item.get("detail") else [],
                      "col": 0, "kind": "src", "logo": kit.L.get(item.get("logo", ""))}
        src_col.insert(0, nid)
    columns.append(src_col)

    for li, layer in enumerate(dom.layers, start=1):
        col = []
        for t in (t for t in dom.tables if t.layer == layer):
            nid = inventory.table_node(dom.name, t.layer, t.name)
            lines = [short_target(t)]
            if t.built_from and t.built_from != "—":
                lines.append("from " + t.built_from.replace("`", ""))
            if t.transforms:
                lines.append("transform " + ", ".join(t.transforms))
            if t.gate and t.gate != "—":
                lines.append("dq " + t.gate.replace("`", ""))
            nodes[nid] = {"title": t.name, "lines": lines, "col": li, "kind": "table",
                          "accent": LAYER_ACCENT.get(layer, kit.TEAL)}
            col.append(nid)
            if t.quarantine:
                qid = inventory.table_node(dom.name, t.layer, t.quarantine)
                nodes[qid] = {"title": t.quarantine,
                              "lines": ["dqx error rows + _errors evidence"],
                              "col": li, "kind": "quar", "parent": nid}
                col.append(qid)
        columns.append(col)

    cons_col: list[str] = []
    for j in edge_jobs:
        nid = "job__" + j.key
        lines = job_lines(j)
        spec = overlay_jobs.get(j.key) or {}
        if spec.get("writes"):
            lines.insert(1, f"writes {spec['writes']}")
        if not spec.get("reads"):
            layer_params = [k for k in j.params if k.endswith("_schema")]
            if layer_params:
                lines.insert(1, "reads schema(s) via job parameter " + ", ".join(layer_params))
        nodes[nid] = {"title": j.key, "lines": lines, "col": len(columns), "kind": "job"}
        cons_col.append(nid)
    for item in est.overlay.get("consumers") or []:
        reads = [r for r in item.get("reads") or [] if r in idx and idx[r][0] is dom]
        if not reads:
            continue
        nid = "ovcons__" + re.sub(r"\W", "_", item["name"])
        nodes[nid] = {"title": item["name"],
                      "lines": [item["detail"]] if item.get("detail") else [],
                      "col": len(columns), "kind": "consumer",
                      "logo": kit.L.get(item.get("logo", ""))}
        cons_col.append(nid)
    columns.append(cons_col)
    ncols = len(columns)

    # ---- logical edges ----------------------------------------------------
    col_of = {nid: n["col"] for nid, n in nodes.items()}
    ledges: dict[tuple[str, str], LEdge] = {}

    def add_edge(src, dst, kind):
        if src not in col_of or dst not in col_of or src == dst:
            return
        key = (src, dst)
        if key in ledges:
            if ledges[key].kind in ("lookup", "read") and kind == "data":
                ledges[key].kind = "data"
            return
        ledges[key] = LEdge(src, dst, kind, col_of[src], col_of[dst])

    for t in dom.tables:
        dst = inventory.table_node(dom.name, t.layer, t.name)
        for e in t.edges:
            add_edge(e.source, dst, "lookup" if e.dashed else "data")
        if t.quarantine:
            add_edge(dst, inventory.table_node(dom.name, t.layer, t.quarantine), "quarantine")
    for item in est.overlay.get("sources") or []:
        nid = "ovsrc__" + re.sub(r"\W", "_", item["name"])
        for r in item.get("feeds") or []:
            if r in idx and idx[r][0] is dom:
                add_edge(nid, idx[r][1], "data")
    for item in est.overlay.get("consumers") or []:
        nid = "ovcons__" + re.sub(r"\W", "_", item["name"])
        for r in item.get("reads") or []:
            if r in idx and idx[r][0] is dom:
                add_edge(idx[r][1], nid, "read")
    for j in edge_jobs:
        for r in (overlay_jobs.get(j.key) or {}).get("reads") or []:
            if r in idx and idx[r][0] is dom:
                add_edge(idx[r][1], "job__" + j.key, "read")
    edges = list(ledges.values())
    order_by_upstream(columns, nodes, edges)
    gut_keys, corridor_keys = plan_lanes(edges, ncols)

    # ---- x positions --------------------------------------------------------
    widths = [COL_W["sources"]] + [COL_W["layer"]] * (ncols - 2) + [COL_W["consumers"]]
    xs = []   # panel x per column
    gut_lo = []
    x = MARGIN
    for c in range(ncols):
        xs.append(x)
        x += widths[c]
        extra = CONTAINER_PAD if c in (0, ncols - 2) else 0  # container edge sits here
        gw = gutter_width(len(gut_keys[c])) + extra
        gut_lo.append((x, x + gw, c))
        x += gw
    lane_x = []
    for c, (lo, hi, _) in enumerate(gut_lo):
        # lanes stay outside the pipeline container's padding strip
        if c == 0:
            hi -= CONTAINER_PAD
        if c == ncols - 2:
            lo += CONTAINER_PAD
        lane_x.append(lanes_in(lo, hi, gut_keys[c]))

    # ---- y positions --------------------------------------------------------
    y = 132
    orch_ids = []
    if orch:
        ox = xs[1] if ncols > 2 else xs[0]
        row_h = 0
        for j in orch:
            jid, h = put_card(p, ox, y, 300, j.key, job_lines(j), accent=kit.DARK,
                              cid="job__" + j.key)
            orch_ids.append(jid)
            ox += 300 + 24
            row_h = max(row_h, h)
        y += row_h + 36
    cont_x = xs[1] - CONTAINER_PAD
    cont_w = (xs[ncols - 2] + widths[ncols - 2] + CONTAINER_PAD) - cont_x
    pipe_text = ((f"<b>Lakeflow SDP pipeline · {esc(pipe.key)}</b>"
                  + (" · serverless" if pipe.serverless else "")
                  + (f" · {esc(pipe.file)}" if pipe.file else ""))
                 if pipe else "<b>Lakeflow SDP pipeline</b> · no bundle resource found")
    probe = {"w": cont_w, "pl": 8, "pr": 8, "size": 13, "text": pipe_text, "valign": "middle"}
    bar_h = max(BAR_H, int(math.ceil((estimate_text_height(probe) + 14) / 2.0) * 2))
    bar_y = y
    top = bar_y + bar_h + CONTAINER_PAD

    placed_bottom = {}
    for c, col in enumerate(columns):
        cx = xs[c] + PANEL_PAD
        cw = widths[c] - 2 * PANEL_PAD
        cy = top + PANEL_HEAD
        for nid in col:
            n = nodes[nid]
            if n["kind"] == "quar":
                cy += CHILD_GAP - CARD_GAP
                _, h = put_card(p, cx + 18, cy, cw - 18, n["title"], n["lines"], fill=kit.BLUSH,
                                stroke=kit.BLUSH_LINE, cid=nid)
            elif n["kind"] == "ext":
                ingest = re.match(r"(Auto Loader|files|Kafka|python|snapshot|view|sql)\b",
                                  n["title"])
                note = ("ingested by this pipeline" if ingest
                        else "existing table - read here, owned elsewhere")
                _, h = put_card(p, cx, cy, cw, n["title"], n["lines"] or [note],
                                fill=kit.SKY, stroke=kit.SKY_LINE, cid=nid)
            else:
                _, h = put_card(p, cx, cy, cw, n["title"], n["lines"], accent=n.get("accent"),
                                logo=n.get("logo"), cid=nid)
            cy += h + CARD_GAP
        placed_bottom[c] = cy - CARD_GAP + PANEL_PAD if col else top + PANEL_HEAD + 40

    layer_bottom = max([placed_bottom[c] for c in range(1, ncols - 1)] or [top + 120])
    corridor_h = (2 * LANE_EDGE + LANE_STEP * max(0, len(corridor_keys) - 1)
                  if corridor_keys else 0)
    corridor_y = {k: layer_bottom + LANE_EDGE + i * LANE_STEP
                  for i, k in enumerate(corridor_keys)}
    container_bottom = layer_bottom + corridor_h + CONTAINER_PAD

    # panels go UNDER the cards: insert them right after the page head
    head_items = 3  # head() emits the title, the subtitle and the accent rule
    kicker_of = {0: ("Sources", "outside the pipeline"),
                 ncols - 1: ("Serving and edge jobs", "read-only on pipeline tables")}
    under = kit.Page("tmp")
    if ncols > 2:
        under.rect(cont_x, bar_y, cont_w, container_bottom - bar_y, fill=kit.WHITE,
                   stroke=kit.PANEL_LINE, radius=12, id="container")
        under.rect(cont_x, bar_y, cont_w, bar_h, fill=kit.DARK, stroke="none", radius=12,
                   text=pipe_text, size=13, color=kit.WHITE, id="pipeline_bar")
    for c in range(ncols):
        if 0 < c < ncols - 1:
            layer = dom.layers[c - 1]
            in_layer = [t for t in dom.tables if t.layer == layer]
            views = sum(1 for t in in_layer if "view" in t.target)
            sinks = sum(1 for t in in_layer if "sink" in t.target)
            parts = [plural(len(in_layer) - views - sinks, "table"), plural(views, "view")]
            parts += [plural(sinks, "sink")] if sinks else []
            title, kick = layer, " · ".join(x for x in parts if not x.startswith("0 "))
            bottom = layer_bottom
        else:
            title, kick = kicker_of[c]
            bottom = placed_bottom[c]
            if c == 0 and not columns[0]:
                continue
            if c == ncols - 1 and not columns[c]:
                continue
        panel(under, xs[c], top, widths[c], bottom - top, title, kick)
    p.items[head_items:head_items] = [dict(it) for it in under.items]
    for it in p.items[head_items:head_items + len(under.items)]:
        if it["id"].startswith("c"):
            it["id"] = f"u{it['id']}"

    # ---- orchestration + edges ----------------------------------------------
    if ncols > 2:
        bar = _geom(p, "pipeline_bar")
        for jid in orch_ids:
            j = _geom(p, jid)
            nx = (j["x"] + j["w"] / 2.0 - bar["x"]) / bar["w"]
            p.edge(jid, "pipeline_bar", ex=0.5, ey=1, nx=round(nx, 4), ny=0, points=[],
                   color=CONTROL, sw=2)

    route(p, edges, lane_x, corridor_y, resolve_ports(p, edges, lane_x, corridor_y))

    # ---- legend ------------------------------------------------------------
    bottom = max(i["y"] + i["h"] for i in p.items if i["kind"] != "edge")
    legend = ("Orange solid: data flow · orange dashed: lookup, backfill or a read "
              "stated in design/estate.yml · red dashed: dqx error rows to quarantine · "
              "grey: orchestration (pipeline_task). Generated by scripts/design_diagram.py "
              "from config/, resources/ and design/estate.yml - do not edit by hand.")
    p.text(MARGIN, bottom + 24, max(900, cont_w), 36, esc(legend), size=11, align="left")
    return p


def overview_page(est: Estate) -> kit.Page:
    p = kit.Page("1 - Estate overview")
    totals = [count_kinds(d) for d in est.domains]
    p.head(MARGIN, 54, 1200, f"{esc(est.title)} · estate overview",
           " · ".join([plural(len(est.domains), "domain"), plural(len(est.pipelines), "pipeline"),
                       plural(len(est.jobs), "job"),
                       plural(sum(c["tables"] for c in totals), "table"),
                       plural(sum(c["views"] for c in totals), "view"),
                       plural(sum(c["quarantine"] for c in totals), "quarantine table")]))
    cols = ["Orchestration jobs", "Lakeflow pipelines", "Domains", "Edge jobs and notebooks"]
    kick = ["pipeline_task triggers", "resources/*.pipeline.yml", "config/<domain>/ artifacts",
            "spark_python_task / notebook_task"]
    widths = [290, 300, 300, 290]

    rows = []  # (orch jobs, pipeline, domain, edge jobs)
    used_p, used_j = set(), set()
    for d in est.domains:
        pipe = est.pipeline_of(d)
        js = [j for j in est.jobs.values() if est.domain_of_job(j) is d]
        rows.append(([j for j in js if j.is_orchestration], pipe, d,
                     [j for j in js if not j.is_orchestration]))
        if pipe:
            used_p.add(pipe.key)
        used_j.update(j.key for j in js)
    for pk, pipe in est.pipelines.items():
        if pk not in used_p:
            js = [j for j in est.jobs.values() if pk in j.pipelines]
            rows.append((js, pipe, None, []))
            used_j.update(j.key for j in js)
    loose = [j for j in est.jobs.values() if j.key not in used_j]
    if loose:
        rows.append(([j for j in loose if j.is_orchestration], None, None,
                     [j for j in loose if not j.is_orchestration]))

    # edges per gutter: jobs->pipeline (g0), pipeline->domain (g1), domain->edge job (g2)
    reads = set()
    idx = _ref_index(est)
    for jk, spec in (est.overlay.get("jobs") or {}).items():
        for r in (spec or {}).get("reads") or []:
            if r in idx:
                reads.add((idx[r][0].name, jk))
    g_keys = [[], [], [], []]
    for orch, pipe, d, ej in rows:
        if pipe:
            if orch:
                g_keys[0].append(pipe.key)
            if d:
                g_keys[1].append(d.name)
        for j in ej:
            if d and (d.name, j.key) in reads:
                g_keys[2].append(j.key)
    xs, x = [], MARGIN
    for c in range(4):
        xs.append(x)
        x += widths[c] + gutter_width(len(g_keys[c]))
    lane_x = []
    for c in range(3):
        lo = xs[c] + widths[c]
        lane_x.append(lanes_in(lo, xs[c + 1], g_keys[c]))

    top = 132
    y = top + PANEL_HEAD
    ids = []
    for orch, pipe, d, ej in rows:
        row_bottom = y
        placed = [[], None, None, []]
        cy = y
        for j in orch:
            jid, h = put_card(p, xs[0] + PANEL_PAD, cy, widths[0] - 2 * PANEL_PAD, j.key,
                              job_lines(j)[:1], accent=kit.DARK, cid="ojob__" + j.key)
            placed[0].append(jid)
            cy += h + CARD_GAP
        row_bottom = max(row_bottom, cy - CARD_GAP)
        if pipe:
            lines = [("serverless · " if pipe.serverless else "") + f"catalog {pipe.catalog}",
                     pipe.file]
            pid, h = put_card(p, xs[1] + PANEL_PAD, y, widths[1] - 2 * PANEL_PAD, pipe.key,
                              lines, accent=kit.TEAL, cid="pipe__" + pipe.key)
            placed[1] = pid
            row_bottom = max(row_bottom, y + h)
        if d:
            c = count_kinds(d)
            per_layer = " · ".join(
                f"{lay} {sum(1 for t in d.tables if t.layer == lay)}" for lay in d.layers)
            lines = [per_layer, f"{plural(c['tables'], 'table')} · {plural(c['views'], 'view')} · "
                     f"{c['quarantine']} quarantine", d.config_dir + "/"]
            did, h = put_card(p, xs[2] + PANEL_PAD, y, widths[2] - 2 * PANEL_PAD, d.name,
                              lines, accent=kit.GOLD, cid="dom__" + d.name)
            placed[2] = did
            row_bottom = max(row_bottom, y + h)
        cy = y
        for j in ej:
            jid, h = put_card(p, xs[3] + PANEL_PAD, cy, widths[3] - 2 * PANEL_PAD, j.key,
                              job_lines(j)[:1], cid="ejob__" + j.key)
            placed[3].append(jid)
            cy += h + CARD_GAP
        row_bottom = max(row_bottom, cy - CARD_GAP)
        ids.append(placed)
        y = row_bottom + 32
    bottom = y - 32 + PANEL_PAD

    under = kit.Page("tmp")
    for c in range(4):
        panel(under, xs[c], top, widths[c], bottom - top, cols[c], kick[c])
    head_n = 3  # head() emits title, subtitle, accent rule
    for it in under.items:
        it["id"] = "u" + it["id"]
    p.items[head_n:head_n] = under.items

    for (_orch, pipe, d, ej), placed in zip(rows, ids, strict=True):
        if placed[1]:
            for jid in placed[0]:
                flow(p, jid, placed[1], lane_x[0][pipe.key], color=CONTROL, sw=2)
            if placed[2]:
                flow(p, placed[1], placed[2], lane_x[1][d.name], sw=2)
        for j, jid in zip(ej, placed[3], strict=True):
            if d and placed[2] and (d.name, j.key) in reads:
                flow(p, placed[2], jid, lane_x[2][j.key], sw=2, dashed=True)

    # ---- inventory table --------------------------------------------------------
    layers = []
    for d in est.domains:
        for lay in d.layers:
            if lay not in layers:
                layers.append(lay)
    header = ["Domain", "Pipeline", *layers, "Views", "Quarantine", "Jobs"]
    colw = [220, 220] + [90] * len(layers) + [90, 110, 80]
    trows = []
    for d in est.domains:
        pipe = est.pipeline_of(d)
        c = count_kinds(d)
        trows.append([d.name, pipe.key if pipe else "-",
                      *[str(sum(1 for t in d.tables if t.layer == lay)) for lay in layers],
                      str(c["views"]), str(c["quarantine"]),
                      str(sum(1 for j in est.jobs.values() if est.domain_of_job(j) is d))])
    ty = bottom + 40
    p.kicker(MARGIN, ty, 400, "ESTATE INVENTORY")
    th = p.table(MARGIN, ty + 22, colw, 30, header, trows)
    p.text(MARGIN, ty + 22 + th + 18, 1100, 20,
           "Per-domain lineage is on the following pages; delivery and environments on the last. "
           "Generated by scripts/design_diagram.py - do not edit by hand.", size=11)
    return p


def delivery_page(est: Estate, number: int) -> kit.Page:
    dl = est.delivery
    p = kit.Page(f"{number} - Delivery")
    p.head(MARGIN, 54, 1200, "Delivery · from a change to a deployed bundle",
           "GitHub Actions deploys the Declarative Automation Bundle per target; facts from "
           ".github/workflows/, targets/ and the Makefile")
    top = 132
    rail_x, rail_w = MARGIN, 300
    y = top
    ids = {}
    ids["author"], h = put_card(p, rail_x, y, rail_w, "1 · Author on a branch",
                                ["config/<domain>/<layer>/<table>.yml + resources/*.yml",
                                 "feature/<slug> branch, never main"], accent=kit.DARK,
                                cid="d_author")
    y += h + 30
    chain = dl.get("chain") or []
    ci_lines = [" → ".join(["ci-cd.yml", *chain]) if dl["triggers"] else "no ci-cd.yml found"]
    if dl.get("dispatch"):
        ci_lines.append("manual dispatch: pick the target")
    ids["ci"], h = put_card(p, rail_x, y, rail_w, "2 · CI/CD workflow", ci_lines,
                            accent=kit.DARK, cid="d_ci")
    y += h
    others = [w for w in dl["workflows"] if w != "ci-cd.yml" and w not in chain]
    if others:
        _, oh = put_card(p, rail_x, y + 26, rail_w, "Other workflows (no deploy)", [", ".join(others)],
                         fill=kit.PANEL, stroke=kit.PANEL_LINE, cid="d_other_wf")
        y += 26 + oh
    rail_bottom = y

    env_x = rail_x + rail_w + 110
    env_w = 420
    ey = top
    step = 3
    env_ids = []
    trig_by_target: dict[str, list] = {}
    for t in dl["triggers"]:
        trig_by_target.setdefault(t["target"], []).append(t)
    for tgt in dl["targets"]:
        trigs = trig_by_target.get(tgt["name"], [])
        lines = []
        for t in trigs:
            lines.append(f"{t['trigger']} → " + ("deploy" if t["deploy"] else "CI only, no deploy"))
        if tgt["name"] in dl.get("auto_approve", []):
            lines.append("destructive changes auto-approved")
        elif dl.get("auto_approve"):
            lines.append("destructive changes need a human review")
        lines.append(f"databricks bundle deploy -t {tgt['name']}"
                     + (f" · mode {tgt['mode']}" if tgt["mode"] else ""))
        title = f"{step} · deploy to {tgt['name']}"
        h = max(48, card_height(env_w - 32, card_text(title, lines), 16))
        box_h = 40 + 14 + h + 16
        p.rect(env_x, ey, env_w, box_h, fill=kit.PANEL, stroke=kit.PANEL_LINE, radius=12)
        p.rect(env_x, ey, env_w, 40, fill=kit.DARK, stroke="none", radius=12,
               text=f"<b>{esc(tgt['name'].upper())} ENVIRONMENT · Databricks</b>",
               size=13, color=kit.WHITE)
        cid, _ = put_card(p, env_x + 16, ey + 40 + 14, env_w - 32, title, lines,
                          cid=f"d_env_{tgt['name']}")
        env_ids.append(cid)
        ey += box_h + 26
        step += 1

    lanes = lanes_in(rail_x + rail_w, env_x, env_ids)
    p.edge(ids["author"], ids["ci"], ex=0.5, ey=1, nx=0.5, ny=0, points=[], color=CONTROL, sw=2)
    for cid in env_ids:
        flow(p, ids["ci"], cid, lanes[cid], color=CONTROL, sw=2)

    # ---- operations notes from the Makefile help ------------------------------
    notes_y = max(rail_bottom, ey - 26) + 40
    mk = dl["make"]
    profiles = [f"make {t}: {mk[t]}" for t in ("deploy", "run", "run-local", "validate-connect")
                if t in mk]
    ops = [f"make {t}: {mk[t]}" for t in ("bootstrap-uc", "validate", "destroy") if t in mk]
    guards = [f"make {t}: {mk[t]}" for t in ("check-design", "check-skills", "check-lockstep")
              if t in mk]
    nx = MARGIN
    for title, lines in (("Execution profiles", profiles), ("Environment operations", ops),
                         ("Repository gates", guards)):
        if not lines:
            continue
        put_card(p, nx, notes_y, 420, title, lines)
        nx += 420 + 24
    return p


def implementation_pages(est: Estate) -> list[kit.Page]:
    pages = [overview_page(est)]
    for i, d in enumerate(est.domains, start=2):
        pages.append(domain_page(est, d, i))
    pages.append(delivery_page(est, len(pages) + 1))
    return pages


# --------------------------------------------------------------------------- #
# Emit, audit, check
# --------------------------------------------------------------------------- #

def emit(pages: list[kit.Page]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.drawio"
        kit.to_drawio(pages, str(path))
        return path.read_text(encoding="utf-8").replace('host="Claude"', 'host="datalab"') + "\n"


def wide_tokens(p: kit.Page) -> list[str]:
    """The kit's audit estimates wrapped HEIGHT; a single unbreakable token (a
    path, a dotted name) wider than its box clips SIDEWAYS instead. Flag it."""
    out = []
    for it in p.items:
        if it["kind"] not in ("rect", "text") or not (it.get("text") or "").strip():
            continue
        usable = it["w"] - it.get("pl", 0) - it.get("pr", 0) - 8
        for seg in re.split(r"<br\s*/?>", it["text"]):
            plain = html.unescape(re.sub(r"<[^>]+>", "", seg))
            size = float(it["size"])
            m = re.search(r"font-size:\s*([\d.]+)px", seg)
            if m:
                size = max(size, float(m.group(1)))
            for tok in re.split(r"[\s\u200b]+", plain):
                if len(tok) * size * 0.56 > usable:
                    out.append(f"OVERFLOW-X {it['kind']} at ({it['x']:.0f},{it['y']:.0f}) "
                               f"{it['w']:.0f}px wide cannot fit the token {tok[:50]!r}")
    return out


def audit_pages(pages: list[kit.Page]) -> list[str]:
    problems = []
    for p in pages:
        problems.extend(f"{p.name}: {m}" for m in wide_tokens(p))
        for msg in layout_audit(p, quiet=True):
            if msg.startswith("SLACK"):
                continue  # a judgement call; the preview is where to look
            problems.append(f"{p.name}: {msg}")
        buf = io.StringIO()
        with redirect_stdout(buf):
            audit_arrows(p)
        for line in buf.getvalue().splitlines():
            if line.startswith("ARROW ") and "AUDIT" not in line:
                problems.append(f"{p.name}: {line}")
        problems.extend(f"{p.name}: {m}" for m in overlap_findings(p))
        if any(i["kind"] == "edge" and i["color"] not in (FLOW, CONTROL, QUARANTINE, kit.EDGE)
               for i in p.items):
            problems.append(f"{p.name}: an arrow uses a colour outside the legend")
    return problems


def build_all(root: Path, spec_variant: list | None = None,
              estate: Estate | None = None) -> dict[Path, list[kit.Page]]:
    """Both diagrams as page models. `estate` lets a caller that cannot parse
    YAML (the stdlib-only adopter scaffold) hand in the estate it just wrote."""
    import design_spec

    est = estate or discover(root)
    errors = validate_overlay(est)
    if errors:
        raise SystemExit("\n".join(errors))
    return {IMPL: implementation_pages(est), SPEC: design_spec.pages(spec_variant)}


def render_files(root: Path, spec_variant: list | None = None,
                 estate: Estate | None = None) -> tuple[dict[Path, str], list[str]]:
    built = build_all(root, spec_variant, estate)
    problems = []
    for pages in built.values():
        problems.extend(audit_pages(pages))
    return {rel: emit(pages) for rel, pages in built.items()}, problems


def preview(root: Path, out: Path, scale: float = 1.5) -> list[Path]:
    """HTML twin + one PNG per page (needs playwright). What you LOOK at."""
    from render import shoot

    out.mkdir(parents=True, exist_ok=True)
    files = []
    for rel, pages in build_all(root).items():
        html_path = out / f"{rel.stem}.html"
        kit.to_html(pages, str(html_path))
        for i, png in enumerate(shoot(str(html_path), str(out), scale, rel.stem)):
            files.append(Path(png))
            _ = i
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate design/*.drawio")
    mode.add_argument("--check", action="store_true", help="fail if stale, edited or not clean")
    mode.add_argument("--preview", metavar="DIR", help="write the HTML twin + PNGs to DIR")
    ap.add_argument("--root", default=str(REPO_ROOT))
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    if a.preview:
        for f in preview(root, Path(a.preview)):
            print(f"wrote {f}")
        print("Now LOOK at every PNG: the audit finds size mistakes, only eyes find ugly.")
        return 0

    files, problems = render_files(root)
    if problems:
        print("design diagrams: the layout audit is not clean (fix the generator, not the XML):")
        for msg in problems:
            print("  " + msg)
        return 1
    if a.write:
        for rel, text in files.items():
            (root / rel).write_text(text, encoding="utf-8")
            print(f"wrote {rel}")
        return 0

    stale = []
    for rel, text in files.items():
        current = (root / rel).read_text(encoding="utf-8") if (root / rel).exists() else ""
        if current != text:
            stale.append(rel)
            diff = difflib.unified_diff(current.splitlines(), text.splitlines(),
                                        f"committed/{rel}", f"generated/{rel}", lineterm="", n=1)
            print("\n".join(list(diff)[:40]))
    if stale:
        print(f"\n{', '.join(map(str, stale))} differ from what the estate generates.\n"
              "The .drawio files are GENERATED - never edit their XML. Change config/, "
              "resources/, design/estate.yml or scripts/design_diagram.py / design_spec.py "
              "(drawio-architecture-designer skill), then run `make design` and commit.")
        return 1
    print("design diagrams are current with the estate and their layout audit is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
