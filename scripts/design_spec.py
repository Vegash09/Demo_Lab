"""The conceptual design spec - design/01_design_config_driven_medallion.drawio.

Five pages (Context -> Author -> Generate -> Run -> Ship), laid out through the
vendored drawio-architecture-designer kit (scripts/drawio_kit/) and written by
`scripts/design_diagram.py --write` (`make design`). The TEXT below is the spec;
the positions are computed from it, so a longer bullet grows its card instead
of clipping. Edit the text here - never the generated .drawio.

`pages(variant)` takes (old, new) replacements the adopter scaffold uses to
repoint the worked-example references at the adopter's own domain.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "drawio_kit"))

import drawio_kit as kit  # noqa: E402
from render import estimate_text_height  # noqa: E402

W = 1620          # content width
X = 40            # page margin
GAP = 30

# --------------------------------------------------------------------------- #
# The spec text (HTML, as draw.io labels take it). All text is black; hierarchy
# comes from size and weight (drawio-architecture-designer output rule 1).
# --------------------------------------------------------------------------- #

TEXT: dict[str, str] = {
    "p1_title": "datalab · Config-Driven Medallion Framework · ONE YAML artifact per table → Lakeflow SDP",
    "p1_sub": "A medallion (bronze → silver → gold) lakehouse framework where the target table IS the unit of work. Author its YAML artifact; the framework generates the pyspark.pipelines datasets, the dqx quality gates, and the AUTO CDC flows. Ships as a Declarative Automation Bundle deployed by GitHub OIDC CI/CD.",
    "p1_today": "<b style='font-size:14px;'>WHAT EXISTS TODAY</b><br><br>• Framework: the external <tt>datalab</tt> dependency (the datalab-framework repo): reusable, zero domain code<br><br>• Two reference domains: <tt>projects/customer_sales/</tt> (bronze → silver (AUTO CDC SCD1) → gold, dqx valid/quarantine, edge jobs + notebook) and <tt>projects/sales/</tt> (pipeline-only feature showcase)<br><br>• Three authoring lanes: SDP pipelines, python-file jobs, notebooks<br><br>• Three execution profiles: Databricks, OSS spark-pipelines, Databricks Connect<br><br>• Deploy: DAB → GitHub OIDC → dev / stage / prod",
    "p1_goals": "<b style='font-size:14px;'>DESIGN GOALS</b><br><br>• A target table = <b>ONE artifact</b> (columns, dqx rules, CDC target) authored from natural language<br><br>• <b>Framework vs domain</b> strict separation — the framework lifts into any project untouched<br><br>• <b>Single-writer invariant</b> — every UC table has exactly one owning lane<br><br>• Config validated by Pydantic + dqx — the SAME loader in CI, pytest, and the pipeline<br><br>• No hand-written <tt>dp.*</tt> / MERGE unless the capability matrix says the framework cannot express it",
    "p1_drivers": "<b style='font-size:14px;'>WHY (DRIVERS)</b><br><br>• Config-driven beats hand-written pipelines — reviewable, statically validated, uniform across tables<br><br>• Data quality as <b>evidence</b> — dqx valid/quarantine split with _errors structs<br><br>• <b>Run anywhere</b> — local OSS for a fast inner loop, Connect for live validation, Databricks for prod<br><br>• Reproducible deps — uv end to end (<tt>uv.lock</tt>, CI <tt>--frozen</tt>)<br><br>• Agents author tables safely behind protected-file + branch-first guards",
    "p1_detail": "<b style='font-size:15px;'>THE FLOWSPEC PATTERN  ·  config/&lt;catalog&gt;/&lt;schema&gt;/&lt;table&gt;.yml is the source of truth</b><br><br>Every target table is declared by ONE YAML artifact (file name == table name; folder path mirrors the UC namespace <tt>&lt;catalog&gt;.&lt;schema&gt;.&lt;table&gt;</tt>). The artifact declares:<br><br>&nbsp;&nbsp;→ <b>source(s)</b> — cloud_files / files / table / view / kafka (single <tt>source:</tt> or fan-in <tt>sources:</tt>)<br>&nbsp;&nbsp;→ <b>columns</b> — source→target names, data types (always <tt>try_cast</tt>), per-column dqx rules<br>&nbsp;&nbsp;→ <b>transform</b> steps (registry names) + table-level <b>quality</b> checks<br>&nbsp;&nbsp;→ optional <b>backfill:</b> once-flows (the recreation path + audit trail)<br>&nbsp;&nbsp;→ <b>target</b> kind — streaming_table [+cdc | +cdc_from_snapshot] / materialized_view / temporary_view / delta_sink / kafka_sink<br><br><b>datalab.framework.generate</b> turns the validated config into Lakeflow SDP datasets. Business logic lives in <tt>src/&lt;catalog&gt;_etl/transforms/</tt> as pure <tt>@transform</tt> functions; custom dqx in <tt>checks/</tt>. The per-domain <tt>transformations/pipeline.py</tt> is 3 lines. <b>Never <tt>import dlt</tt></b> — this repo standardizes on <tt>pyspark.pipelines</tt>.",
    "p1_struct": "<b style='font-size:13px;'>How this file is structured</b> — Pages 2-5 walk the flow:&nbsp; <b>AUTHOR</b> (Page 2: artifact anatomy + the 3-question lane router) &nbsp;→&nbsp; <b>GENERATE</b> (Page 3: YAML → pyspark.pipelines datasets) &nbsp;→&nbsp; <b>RUN</b> (Page 4: medallion runtime + the three execution profiles) &nbsp;→&nbsp; <b>SHIP</b> (Page 5: bundle deploy + RBAC / ABAC governance).",
    "p1_footer": "<b>The artifact is the contract. Author it; the framework owns materialization. Full reference + SDP capability matrix: docs/FRAMEWORK.md.  The implemented system is mapped in design/02_implementation_end_to_end.drawio.</b>",
    "p2_title": "STAGE 1 of 4 · AUTHOR · The YAML artifact anatomy + the 3-question lane router",
    "p2_sub": "Adding or changing a table = authoring its artifact, not writing Python. Use the author-ldp-artifact skill to turn a natural-language request into the YAML below. Route every new target through the 3-question router first.",
    "p2_art_hdr": "A  ·  Artifact anatomy  —  config/&lt;catalog&gt;/&lt;schema&gt;/&lt;table&gt;.yml  (one file == one target table)",
    "p2_art": "<b>source:</b> / <b>sources:</b>&nbsp;&nbsp; one input or a fan-in list (replaces UNION).<br>&nbsp;&nbsp;kinds: <tt>cloud_files</tt> (Auto Loader) · <tt>files</tt> · <tt>table</tt> · <tt>view</tt> · <tt>kafka</tt>. Each flow has a name — <i>flow names are streaming-checkpoint identities</i>.<br><br><b>columns:</b>&nbsp;&nbsp; the source→target mapping. <tt>name</tt> / <tt>source</tt> / <tt>type</tt> (cast with <tt>try_cast</tt> so ANSI-mode bad values become NULL, not a stream failure) + per-column <b>quality:</b> dqx rules.<br><br><b>transform:</b>&nbsp;&nbsp; ordered step list referencing <tt>@transform</tt>-registered pure functions in the domain package.<br><br><b>quality:</b>&nbsp;&nbsp; table-level dqx checks (dqx metadata format). One rules list drives BOTH the target filter and the <tt>&lt;table&gt;_quarantine</tt> split.<br><br><b>backfill:</b>&nbsp;&nbsp; optional once-flows (batch source; streaming when the target has <tt>cdc:</tt>). They re-run on full refresh by design.<br><br><b>target:</b>&nbsp;&nbsp; the kind + its options (see C below) — <tt>cdc</tt> / <tt>cdc_from_snapshot</tt> keys, sequence_by, SCD type.",
    "p2_router_hdr": "B  ·  Route every new target — the 3-question router",
    "p2_router": "<b>1.</b> Is the output a managed Delta table in the medallion, derivable from upstream datasets?<br>&nbsp;&nbsp;→ <b>SDP</b> (mandatory). Backfills included as <tt>backfill:</tt> once-flows.<br><br><b>2.</b> Is it a side-effectful action (export to a volume / external system, API pull into landing, non-SDP table maintenance) running headless on a schedule?<br>&nbsp;&nbsp;→ <b>python-file</b> (<tt>spark_python_task</tt>, <tt>src/jobs/</tt>).<br><br><b>3.</b> Must a human read the run output and decide?<br>&nbsp;&nbsp;→ <b>notebook</b> (<tt>notebook_task</tt>, on-demand only — no trigger).<br><br><i>When in doubt: SDP. Exploration with no managed target stays out of the bundle.</i>",
    "p2_inv": "<b>Single-writer invariant + don'ts</b><br><br>• Every UC table has exactly ONE owning lane. Jobs and notebooks may READ SDP-owned tables, never WRITE them — a <tt>.saveAsTable</tt> on an SDP streaming table corrupts pipeline state.<br><br>• Repaired / backfill data re-enters via the landing volume or a <tt>backfill:</tt> flow — never a job write.<br><br>• No <tt>import dlt</tt>, no hand-written MERGE, no hardcoded catalogs/paths (use pipeline <tt>configuration</tt> + <tt>pipeline_conf</tt>).",
    "p2_targets_hdr": "C  ·  Target kinds (the YAML target: block) — the SDP surface the framework can express",
    "p2_targets": "<b>streaming_table</b> — <tt>@dp.table</tt>, append/streaming ingest (Auto Loader, Kafka).&nbsp;&nbsp;|&nbsp;&nbsp; <b>streaming_table + cdc</b> — <tt>create_streaming_table</tt> + <tt>create_auto_cdc_flow</tt> (keys + sequence_by; SCD1/SCD2) — replaces MERGE.<br><br><b>streaming_table + cdc_from_snapshot</b> — <tt>create_auto_cdc_from_snapshot_flow</tt> for periodic FULL dumps (nightly extracts).&nbsp;&nbsp;|&nbsp;&nbsp; <b>materialized_view</b> — <tt>@dp.materialized_view</tt> (gold aggregates, batch).<br><br><b>temporary_view</b> — <tt>@dp.temporary_view</tt> (pipeline-scoped).&nbsp;&nbsp;|&nbsp;&nbsp; <b>delta_sink</b> / <b>kafka_sink</b> — streaming publish (append-only; never cleared by full refresh, so <tt>backfill:</tt> is rejected on sinks).<br><br><i>Anything the matrix says is genuinely out of scope (e.g. Kinesis / Pub/Sub sources) is the rare case for the author-sdp-pipeline skill — extend the framework first.</i>",
    "p2_footer": "<b>Author the artifact, add any new @transform with a unit test, then: make validate-configs lint test validate. Verify interactively with run_dataset / make validate-connect — no deploy needed.</b>",
    "p3_title": "STAGE 2 of 4 · GENERATE · datalab.framework turns the YAML into pyspark.pipelines datasets",
    "p3_sub": "The same loader runs in CI, pytest (local Spark) and the deployed pipeline. Dataset functions RETURN a DataFrame — the engine owns materialization (no .write / .saveAsTable / .start / .collect inside them).",
    "p3_models": "<b>1 · models.py</b><br><br>Pydantic config contract.<br>Parses + validates every artifact (and domain.yml).<br><br><i>make validate-configs fails fast on a bad rule or type.</i>",
    "p3_loader": "<b>2 · loader.py + registry</b><br><br>Reads domain.yml imports; resolves <tt>@transform</tt> / <tt>@check_function</tt> / <tt>@snapshot_source</tt> by name.<br><br><i>Framework hardcodes no domain module.</i>",
    "p3_gen": "<b>3 · generator.generate()</b><br><br>Builds the graph: readers → column map (try_cast) → transform steps → dqx → target.<br><br>Routes on <tt>datalab.profile</tt> (see the profile box below).",
    "p3_datasets": "<b>4 · SDP datasets</b><br><br><tt>@dp.table</tt> (streaming)<br><tt>@dp.materialized_view</tt><br><tt>create_streaming_table</tt> + <tt>create_auto_cdc_flow</tt><br><br><i>Functions return a DataFrame.</i>",
    "p3_profile": "<b>Profile routing</b><br><br><tt>datalab.profile</tt>:<br>• <b>databricks</b> → dp.* datasets (default)<br>• <b>local</b> → batch materialized views (framework/local.py)<br><br><tt>compat.py</tt> guards Databricks-only knobs locally.",
    "p3_dq_hdr": "dqx data quality  —  ONE rules list drives valid + quarantine (dp.expect_* is retired here)",
    "p3_dq": "<b>framework/dq.py</b> routes the artifact's <tt>quality.checks</tt> through databrickslabs/dqx.&nbsp;&nbsp; <b>criticality: error</b> rows are dropped from the target and land in <tt>&lt;dataset&gt;_quarantine</tt> with <tt>_errors</tt> evidence structs; <b>warn</b> rows flow through flagged.<br><br>Default <tt>quarantine.include_warnings: false</tt> keeps quarantine == exactly the dropped rows. With fan-in <tt>sources:</tt> every flow feeds the same quarantine. Optional <tt>*_dq_metrics</tt> MV. Locally dqx runs with a mocked WorkspaceClient and static run_time / run_id overwrites (removing them breaks MV incrementalization).",
    "p3_cdc_hdr": "AUTO CDC  —  upserts without MERGE (the engine owns the merge)",
    "p3_cdc": "<tt>target.cdc</tt> → <tt>create_streaming_table</tt> + <tt>create_auto_cdc_flow(target=..., source=..., keys=[...], sequence_by=...)</tt>.&nbsp;&nbsp; <tt>target.cdc_from_snapshot</tt> → <tt>create_auto_cdc_from_snapshot_flow</tt> for periodic full snapshots.<br><br>Flow names are checkpoint identities — renaming a fan-in / backfill flow (or converting single-source ↔ fan-in) abandons state and reprocesses from scratch; pair such a change with a deliberate full refresh. Streaming FROM a CDC/SCD table needs <tt>options: {skipChangeCommits: true}</tt>.",
    "p3_footer": "<b>The framework is an external dependency: change it in the datalab-framework repo (its docs/FRAMEWORK.md is the doc of record); after a framework bump, make sync-schemas regenerates the vendored schemas/*.json.</b>",
    "p4_title": "STAGE 3 of 4 · RUN · the medallion at runtime + the three execution profiles",
    "p4_sub": "The customer_sales_etl pipeline runs serverless on Databricks (environment_version 4). The same artifacts also run off-Databricks for a fast inner loop — with deliberate fidelity gaps noted below.",
    "p4_land": "<b>Landing volume</b><br><br>/Volumes/&lt;catalog&gt;/\u200blanding/sales/customers/<br><br>Raw JSON files arrive out-of-band; Auto Loader source.",
    "p4_bronze": "<b>bronze.customers_raw</b><br><br>@dp.table (streaming) via cloud_files.<br><br>Raw ingest, minimal shaping.",
    "p4_silver": "<b>silver.customers</b><br><br>create_streaming_table + create_auto_cdc_flow (SCD1).<br>dqx gate keeps valid rows.<br><br><i>Upserts without MERGE.</i>",
    "p4_gold": "<b>gold.customers_by_city</b><br><br>@dp.materialized_view.<br><br>Business-level aggregates for readers / BI / exports.",
    "p4_refresh": "<b>customer_sales_etl_refresh</b><br><br>pipeline_task, daily trigger (paused in dev).<br><br>Edge jobs read gold; notebook triages quarantine.",
    "p4_quar": "<b>silver.customers_quarantine</b><br><br>dqx error rows + _errors evidence — the dropped rows, exactly.",
    "p4_e1": "Auto Loader",
    "p4_e2": "AUTO CDC",
    "p4_e3": "aggregate",
    "p4_e4": "error rows",
    "p4_matrix_hdr": "Execution profiles  —  capability fidelity (datalab.profile)",
    "p4_prof_db": "<b>databricks (default)</b><br><br>deploy + run (make deploy / run).<br><br>• Auto Loader ✓<br>• AUTO CDC ✓<br>• dqx quarantine ✓<br>• delta/kafka sinks ✓<br><br><i>Full fidelity — the production path.</i>",
    "p4_prof_local": "<b>local — OSS spark-pipelines</b><br><br>make run-local (generates spark-pipeline.yml).<br><br>• Materializes bronze → silver → gold as BATCH MVs on sample data<br>• <b>No</b> AUTO CDC dedup (a window over an in-graph dataset fails graph registration)<br>• <b>No</b> dqx gate (dqx reads df.columns / df.isStreaming — forbidden in an SDP query fn)<br>• <b>No</b> Auto Loader / sinks<br><br><i>Validates mapping + transform shape only.</i>",
    "p4_prof_conn": "<b>connect — Databricks Connect</b><br><br>make validate-connect.<br><br>• Runs run_dataset on a LIVE cluster from an isolated, out-of-lock overlay<br>• Validates transforms + dqx against real UC data<br>• Never installed into the dev venv / uv.lock (conflicts with pyspark)<br><br><i>CDC / once semantics still verify via a dev refresh.</i>",
    "p4_footer": "<b>Local OSS pyspark.pipelines lacks Databricks-only symbols (AUTO CDC fns, once, MV refresh_policy); compat.py drops the knobs locally for shape-only inspection. CDC / dqx semantics verify on a dev refresh.</b>",
    "p5_title": "STAGE 4 of 4 · SHIP · Declarative Automation Bundle, GitHub OIDC CI/CD, RBAC + ABAC",
    "p5_sub": "One bundle (databricks.yml + resources/*.yml) deploys the whole domain to dev / stage / prod. CD authenticates with GitHub OIDC — no long-lived Databricks secret in GitHub. Access governance has three layers, each with one home.",
    "p5_dab": "<b style='font-size:13px;'>Declarative Automation Bundle</b><br><br>• <tt>databricks.yml</tt> — variables (catalog / schemas / paths)<br>• <tt>rbac.yml</tt> — RBAC: group + permission-level string vars + complex pipeline_permissions / job_permissions (per-target overrides)<br>• <tt>projects/*/resources/*.yml</tt> — 2 SDP pipelines + 3 jobs (refresh / export / quarantine-report)<br>• targets: <b>dev</b> (mode development — [dev user] prefix, trigger paused) · <b>stage</b> · <b>prod</b> (mode production, explicit root_path)<br>• deps: the framework as a versioned wheel from each catalog's <tt>artifacts.wheels</tt> UC Volume (<tt>${var.datalab_wheel}</tt>) + the domain's own <tt>&lt;catalog&gt;_etl</tt> wheel, never <tt>--editable</tt><br><br><i>make validate before pushing bundle changes.</i>",
    "p5_cicd": "<b style='font-size:13px;'>GitHub OIDC CI/CD</b><br><br>• <b>CI</b> (common-ci-steps): ruff + validate-configs + pytest (local Spark) + bundle validate, plus an advisory spark-pipelines dry-run<br>• <b>CD</b> (common-cd-steps → deploy-dab): validate + deploy with optional --var overrides<br>• Auth = <b>GitHub OIDC</b>; the federation subject must match <tt>repo:&lt;owner&gt;/&lt;repo&gt;:environment:&lt;target&gt;</tt><br>• Releases: merge to main → dev · tag vX.Y.Z-rcN → stage · tag vX.Y.Z → prod<br><br><i>Only STRING variables can be --var-overridden (complex cannot).</i>",
    "p5_rbac": "<b>Layer 1 · Workspace-resource RBAC</b><br><br><tt>permissions:</tt> on every bundle resource, driven by the group + permission-level string vars in <tt>rbac.yml</tt> (the complex permissions reference them).<br><br>Both groups AND levels diverge per target (dev demo groups; stage / prod persona groups; prod tightens readers to CAN_VIEW + adds admin_group) and per GitHub Environment (DATALAB_*_GROUP → deploy-dab --var).",
    "p5_uc": "<b>Layer 2 · Unity Catalog RBAC</b><br><br>Grants-as-code in <tt>scripts/bootstrap_uc.py</tt> — idempotent catalog / schema / volume DDL + GRANTs, applied once per target with <tt>make bootstrap-uc</tt>.<br><br>Deliberately out-of-band of the bundle so <tt>bundle destroy</tt> never touches governance state. Readers get silver/gold SELECT + export reads; engineers build the medallion.",
    "p5_abac": "<b>Layer 3 · ABAC (display-only)</b><br><br>Column masks + row filters as SQL under the domain's <tt>sql/abac/</tt>.<br><br><b>Nothing in this repo</b> (CI, agents, scripts) executes them — an admin reviews and applies them manually.<br><br><i>Auto-applying access policy from a code repo is the failure mode this convention prevents.</i>",
    "p5_footer": "<b>Production-sensitive files (the bundle, dependency manifests, framework core, CI/CD, agent harness, docs-of-record) are guarded; the branch-first protocol (no edits on main) is enforced in both agent harnesses and the git pre-commit hook.</b>",
}


# --------------------------------------------------------------------------- #
# Layout primitives - every height is computed from its text
# --------------------------------------------------------------------------- #

def _h(w: float, text: str, size: float, pl: float = 16, pr: float = 14, pt: float = 12,
       valign: str = "top") -> int:
    probe = {"w": w, "pl": pl, "pr": pr, "size": size, "text": text, "valign": valign, "pt": pt}
    return int(-(-(estimate_text_height(probe) + 14) // 2) * 2)


def heading(p: kit.Page, y: float, title: str, sub: str) -> float:
    p.rect(X, y - 14, 54, 5, fill=kit.RED, stroke="none", radius=3)
    p.text(X, y, W, 38, f"<b>{title}</b>", size=24, align="left")
    sh = _h(W, sub, 13.5, pl=0, pr=0, pt=0, valign="middle") - 8
    p.text(X, y + 44, W, sh, sub, size=13.5, align="left")
    return y + 44 + sh + 26


def card(p: kit.Page, x: float, y: float, w: float, text: str, h: float | None = None,
         accent: str | None = None, fill: str = kit.WHITE, stroke: str = kit.LINE,
         size: float = 12) -> tuple[str, float]:
    pl = 22 if accent else 16
    h = h or _h(w, text, size, pl=pl)
    cid = p.rect(x, y, w, h, fill=fill, stroke=stroke, radius=10, text=text, size=size,
                 align="left", valign="top", pl=pl, pr=14, pt=12, pb=10)
    if accent:
        p.rect(x, y + 10, 5, h - 20, fill=accent, stroke="none", radius=3)
    return cid, h


def bar(p: kit.Page, x: float, y: float, w: float, text: str) -> float:
    p.rect(x, y, w, 34, fill=kit.DARK, stroke="none", radius=8, text=f"<b>{text}</b>", size=12.5,
           color=kit.WHITE, align="left", pl=14)
    return y + 34 + 10


def row(p: kit.Page, y: float, keys: list[str], accents: list[str | None], size: float = 12,
        widths: list[float] | None = None) -> tuple[list[str], float]:
    n = len(keys)
    widths = widths or [(W - GAP * (n - 1)) / n] * n
    h = max(_h(w, TEXT[k], size, pl=22 if a else 16) for k, w, a in zip(keys, widths, accents, strict=True))
    ids, x = [], X
    for k, w, a in zip(keys, widths, accents, strict=True):
        cid, _ = card(p, x, y, w, TEXT[k], h=h, accent=a, size=size)
        ids.append(cid)
        x += w + GAP
    return ids, y + h


def footer(p: kit.Page, y: float, key: str) -> None:
    h = _h(W, TEXT[key], 11.5, pl=0, pr=0, pt=0, valign="middle") - 8
    p.text(X, y, W, h, TEXT[key], size=11.5, align="center")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def page1() -> kit.Page:
    p = kit.Page("1 - Context")
    y = heading(p, 54, TEXT["p1_title"], TEXT["p1_sub"])
    _, y = row(p, y, ["p1_today", "p1_goals", "p1_drivers"], [kit.TEAL, kit.GOLD, kit.RED])
    _, h = card(p, X, y + GAP, W, TEXT["p1_detail"], accent=kit.BRONZE)
    y += GAP + h
    _, h = card(p, X, y + 20, W, TEXT["p1_struct"], fill=kit.SAND, stroke=kit.SAND_LINE)
    footer(p, y + 20 + h + 18, "p1_footer")
    return p


def page2() -> kit.Page:
    p = kit.Page("2 - AUTHOR - Artifact + lane router")
    y = heading(p, 54, TEXT["p2_title"], TEXT["p2_sub"])
    left_w, right_w = 1040, W - 1040 - GAP
    rx = X + left_w + GAP
    ya = bar(p, X, y, left_w, TEXT["p2_art_hdr"])
    yb = bar(p, rx, y, right_w, TEXT["p2_router_hdr"])
    h_router = _h(right_w, TEXT["p2_router"], 11.5)
    h_inv = _h(right_w, TEXT["p2_inv"], 11.5, pl=22)
    _, h_art = card(p, X, ya, left_w, TEXT["p2_art"], size=12)
    card(p, rx, yb, right_w, TEXT["p2_router"], h=h_router, size=11.5)
    card(p, rx, yb + h_router + 16, right_w, TEXT["p2_inv"], h=h_inv,
         accent=kit.RED, fill=kit.BLUSH, stroke=kit.BLUSH_LINE, size=11.5)
    h_art = max(h_art, h_router + 16 + h_inv)  # ragged bottoms; next row clears both
    y = ya + h_art + GAP
    y = bar(p, X, y, W, TEXT["p2_targets_hdr"])
    _, h = card(p, X, y, W, TEXT["p2_targets"], size=11.5)
    footer(p, y + h + 18, "p2_footer")
    return p


def page3() -> kit.Page:
    p = kit.Page("3 - GENERATE - YAML to SDP")
    y = heading(p, 54, TEXT["p3_title"], TEXT["p3_sub"])
    keys = ["p3_models", "p3_loader", "p3_gen", "p3_datasets"]
    n, gap = len(keys), 70
    w = (W - gap * (n - 1)) / n
    h = max(_h(w, TEXT[k], 11.5) for k in keys)
    ids, x = [], X
    for k in keys:
        cid, _ = card(p, x, y, w, TEXT[k], h=h, size=11.5,
                      accent=kit.TEAL if k != "p3_datasets" else kit.GOLD)
        ids.append(cid)
        x += w + gap
    for a, b in zip(ids, ids[1:], strict=False):
        p.edge(a, b, color=kit.EDGE, sw=2)
    gx = X + 2 * (w + gap)
    ph = _h(w, TEXT["p3_profile"], 11.5)
    prof, _ = card(p, gx, y + h + 44, w, TEXT["p3_profile"], h=ph, size=11.5,
                   fill=kit.SKY, stroke=kit.SKY_LINE)
    p.edge(prof, ids[2], ex=0.5, ey=0, nx=0.5, ny=1, color=kit.EDGE, sw=2, dashed=True)
    y = y + h + 44 + ph + GAP
    y = bar(p, X, y, W, TEXT["p3_dq_hdr"])
    _, h = card(p, X, y, W, TEXT["p3_dq"], size=11.5, accent=kit.RED)
    y = bar(p, X, y + h + GAP, W, TEXT["p3_cdc_hdr"])
    _, h = card(p, X, y, W, TEXT["p3_cdc"], size=11.5, accent=kit.TEAL)
    footer(p, y + h + 18, "p3_footer")
    return p


def page4() -> kit.Page:
    p = kit.Page("4 - RUN - Medallion + profiles")
    y = heading(p, 54, TEXT["p4_title"], TEXT["p4_sub"])
    keys = ["p4_land", "p4_bronze", "p4_silver", "p4_gold", "p4_refresh"]
    accents = [None, kit.BRONZE, kit.SILVER, kit.GOLD, kit.DARK]
    fills = [kit.SKY, kit.WHITE, kit.WHITE, kit.WHITE, kit.WHITE]
    strokes = [kit.SKY_LINE, kit.LINE, kit.LINE, kit.LINE, kit.LINE]
    gaps = [120, 120, 120, 60]
    w = (W - sum(gaps)) / len(keys)
    h = max(_h(w, TEXT[k], 11.5, pl=22 if a else 16) for k, a in zip(keys, accents, strict=True))
    ids, x = [], X
    for i, k in enumerate(keys):
        cid, _ = card(p, x, y, w, TEXT[k], h=h, size=11.5, accent=accents[i], fill=fills[i],
                      stroke=strokes[i])
        ids.append(cid)
        x += w + (gaps[i] if i < len(gaps) else 0)
    for (a, b), lab in zip(zip(ids[:3], ids[1:4], strict=True), ["p4_e1", "p4_e2", "p4_e3"],
                            strict=True):
        p.edge(a, b, color=kit.FLOW, sw=2, label=TEXT[lab])
    sx = X + 2 * (w + 120)
    qh = _h(w, TEXT["p4_quar"], 11.5)
    q, _ = card(p, sx, y + h + 50, w, TEXT["p4_quar"], h=qh, size=11.5, fill=kit.BLUSH,
                stroke=kit.BLUSH_LINE)
    p.edge(ids[2], q, ex=0.5, ey=1, nx=0.5, ny=0, color="#C0392B", sw=2, dashed=True,
           label=TEXT["p4_e4"], ldx=38, ldy=0)
    y = y + h + 50 + qh + GAP + 10
    y = bar(p, X, y, W, TEXT["p4_matrix_hdr"])
    _, y = row(p, y, ["p4_prof_db", "p4_prof_local", "p4_prof_conn"],
               [kit.TEAL, kit.GOLD, kit.EDGE], size=11.5)
    footer(p, y + 18, "p4_footer")
    return p


def page5() -> kit.Page:
    p = kit.Page("5 - SHIP - Deploy + governance")
    y = heading(p, 54, TEXT["p5_title"], TEXT["p5_sub"])
    _, y = row(p, y, ["p5_dab", "p5_cicd"], [kit.TEAL, kit.DARK], size=11.5)
    _, y = row(p, y + GAP, ["p5_rbac", "p5_uc", "p5_abac"], [kit.BRONZE, kit.SILVER, kit.RED],
               size=11.5)
    footer(p, y + 18, "p5_footer")
    return p


def pages(variant: list[tuple[str, str]] | None = None) -> list[kit.Page]:
    """Build the five spec pages. `variant` = (old, new) text replacements; an
    `old` that matches nothing is an error, so a drifted edit fails loudly."""
    original = dict(TEXT)
    try:
        for old, new in variant or []:
            hits = [k for k, v in TEXT.items() if old in v]
            if not hits:
                raise SystemExit(f"design_spec: variant edit matches no spec text: {old[:60]!r}")
            for k in hits:
                TEXT[k] = TEXT[k].replace(old, new)
        return [page1(), page2(), page3(), page4(), page5()]
    finally:
        TEXT.clear()
        TEXT.update(original)
