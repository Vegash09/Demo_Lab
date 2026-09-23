# Query Databricks from the agent (opt-in, dev-time MCP)

Let Claude Code / Cursor run **read-only** SQL and browse Unity Catalog tables in
your workspace directly from the editor — so the agent can **ground the authoring
workflow** in real data (preview `silver.customers` before authoring
`gold.customers_by_city`, check a value distribution before adding a dqx rule,
discover what a schema holds). It connects to a Databricks **managed MCP server**
through a small stdio proxy that authenticates with your existing **Databricks
CLI profile** — no OAuth app, no token in the repo.

This is **opt-in, reversible, and dev-time only**. It changes nothing about the
framework, the bundle, CI, or the deploy surface — `.mcp.json` is excluded from
the deployed bundle via `.databricksignore`, and the proxy never enters
`uv.lock` (it runs through `uvx` — never a locked dependency).

## What's here

| File | Purpose |
|---|---|
| [`.mcp.json`](../.mcp.json) | Claude Code project-scoped MCP config — a `uvx` stdio proxy (`uc-mcp-proxy`) to the workspace's managed Databricks **SQL** MCP endpoint. Uses `${VAR:-default}` so env vars can repoint it without editing the file. | <!-- adopter-if:agent-claude -->
| [`.cursor/mcp.json`](../.cursor/mcp.json) | Cursor counterpart (same server; literal values — edit them, or set env, for your workspace). | <!-- adopter-if:agent-cursor -->
| `.agents/skills/query-databricks/SKILL.md` (canonical; generated copy in `.claude/skills/` via `make sync-skills`) | The `query-databricks` skill — teaches the agent *when* to query and the **read-only / single-writer** guardrail. |

## Prerequisites

- **Databricks CLI authenticated** as a profile (OAuth U2M — no PAT needed):
  ```bash
  databricks auth login --host https://dbc-425be768-f138.cloud.databricks.com
  # creates/uses a ~/.databrickscfg profile; this repo is configured for `diggi_dev_aws`
  ```
- **`uv` / `uvx`** on PATH (already required by the repo). The proxy is fetched
  ephemerally by `uvx` — **do not `uv add` it**; it must not enter
  `pyproject.toml` / `uv.lock` or the bundle.
- A **running SQL warehouse** you can use (this repo is configured for
  `c1cdbe2406e5cf04`; `databricks warehouses list` shows yours).
- **Managed MCP enabled** in the workspace (see Verification — it may be a
  Beta/preview feature gated per workspace/region).

## How it works

```
Claude Code / Cursor ──stdio──▶ uvx uc-mcp-proxy ──HTTPS (CLI-profile auth)──▶
   <profile host>/api/2.0/mcp/sql   (Databricks managed MCP; warehouse via --meta)
        │
        ▼  Unity Catalog grants enforced on every read
   read-only SQL · DESCRIBE · SHOW TABLES over your UC tables
```

- **Managed server, hosted by Databricks** — there is no server code in this
  repo. The endpoint lives on your workspace host.
- **Auth = your CLI profile.** `uc-mcp-proxy --auth-type databricks-cli --profile
  <name>` reuses `~/.databrickscfg` — and resolves the workspace **host from that
  profile** (the `--url` is the workspace-relative `/api/2.0/mcp/sql`), so the
  host is never duplicated. The SQL warehouse is passed with `--meta
  warehouse_id=<id>`. Databricks does **not** support Dynamic Client
  Registration, so the naive remote-OAuth path fails in most IDEs; the
  CLI-profile proxy is Databricks' documented answer and keeps **no secret in the
  repo**.
- **Unity Catalog governs access** — you only see what your identity is granted.

## Endpoints

| Server | URL | Wired here? |
|---|---|---|
| Databricks SQL | `https://<host>/api/2.0/mcp/sql` | **Yes** (primary — ad-hoc read-only SQL + schema introspection) |
| Genie (NL Q&A) | `https://<host>/api/2.0/mcp/genie/{genie_space_id}` | No — optional; needs a curated Genie space |
| UC functions | `https://<host>/api/2.0/mcp/functions/{catalog}/{schema}` | No — optional; exposes registered UC functions as tools |

The proxy takes the workspace-relative form (`--url /api/2.0/mcp/sql`) and fills
the host from your profile. To add Genie/functions, copy the `databricks-sql`
block in `.mcp.json`, rename it, and swap the `--url` (e.g.
`/api/2.0/mcp/genie/{genie_space_id}`). Find your servers + exact URLs at
**Workspace → Agents → MCP Servers**.

## Use it

<!-- adopter-if:agent-claude start -->
- **Claude Code**: open the repo; it detects `.mcp.json` and asks you to approve
  the `databricks-sql` server (approve once). `/mcp` lists its tools. Then ask,
  e.g. *"List tables in `customer_sales.silver`, then show 5 rows of
  `silver.customers`."* The `query-databricks` skill guides when to reach for it.
<!-- adopter-if:agent-claude end -->
<!-- adopter-if:agent-cursor start -->
- **Cursor**: enable `databricks-sql` under **Settings → MCP**, then prompt the
  same way in chat (e.g. *"List the tables in the silver schema, then show 5
  rows of one"*); the `query-databricks` skill guides when to reach for it.
<!-- adopter-if:agent-cursor end -->

## Safety

- **Read-only.** The agent runs `SELECT` / `DESCRIBE` / `SHOW`; the
  `query-databricks` skill forbids `INSERT/UPDATE/DELETE/MERGE/CREATE/DROP`, and
  Unity Catalog grants are the real boundary (don't grant the querying identity
  write on SDP-owned tables).
- **Single-writer invariant holds.** The agent may *read* SDP-owned tables, never
  *write* them — repaired/backfill data re-enters via the landing volume or a
  `backfill:` flow (see AGENTS.md).
- **No secret in the repo.** The committed JSON holds only a workspace host, a
  warehouse id, and a profile *name* — none are credentials. OAuth tokens live in
  the CLI keyring / `~/.databrickscfg`, which is never committed.

## Reversibility

Delete `.mcp.json`, `.cursor/mcp.json`, the two `query-databricks/SKILL.md`
files, and their `.databricksignore` / protected-list rows — nothing else depends
on them. `uc-mcp-proxy` is community/fast-moving; pin a version
(`uvx uc-mcp-proxy@<ver>`) and re-check `uvx uc-mcp-proxy --help` if a flag
changes. Treat it as opt-in, verify, throwaway.

<!-- template-only:agent-mcp-adopter-setup start -->
## Adopter setup

When you stand up an adopter repo with `make configure-adopter` (in place) or
`make new-adopter` (sibling), the configurator has **already** rewritten both
JSON files to your SQL warehouse id + CLI profile — there is nothing to swap
unless you left the warehouse id as a placeholder (`<sql-warehouse-id>`) at
configure time, in which case fill it now. (If you instead copied the harness in
by hand, the `.mcp.json` / `.cursor/mcp.json`, the `query-databricks` skill, this
doc, and the `.databricksignore` / protected-list rows come along **as-is**, still
pointing at this template's workspace — point them at yours.) Either way you can
edit the two JSON files directly, or (Claude Code) export the env overrides the
defaults already reference:
<!-- template-only:agent-mcp-adopter-setup end -->

| Value | This repo's configured value | Where it lives | Your source |
|---|---|---|---|
| CLI profile (`DATABRICKS_CONFIG_PROFILE`) | `diggi_dev_aws` | `~/.databrickscfg` (carries the workspace host + auth) | your `databricks auth login` profile |
| SQL warehouse id (`DATABRICKS_SQL_WAREHOUSE_ID`) | `c1cdbe2406e5cf04` | a dev SQL warehouse | `databricks warehouses list` |

The **workspace host comes from your CLI profile** (the `--url` is
workspace-relative), so there is no host to set separately.
<!-- adopter-if:agent-cursor start -->
`.cursor/mcp.json` carries literal values (most robust across Cursor versions) —
edit them directly.
<!-- adopter-if:agent-cursor end -->
<!-- adopter-if:agent-claude start -->
`.mcp.json` uses `${VAR:-default}`, so
`export DATABRICKS_CONFIG_PROFILE=… DATABRICKS_SQL_WAREHOUSE_ID=…` repoints Claude
Code without touching the protected file.

> Note: a `.env` that sets `DATABRICKS_PROFILE` is using the wrong name — the
> CLI/SDK variable is `DATABRICKS_CONFIG_PROFILE`. The `.mcp.json` default
> (`diggi_dev_aws`) means you don't depend on `.env` at all; set
> `DATABRICKS_CONFIG_PROFILE` to override.
<!-- adopter-if:agent-claude end -->

## Verification

1. **Managed MCP is available** — Databricks UI → **Workspace → Agents → MCP
   Servers**; confirm the **SQL** server is listed and your warehouse is RUNNING.
   (Managed MCP may be Beta / admin-enabled / region-gated.)
2. **Proxy + auth smoke test** (no repo changes):
   ```bash
   databricks auth login --host https://dbc-425be768-f138.cloud.databricks.com
   uvx uc-mcp-proxy --help            # confirm the package name + flags first
   databricks warehouses get c1cdbe2406e5cf04 --profile diggi_dev_aws   # → RUNNING
   ```
3. **Claude Code end-to-end** — approve the server, run `/mcp`, then ask for a `SHOW TABLES` + a `SELECT … LIMIT 5`; expect results (subject to UC grants). <!-- adopter-if:agent-claude -->
4. **Cursor end-to-end** — enable the server in Settings → MCP, then ask for a `SHOW TABLES` + a `SELECT … LIMIT 5`. <!-- adopter-if:agent-cursor -->
5. **Read-only check** — ask the agent to `CREATE`/`INSERT`; confirm it refuses
   (skill) and that the warehouse/UC grants would reject it anyway.

## Fallback — managed MCP not available

If your workspace has no managed MCP (Beta-gated / wrong region), run a **local**
Databricks SQL MCP server that talks to the same warehouse via your CLI profile,
and point `.mcp.json` / `.cursor/mcp.json` `command`/`args` at it instead of the
`uvx` proxy + managed URL. Keep the managed endpoint as the default and the local
server as the documented alternative; verify the exact local-server package and
its flags before wiring it.
