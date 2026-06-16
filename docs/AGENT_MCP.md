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
`uv.lock` (it runs through `uvx`, like the `omnigent/` pilot).

## What's here

| File | Purpose |
|---|---|
| [`.mcp.json`](../.mcp.json) | Claude Code project-scoped MCP config — a `uvx` stdio proxy (`uc-mcp-proxy`) to the workspace's managed Databricks **SQL** MCP endpoint. Uses `${VAR:-default}` so env vars can repoint it without editing the file. |
| [`.cursor/mcp.json`](../.cursor/mcp.json) | Cursor counterpart (same server; literal values — edit them, or set env, for your workspace). |
| `.claude/skills/query-databricks/SKILL.md` (+ `.cursor/` mirror) | The `query-databricks` skill — teaches the agent *when* to query and the **read-only / single-writer** guardrail. |

## Prerequisites

- **Databricks CLI authenticated** as a profile (OAuth U2M — no PAT needed):
  ```bash
  databricks auth login --host https://dbc-425be768-f138.cloud.databricks.com
  # creates/uses a ~/.databrickscfg profile; this repo's default is `diggi_dev_aws`
  ```
- **`uv` / `uvx`** on PATH (already required by the repo). The proxy is fetched
  ephemerally by `uvx` — **do not `uv add` it**; it must not enter
  `pyproject.toml` / `uv.lock` or the bundle.
- A **running SQL warehouse** you can use (this repo's default is
  `c1cdbe2406e5cf04`; `databricks warehouses list` shows yours).
- **Managed MCP enabled** in the workspace (see Verification — it may be a
  Beta/preview feature gated per workspace/region).

## How it works

```
Claude Code / Cursor ──stdio──▶ uvx uc-mcp-proxy ──HTTPS (CLI-profile auth)──▶
   https://<host>/api/2.0/mcp/sql?warehouse_id=<id>   (Databricks managed MCP)
        │
        ▼  Unity Catalog grants enforced on every read
   read-only SQL · DESCRIBE · SHOW TABLES over your UC tables
```

- **Managed server, hosted by Databricks** — there is no server code in this
  repo. The endpoint lives on your workspace host.
- **Auth = your CLI profile.** `uc-mcp-proxy --auth-type databricks-cli --profile
  <name>` reuses `~/.databrickscfg`. Databricks does **not** support Dynamic
  Client Registration, so the naive remote-OAuth path fails in most IDEs; the
  CLI-profile proxy is Databricks' documented answer and keeps **no secret in the
  repo**.
- **Unity Catalog governs access** — you only see what your identity is granted.

## Endpoints

| Server | URL | Wired here? |
|---|---|---|
| Databricks SQL | `https://<host>/api/2.0/mcp/sql` | **Yes** (primary — ad-hoc read-only SQL + schema introspection) |
| Genie (NL Q&A) | `https://<host>/api/2.0/mcp/genie/{genie_space_id}` | No — optional; needs a curated Genie space |
| UC functions | `https://<host>/api/2.0/mcp/functions/{catalog}/{schema}` | No — optional; exposes registered UC functions as tools |

To add Genie/functions, copy the `databricks-sql` block in `.mcp.json`, rename
it, and swap the `--url`. Find your servers + exact URLs at **Workspace → Agents
→ MCP Servers**.

## Use it

- **Claude Code**: open the repo; it detects `.mcp.json` and asks you to approve
  the `databricks-sql` server (approve once). `/mcp` lists its tools. Then ask,
  e.g. *"List tables in `customer_sales.silver`, then show 5 rows of
  `silver.customers`."* The `query-databricks` skill guides when to reach for it.
- **Cursor**: enable `databricks-sql` under **Settings → MCP**, then prompt the
  same way in chat.

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
changes. Treat it like the `omnigent/` pilot: opt-in, verify, throwaway.

## Adopter setup

When you copy this framework into your own repo, the harness (`.mcp.json`,
`.cursor/mcp.json`, the `query-databricks` skill, this doc, and the
`.databricksignore` / protected-list rows) comes along **as-is**. Then point it
at your workspace — either edit the two JSON files, or (Claude Code) export the
env overrides the defaults already reference:

| Value | This repo's default | Where it lives | Your source |
|---|---|---|---|
| Workspace host (`DATABRICKS_MCP_HOST`) | `https://dbc-425be768-f138.cloud.databricks.com` | `databricks.yml` `targets.<t>.workspace.host` | your target host |
| SQL warehouse id (`DATABRICKS_SQL_WAREHOUSE_ID`) | `c1cdbe2406e5cf04` | a dev SQL warehouse | `databricks warehouses list` |
| CLI profile (`DATABRICKS_CONFIG_PROFILE`) | `diggi_dev_aws` | `~/.databrickscfg` | your `databricks auth login` profile |

`.cursor/mcp.json` carries literal values (most robust across Cursor versions) —
edit them directly. `.mcp.json` uses `${VAR:-default}`, so
`export DATABRICKS_MCP_HOST=… DATABRICKS_SQL_WAREHOUSE_ID=… DATABRICKS_CONFIG_PROFILE=…`
repoints Claude Code without touching the protected file.

> Note: the repo `.env` currently sets `DATABRICKS_PROFILE` (wrong name) — the
> CLI/SDK variable is `DATABRICKS_CONFIG_PROFILE`. The `.mcp.json` default
> (`diggi_dev_aws`) means you don't depend on `.env`; set
> `DATABRICKS_CONFIG_PROFILE` to override.

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
3. **Claude Code end-to-end** — approve the server, run `/mcp`, then ask for a
   `SHOW TABLES` + a `SELECT … LIMIT 5`. Expect results (subject to UC grants).
4. **Cursor end-to-end** — enable the server in Settings → MCP, same prompt.
5. **Read-only check** — ask the agent to `CREATE`/`INSERT`; confirm it refuses
   (skill) and that the warehouse/UC grants would reject it anyway.

## Fallback — managed MCP not available

If your workspace has no managed MCP (Beta-gated / wrong region), run a **local**
Databricks SQL MCP server that talks to the same warehouse via your CLI profile,
and point `.mcp.json` / `.cursor/mcp.json` `command`/`args` at it instead of the
`uvx` proxy + managed URL. Keep the managed endpoint as the default and the local
server as the documented alternative; verify the exact local-server package and
its flags before wiring it.
