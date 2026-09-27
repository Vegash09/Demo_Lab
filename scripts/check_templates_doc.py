#!/usr/bin/env python3
"""Assert the bootstrap-adopter-repo skill's templates.md mirrors the scaffold engine.

``.agents/skills/bootstrap-adopter-repo/references/templates.md`` is two things:
the human-readable record of what ``scripts/scaffold_adopter.py`` writes, and the
documented MANUAL FALLBACK for converting a repo when the script cannot be run.
It only earns that second role while it is byte-identical to the engine's
templates (modulo placeholder spelling) — and it silently was not:

* it shipped ``environment_version: "4"`` UNCOMMENTED, the one setting the engine
  deliberately comments out because Databricks' fingerprint gate leaves a brand-new
  pipeline unable to run once it is enabled (docs/ADOPTING.md "First-deploy traps");
* it told the reader to create empty ``silver/``/``gold/`` layer dirs, which the
  framework's config validator rejects outright;
* it omitted ``tests/test_smoke.py``, so a hand-converted repo collected zero tests
  and failed its own documented ``make test`` gate;
* it pinned ``pyspark[pipelines]>=4.1.0`` without the engine's ``<4.3`` cap.

Prose stays hand-written; only the fenced code blocks are pinned. Each engine
template is mirrored by ONE fenced block under a ``### `<path>``` heading naming
the file it writes. This script substitutes the engine's ``@@TOKEN@@``
placeholders for the doc's ``<angle-bracket>`` spellings and diffs the two.

    make check-templates-doc      # CI gate + pre-commit
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold_adopter as engine  # noqa: E402  (path set above)

DOC = REPO_ROOT / ".agents/skills/bootstrap-adopter-repo/references/templates.md"

# The engine substitutes @@TOKEN@@ per run; the doc is generic, so it spells the
# same slots as <angle-bracket> placeholders (listed at the top of the doc).
PLACEHOLDERS = {
    "@@CATALOG_DEV@@": "<dev-catalog>",
    "@@CATALOG_STAGE@@": "<stage-catalog>",
    "@@CATALOG_PROD@@": "<prod-catalog>",
    "@@CATALOG@@": "<catalog>",
    "@@CUSTOMER@@": "<customer>",
    "@@DESCRIPTION@@": "<description>",
    "@@FRAMEWORK_TAG@@": "<framework-tag>",
    "@@DATALAB_VERSION@@": "<framework-version>",
    "@@HOST_STAGE@@": "<stage-host>",
    "@@HOST_PROD@@": "<prod-host>",
    "@@HOST@@": "<host>",
    "@@DEPLOY_SP@@": "<deploy-sp-app-id>",
    "@@READER_GROUP@@": "<reader-group>",
    "@@ENGINEER_GROUP@@": "<engineer-group>",
    "@@ADMIN_GROUP@@": "<admin-group>",
    "@@WAREHOUSE_ID@@": "<warehouse-id>",
    "@@MCP_PROFILE@@": "<cli-profile>",
    "@@TEMPLATE_URL@@": "<template-url>",
    "@@AGENTS_LIST@@": "<agents>",
    "@@COMPONENTS_LIST@@": "<components>",
    "@@SYNC_EXCLUDE@@": "<sync-exclude-entries>",
    "@@IGNORE_ENTRIES@@": "<ignore-entries>",
}

# Every file the engine WRITES WHOLE (write_domain + write_repo_level +
# write_design) must be mirrored: doc heading path -> the engine constant
# holding its template. The GENERATED design files are described in prose
# instead: the two draw.io diagrams (built by scripts/design_diagram.py through
# the drawio-architecture-designer kit) and design/PIPELINES.md (RENDERED from
# config/ by scripts/design_inventory.py).
# Files the engine only PATCHES in place (Makefile, scripts/, CI/CD, .mcp.json …)
# are described in prose too and are not checked here.
MIRRORED: dict[str, str] = {
    "config/<catalog>/domain.yml": "DOMAIN_YML",
    "config/<catalog>/bronze/events_raw.yml": "BRONZE_YML",
    "src/<catalog>_etl/__init__.py": "PKG_INIT",
    "src/<catalog>_etl/transformations/pipeline.py": "PIPELINE_PY",
    "src/<catalog>_etl/transforms/__init__.py": "TRANSFORMS_INIT",
    "src/<catalog>_etl/checks/__init__.py": "CHECKS_INIT",
    "tests/conftest.py": "CONFTEST_PY",
    "tests/test_smoke.py": "SMOKE_TEST_PY",
    "resources/<catalog>_etl.pipeline.yml": "PIPELINE_RESOURCE",
    "resources/<catalog>_etl.job.yml": "JOB_RESOURCE",
    "sample_data/landing/<catalog>/events/events.json": "SAMPLE_EVENTS_JSON",
    "databricks.yml": "DATABRICKS_YML",
    "pyproject.toml": "PYPROJECT_TOML",
    "variables/medallion.yml": "VARIABLES_MEDALLION",
    "targets/dev.yml": "TARGET_DEV",
    "targets/stage.yml": "TARGET_STAGE",
    "targets/prod.yml": "TARGET_PROD",
    "README.md": "README_MD",
    "CHANGELOG.md": "CHANGELOG_MD",
    ".databricksignore": "DATABRICKSIGNORE",
    ".gitattributes": "GITATTRIBUTES_DESIGN",
    "design/OVERVIEW.md": "DESIGN_OVERVIEW_MD",
    "design/estate.yml": "DESIGN_ESTATE_YML",
}

HEADING_RE = re.compile(r"^###\s+`([^`]+)`\s*$")
# Fences of 3+ backticks, so a block whose CONTENT holds ``` (the generated
# README's bash blocks) can be wrapped in ````.
FENCE_RE = re.compile(r"^(`{3,})\s*[A-Za-z0-9_+-]*\s*$")


def doc_blocks(text: str) -> dict[str, str]:
    """Map each ``### `path``` heading to the first fenced block beneath it."""
    blocks: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        heading = HEADING_RE.match(lines[i])
        if not heading:
            i += 1
            continue
        path = heading.group(1)
        i += 1
        body: list[str] | None = None
        while i < len(lines):
            if HEADING_RE.match(lines[i]) or lines[i].startswith("## "):
                break  # next section began before any fenced block
            fence = FENCE_RE.match(lines[i])
            if fence:
                marker = fence.group(1)
                i += 1
                body = []
                while i < len(lines) and lines[i].rstrip() != marker:
                    body.append(lines[i])
                    i += 1
                break
            i += 1
        if body is not None and path not in blocks:
            blocks[path] = "\n".join(body)
    return blocks


def expected(constant: str) -> str:
    template = getattr(engine, constant)
    for token, placeholder in PLACEHOLDERS.items():
        template = template.replace(token, placeholder)
    return template


def main() -> int:
    if not DOC.exists():
        print(f"check-templates-doc: missing {DOC.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1

    blocks = doc_blocks(DOC.read_text(encoding="utf-8"))
    problems: list[str] = []

    for path, constant in MIRRORED.items():
        want = expected(constant).strip("\n")
        heading = f"### `{path}`"
        if path not in blocks:
            problems.append(
                f"{path}: no fenced code block found under a `{heading}` heading.\n"
                f"  Add one holding scaffold_adopter.{constant} verbatim "
                f"(with the doc's <placeholder> spellings)."
            )
            continue
        got = blocks[path].strip("\n")
        if got != want:
            diff = "\n".join(
                "    " + line
                for line in difflib.unified_diff(
                    want.splitlines(),
                    got.splitlines(),
                    fromfile=f"scaffold_adopter.{constant} (engine — the truth)",
                    tofile=f"templates.md `{path}` (doc)",
                    lineterm="",
                )
            )
            problems.append(f"{path}: drifted from scaffold_adopter.{constant}\n{diff}")

    if problems:
        print(
            "check-templates-doc: the bootstrap-adopter-repo skill's "
            "references/templates.md has drifted from scripts/scaffold_adopter.py.\n"
            "It is the documented MANUAL FALLBACK, so drift hands the next adopter a "
            "repo that fails its own gates. Update the doc's code block to match the "
            "engine (the engine is the source of truth).\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(f"templates.md mirrors the scaffold engine ({len(MIRRORED)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
