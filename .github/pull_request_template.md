<!-- datalab-pr-template: v1 -->
<!--
  datalab · unified pull-request template.

  Keep the `datalab-pr-template` marker comment above. It is required by:
    * CI     — .github/workflows/pr-template-check.yml
    * agents — the PR-creation guard hook each configured coding agent runs
  so every PR shares ONE format. Fill in each section and delete the guidance
  comments. Do not add or remove top-level (`##`) sections.
-->

## Summary

<!-- What does this PR do, and why? 1-3 sentences focused on the "why". -->

## Change type

<!-- Check all that apply. Keep the list; just tick boxes. -->
- [ ] Pipeline / transformation
- [ ] Framework version bump (datalab git tag + var.datalab_version)
- [ ] Bundle / deploy config
- [ ] CI/CD
- [ ] Docs
- [ ] Dependencies

## Changes

<!-- Bullet the notable changes. -->
-

## Test plan

<!-- How did you verify this? Commands run and expected results. -->
- [ ] `make lint` passes
- [ ] `make test` passes (unit tests, local Spark)
- [ ] `make validate` passes (if bundle / resources changed)
- [ ] Dev pipeline refresh succeeds (`make run`) (if pipeline code changed)

## Deployment / rollout notes

<!-- Anything to do at deploy time? New variables, schemas, volumes, grants,
     full refresh needed? Write "None" if not applicable. -->
None

## Checklist

- [ ] Protected-file changes are intentional and captured in `AGENTS.md`
- [ ] Pipeline code uses `pyspark.pipelines` only (no `dlt` imports, no writes in dataset functions)
- [ ] Dependencies: `pyproject.toml` updated via `uv lock` (uv.lock committed)
- [ ] No secrets committed (`.env` stays out of git)
