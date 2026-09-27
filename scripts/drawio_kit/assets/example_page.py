"""example_page.py — a working page that exercises every component.

Copy this next to your own page modules as a starting point, or just read it to
see the vocabulary in use. Render it with:

    python <skill>/scripts/render.py --pages example_page --out out \
        --name example.drawio

Everything is absolute pixel geometry. Lay out on a grid you decide up front
(here: 40px page margin, 4 columns, 16px gutters inside panels) and keep the
numbers in named variables so a column can be moved without hunting.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
from drawio_kit import *  # noqa: E402,F403


def build():
    p = Page("1 · Platform Overview")

    # Title block: red rule, title, one-line subtitle, then a full-width strip
    # of the identifiers a reader needs to trust the diagram.
    p.head(40, 54, 1400, "Acme Analytics Platform",
           "How order and CRM data reaches the warehouse and the people who "
           "use it")
    p.rect(40, 134, 1780, 36, fill=WHITE, stroke=LINE, radius=8, size=12.5,
           color=MUTED, align="center",
           text='Environment <b style="color:%s">acme_prod</b> &nbsp;·&nbsp; '
                'Region eu-west-1 &nbsp;·&nbsp; As-built March 2026' % INK)

    Y = 196
    SRC_X, SRC_W = 40, 260
    PLT_X, PLT_W = 340, 1080
    CON_X, CON_W = 1460, 360
    IX, IW = PLT_X + 16, PLT_W - 32
    ROW = [244, 322, 400]
    CH = 66

    # --- sources: a light panel holding white logo cards ------------------
    p.panel(SRC_X, Y, SRC_W, 286, "Data Sources", "2 SYSTEMS + 1 FILE FEED")
    s_db = p.logocard(SRC_X + 14, ROW[0], SRC_W - 28, CH, L["mysql"],
                      "MySQL · orders", ["14 tables · CDC enabled"],
                      lw=34, lh=24)
    s_crm = p.logocard(SRC_X + 14, ROW[1], SRC_W - 28, CH, L["hubspot"],
                       "HubSpot CRM", ["contacts · deals"], lw=34, lh=20)
    p.logocard(SRC_X + 14, ROW[2], SRC_W - 28, CH, L["google_sheets"],
               "Google Sheets", ["fx_rates reference"], lw=22, lh=26)

    # --- the platform: dark title bar + tinted functional zones -----------
    p.rect(PLT_X, Y, PLT_W, 560, fill=WHITE, stroke=PANEL_LINE, radius=12)
    p.rect(PLT_X, Y, PLT_W, 44, fill=DARK, stroke="none", radius=10,
           text="<b>Acme Lakehouse</b>", size=14, color=WHITE, align="left",
           pl=58)
    p.img(PLT_X + 18, Y + 8, 28, 28, L["databricks"])

    p.rect(IX, 252, IW, 100, fill=WHITE, stroke=CARD_LINE, radius=10)
    p.kicker(IX + 16, 262, 600, "ORCHESTRATION · CI/CD")
    for k, lab in enumerate(["Scheduled Jobs", "Asset Bundles",
                             "GitHub Actions", "Serverless SQL"]):
        p.chip(IX + 16 + k * 256, 288, 240, 44, lab, size=11.5)

    # Medallion strip: coloured header over a white body, arrows between.
    p.rect(IX, 364, IW, 240, fill=PANEL, stroke=CARD_LINE, radius=10)
    p.kicker(IX + 16, 374, 700, "PROCESS &amp; TRANSFORM")
    MW, MSTEP = 320, 344
    layers = [(BRONZE, "BRONZE", "raw", ["<b>41 tables</b>", "landed as-is",
                                         "source schema preserved"]),
              (SILVER, "SILVER", "clean", ["<b>18 tables</b>", "typed, deduped",
                                           "PII masked"]),
              (GOLD, "GOLD", "marts", ["<b>5 aggregates</b>", "revenue · funnel",
                                       "cohort · churn"])]
    bodies = []
    for k, (col, label, schema, lines) in enumerate(layers):
        x = IX + 16 + k * MSTEP
        p.rect(x, 398, MW, 28, fill=col, stroke="none", radius=6,
               text="<b>%s</b>" % label, size=11.5, color=WHITE)
        bid = p.rect(x, 426, MW, 116, fill=WHITE, stroke=CARD_LINE, radius=8,
                     text='<font color="%s" style="font-size:10.5px">%s</font>'
                          "<br>%s" % (FAINT, schema, "<br>".join(lines)),
                     size=11, color=MUTED, align="left", valign="top",
                     pl=14, pr=40, pt=12)
        p.img(x + MW - 32, 436, 22, 22, L["delta_lake"])
        bodies.append(bid)
    for a, b in zip(bodies, bodies[1:]):
        p.edge(a, b, color=FLOW, sw=2)

    p.rect(IX + 16, 552, IW - 32, 40, fill=BLUSH, stroke=BLUSH_LINE, radius=8,
           text="<b>Data quality</b> &nbsp; 22 expectation rules; failing rows "
                "route to quarantine so the stream keeps moving.",
           size=11.5, color=INK, align="left", pl=16)

    p.rect(IX, 620, IW, 116, fill=LILAC, stroke=LILAC_LINE, radius=10)
    # official asset (assets/unity_catalog.jpg) — keep the ~2.08:1 box ratio
    p.img(IX + 12, 632, 56, 27, L["unity_catalog"])
    p.text(IX + 78, 632, 500, 27, "<b>Governance</b>", size=13, color=INK)
    for k, lab in enumerate(["RBAC — 5 personas", "PII masking",
                             "Lineage &amp; audit"]):
        p.chip(IX + 16 + k * 344, 662, 332, 38, lab, size=11.5)

    # --- consumption ------------------------------------------------------
    p.panel(CON_X, Y, CON_W, 286, "Consumption", "SERVERLESS SQL")
    c_bi = p.logocard(CON_X + 14, ROW[0], CON_W - 28, CH, L["dashboards"],
                      "BI Dashboards", ["9 published"], lw=24, lh=24)
    p.logocard(CON_X + 14, ROW[1], CON_W - 28, CH, L["genie"],
               "Natural-language Q&amp;A", ["2 curated spaces"], lw=24, lh=24)
    p.logocard(CON_X + 14, ROW[2], CON_W - 28, CH, L["slack"],
               "Alerts → Slack", ["7 metric alerts"], lw=24, lh=24)

    # --- a card with a coloured spine, a reference note, and a table -------
    p.accentcard(40, 512, 260, 100, FLOW, "Refresh",
                 ["CDC continuous", "Marts every 30 min", "~9 min run"])
    p.note(40, 628, 260, 108, "Out of scope",
           ["billing · legacy_crm", "Not modelled."], fill=PANEL,
           stroke=PANEL_LINE)
    p.note(CON_X, 512, CON_W, 108, "Baselines",
           ["Orders &nbsp; ~12k / day", "Revenue &nbsp; ~£380k / day"],
           logo=L["clock"], fill=PANEL, stroke=PANEL_LINE)

    p.kicker(CON_X, 646, 300, "OWNERSHIP")
    p.table(CON_X, 668, [200, 160], 28, ["domain", "owner"],
            [("orders", "data-eng"), ("crm", "revops"),
             ("finance", "finance-bi")], size=11)

    # --- flow arrows ------------------------------------------------------
    p.edge(s_db, bodies[0], color=FLOW, sw=2, nx=0.0, ny=0.3,
           points=[(322, 277), (322, 461)])
    p.edge(s_crm, bodies[0], color=FLOW, sw=2, nx=0.0, ny=0.7,
           points=[(322, 355), (322, 507)])
    p.edge(bodies[2], c_bi, color=FLOW, sw=2, ey=0.5, nx=0.0, ny=0.5,
           points=[(1440, 484), (1440, 277)])
    return p
