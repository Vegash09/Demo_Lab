# docs/FRAMEWORK.md — moved

The datalab **framework reference** (artifact anatomy, target kinds, dqx
semantics, the SDP capability matrix, "Run anywhere") now lives with the
framework code, in its own repo:

➡️ **https://github.com/dediggibyte/datalab-framework/blob/v1.0.0/docs/FRAMEWORK.md**

This repo (`datalab`) is the reference **domains + deploy bundle**; it consumes the
framework as a git dependency (local dev/CI) and a versioned UC-Volume wheel
(serverless). See [AGENTS.md](../AGENTS.md) and [README.md](../README.md).

The link above is pinned to the framework version this repo runs (the
`datalab` git tag in `pyproject.toml`): `make bump-framework` re-pins it with
every bump and `make check-lockstep` fails if it drifts, so the reference you
read never describes features newer than the pinned framework.

> This stub keeps existing `docs/FRAMEWORK.md` links resolving; in-repo references
> now point directly at the framework repo's reference above.
