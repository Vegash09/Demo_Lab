# Run datalab's authoring agent on Omnigent (opt-in pilot)

[Omnigent](https://github.com/omnigent-ai/omnigent) is a meta-harness/orchestrator
for AI coding agents — it runs the same agent definition on **Claude Code, Codex,
Cursor, or Pi** behind one CLI. This folder lets you drive datalab's existing
**agent-first authoring workflow** (author/change a medallion table as a YAML
artifact) on whichever harness you have access to, grounded in the repo's rules
of record.

This is an **experiment**: opt-in, reversible, and dev-time only. It changes
nothing about the existing Cursor/Claude setup, the framework, the bundle, or
CI — `omnigent/` is excluded from the deployed bundle via `.databricksignore`.

## What's here

| File | Purpose |
|---|---|
| [`datalab-author.yaml`](datalab-author.yaml) | Single-file Omnigent agent spec. `instructions: ../AGENTS.md` makes [AGENTS.md](../AGENTS.md) the single source of truth, so the agent follows the same authoring rules — and reads the same `.agents/skills/*` (`author-ldp-artifact`, `author-sdp-pipeline`, `deploy-databricks-bundle`, `maintain-design-diagram`) — as the Cursor/Claude agents. No rules are copied or restated. |

## Install

Omnigent is a standalone CLI. Install it **outside** this repo's environment — it
must not enter datalab's `.venv` / `uv.lock` (and never goes in the bundle):

```bash
uv tool install omnigent          # or: pipx install omnigent
omnigent --version
```

Do **not** `uv add` it to `pyproject.toml`.

## Run

From the **datalab repo root** (so `../AGENTS.md` and `cwd: .` resolve):

```bash
omnigent run omnigent/datalab-author.yaml
```

Pick a harness explicitly (the spec defaults to `claude-sdk`):

```bash
omnigent run omnigent/datalab-author.yaml --harness codex     # or: cursor | pi
```

Then prompt it the same way you would the Cursor/Claude agent, e.g.
*"Add a `silver.orders` table from the `orders_raw` bronze source with a not-null
check on `order_id`."* The agent reads `AGENTS.md`, applies the relevant skill,
authors the `config/<catalog>/<schema>/<table>.yml` artifact, and can run the
repo's gates through its `shell` terminal:

```bash
make validate-configs    # pydantic + dqx
make lint
make test
```

## Model: provider default or Databricks-hosted

By default no model is pinned, so the agent uses your configured provider default
(an Anthropic/OpenAI key, a Claude/ChatGPT subscription, or a gateway). To route
the model through your **Databricks** workspace instead (in-tenant model serving),
install the extra and uncomment the `model` / `auth` block in `datalab-author.yaml`:

```bash
uv tool install 'omnigent[databricks]'
```

```yaml
executor:
  harness: claude-sdk
  model: databricks-claude-sonnet-4-6
  auth:
    type: databricks
    profile: <your-databricks-cli-profile>
```

(The `cursor` harness is the exception — it talks only to Cursor's backend, so it
needs `CURSOR_API_KEY` and a Cursor model id, not the Databricks gateway.)

## Safety

This pilot deliberately does **not** port datalab's guards
(`.cursor/hooks/branch_guard.py`, `.claude/hooks/protected_files_guard.py`, the
PR-template guard) to Omnigent **policies**, so the Omnigent-run agent is *not*
gated at the agent runtime. The existing net still applies — but only at
commit/CI time, not while the agent edits:

- **Run on a feature branch.** Start from `main`:
  `git switch main && git pull && git switch -c feature/<slug>`. Never run it on
  `main` (the branch-first rule in AGENTS.md still holds for you as the operator).
- **Review the diff before committing.** `git diff` / `git status` after the run.
- **Commit with the git hook enabled.** `make enable-githooks` once;
  `.githooks/pre-commit` then blocks commits to `main` and warns on protected
  files, and CI (ruff + validate-configs + pytest + bundle validate) re-checks the
  PR. Protected-file edits go through `make commit-protected MSG="..."`.

Adding runtime enforcement (re-expressing the guards as Omnigent
`ALLOW`/`DENY`/`ASK` policies) is a separate, deliberate follow-up — not part of
this pilot.

## Reversibility

Delete the `omnigent/` folder and remove its `.databricksignore` entry — nothing
else depends on it. Omnigent itself is alpha and fast-moving; if the spec stops
loading, reconcile the `executor` shape against your installed `omnigent`
version (`omnigent --help`, and the spec format in Omnigent's own docs). Treat
this as a throwaway experiment, not a hard dependency.
