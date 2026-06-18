# docs/FRAMEWORK.md — moved

The datalab **framework reference** (artifact anatomy, target kinds, dqx
semantics, the SDP capability matrix, "Run anywhere") now lives with the
framework code, in its own repo:

➡️ **https://github.com/dediggibyte/datalab-framework/blob/main/docs/FRAMEWORK.md**

This repo (`datalab`) is the reference **domains + deploy bundle**; it consumes the
framework as a git dependency (local dev/CI) and a versioned UC-Volume wheel
(serverless). See [AGENTS.md](../AGENTS.md) and [README.md](../README.md).

> This stub keeps existing `docs/FRAMEWORK.md` links resolving during the split.
> A follow-up doc pass will repoint the in-repo references to the framework repo.
