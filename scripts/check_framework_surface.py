"""Mandate the CORRESPONDING CHANGES of a framework bump in the authoring guidance.

A framework release can add config surface — a new `target.kind` or
`source.kind` (0.9.0 added `foreach_batch_sink`, 1.0.0 added `managed_table`).
Bumping the pin alone leaves this repo's authoring skill — what an agent reads
to turn a request into a YAML artifact — describing the OLD surface, so the new
capability is invisible to everyone authoring here. It drifted exactly that
way: the skill never learned `foreach_batch_sink`.

This check reads every target/source kind from the VENDORED config schema
(`schemas/table_config.schema.json`, regenerated from the pinned framework by
`make bump-framework`) and requires each to be documented in the authoring
skill — written as `` `<kind>` `` or `kind: <kind>`. A bump PR that brings new
kinds therefore fails CI until the skill covers them. Same mode as
check_framework_current.py (DATALAB_FRAMEWORK_MANDATE): enforced in the
template, a warning in generated adopter repos unless they set `enforce`.

Stdlib only — runs with `uv run --no-project`:

    make check-framework-surface
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_framework_current import MODE_VAR, mode  # noqa: E402

SCHEMA = Path("schemas/table_config.schema.json")
SKILL = Path(".agents/skills/author-ldp-artifact/SKILL.md")


def discriminator_kinds(schema: dict, field: str) -> set[str]:
    """The `kind` values of the discriminated union at top-level ``field``."""
    prop = schema["properties"][field]
    for candidate in [prop, *prop.get("anyOf", []), *prop.get("oneOf", [])]:
        mapping = candidate.get("discriminator", {}).get("mapping")
        if mapping:
            return set(mapping)
    raise SystemExit(
        f"{SCHEMA}: no discriminator mapping under properties.{field} — the schema "
        "shape changed; update scripts/check_framework_surface.py"
    )


def documented(kind: str, text: str) -> bool:
    return bool(re.search(rf"`{re.escape(kind)}`|kind:\s*{re.escape(kind)}\b", text))


def missing_kinds(schema: dict, skill_text: str) -> dict[str, list[str]]:
    return {
        field: sorted(k for k in discriminator_kinds(schema, field) if not documented(k, skill_text))
        for field in ("target", "source")
    }


def main(root: Path = REPO_ROOT) -> int:
    schema = json.loads((root / SCHEMA).read_text())
    missing = missing_kinds(schema, (root / SKILL).read_text())
    gaps = {field: kinds for field, kinds in missing.items() if kinds}
    if gaps:
        listed = "; ".join(f"{field}.kind: {', '.join(kinds)}" for field, kinds in gaps.items())
        message = (
            f"{SKILL} does not document {listed} — the pinned framework supports them (see "
            f"{SCHEMA}). Document each (what it is for, its rules) in the skill as part of "
            "the framework bump, then `make sync-skills`."
        )
        if mode(root) == "warn":
            print(f"::warning title=Framework surface not documented::{MODE_VAR}=warn — {message}")
            return 0
        print(f"::error title=Framework surface not documented::{message}")
        return 1
    print(f"{SKILL} documents every target/source kind of the pinned framework")
    return 0


if __name__ == "__main__":
    sys.exit(main())
