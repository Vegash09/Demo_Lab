---
name: query-databricks
description: Inspect live Unity Catalog tables read-only (preview rows, column names/types, DESCRIBE, SHOW TABLES, value distributions) via the opt-in Databricks SQL MCP server while authoring or changing a pipeline table. Use to ground an artifact in real data before writing config/<catalog>/<schema>/<table>.yml — confirm a source table's real columns + types, sanity-check a candidate dqx rule against actual values, or discover what tables a schema holds. NEVER write; this path is read-only and SDP-owned tables have exactly one owning lane.
---

# Query Databricks from the agent (read-only, opt-in MCP)

The `databricks-sql` MCP server (configured in `.mcp.json` / `.cursor/mcp.json`)
lets you run **read-only** SQL and browse Unity Catalog directly from the editor,
against the live workspace. It exists to **ground the authoring workflow** — look
at the real tables before/while you author their downstream artifacts. It is
opt-in and dev-time only; one-time setup + how it authenticates (your Databricks
CLI profile, no token in the repo) is in `docs/AGENT_MCP.md`.

This skill is about WHEN to reach for it and the HARD read-only boundary. The
artifact (`config/<catalog>/<schema>/<table>.yml`) + `make validate-configs`
remain the source of truth — MCP queries inform authoring, they don't replace
validation.

## When to use it (alongside `author-ldp-artifact`)

- **Before authoring a downstream table**, preview its upstream source to get the
  real column names + types + shape — e.g. inspect `silver.customers` before
  writing `gold.customers_by_city`. Map the artifact's `columns:` source→target
  names to what actually exists, not what you assume.
- **Sanity-check a candidate dqx rule** against real values: is `email` ever
  null? what's the `amount` range? does `status` carry values outside the enum
  you were about to enforce? Pick the rule (and its `criticality`) from evidence.
- **Discover a schema's tables** when you don't know the exact name —
  `SHOW TABLES IN <catalog>.<schema>`, then `DESCRIBE` the candidate.
- **Understand an existing output table** by spot-reading it — never to "fix"
  data, only to understand its current shape.

## How

Use the `databricks-sql` MCP tools the server exposes (list catalogs/schemas/
tables, describe a table, run a SELECT). Keep it cheap and read-only:

- Always bound exploratory reads: `SELECT ... FROM <fqn> LIMIT 50`.
- Prefer `DESCRIBE <fqn>` / `SHOW TABLES IN <catalog>.<schema>` for structure —
  cheaper and exactly what authoring needs.
- Fully-qualify names (`<catalog>.<schema>.<table>`); the catalog matches the
  bundle `var.catalog` for the target the server points at.
- You only see what your Databricks identity is granted — Unity Catalog grants
  govern every read (see `rbac.yml` / `scripts/bootstrap_uc.py`).

## Hard guardrails (read-only — non-negotiable)

- **Read-only ONLY.** Never issue `INSERT`/`UPDATE`/`DELETE`/`MERGE`/`CREATE`/
  `DROP`/`ALTER`/`COPY INTO`/`TRUNCATE`. This path observes data; it never
  changes it.
- **Never write an SDP-owned table** (the **single-writer invariant**): every UC
  table has exactly one owning lane. Repaired/backfill data re-enters via the
  landing volume or a `backfill:` once-flow — never a SQL write from here.
- **No secrets, no side effects.** Don't select or echo credentials; don't use
  the connection to reach other systems.
- If a task actually needs to WRITE a table, stop and author it the right way
  (an SDP artifact / `backfill:` flow / the python-file or notebook lane) — run
  the 3-question router in AGENTS.md.

## Done check

You used MCP correctly if: the artifact you authored reflects the table's REAL
columns/types (verified by `DESCRIBE`), any dqx rule you added is backed by an
observed value distribution, and you ran **no** statement that mutates data.
Then validate the artifact the normal way: `make validate-configs`.
