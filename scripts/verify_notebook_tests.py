#!/usr/bin/env python3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NB_DIR = ROOT / "notebooks"
TESTS_DIR = NB_DIR / "tests"
PIPELINES_DIR = ROOT / "pipelines"
CONFIG_DIR = ROOT / "config"


def notebooks_missing_tests() -> list[tuple[Path, Path]]:
    missing: list[tuple[Path, Path]] = []
    for nb_path in NB_DIR.rglob("*.py"):
        # skip tests themselves and non-notebook support files
        if TESTS_DIR in nb_path.parents:
            continue
        rel = nb_path.relative_to(NB_DIR)
        expected_test = TESTS_DIR / rel.parent / f"test_{rel.name}"
        if not expected_test.exists():
            missing.append((nb_path, expected_test))
    return missing


def notebooks_missing_pipeline_refs() -> list[Path]:
    missing: list[Path] = []
    pipeline_files = list(PIPELINES_DIR.glob("**/*.yml")) + list(PIPELINES_DIR.glob("**/*.yaml"))
    pipeline_texts = [p.read_text() for p in pipeline_files]

    for nb_path in NB_DIR.rglob("*.py"):
        if TESTS_DIR in nb_path.parents:
            continue
        rel_path = nb_path.as_posix().split(str(ROOT.as_posix()) + "/")[-1]
        # Accept workspace-style references (files/notebooks/...), with or without extension
        # and also allow other notebook types (.sql, .scala, etc.) by ignoring extension.
        from pathlib import Path as _P
        nb_rel = _P(rel_path)
        no_ext = nb_rel.with_suffix("").as_posix()
        candidates = {
            rel_path,  # notebooks/.../name.py
            ("files/" + rel_path),  # files/notebooks/.../name.py
            no_ext,  # notebooks/.../name
            ("files/" + no_ext),  # files/notebooks/.../name
        }
        found = any(any(cand in content for cand in candidates) for content in pipeline_texts)
        if not found:
            missing.append(nb_path)
    return missing


def notebooks_missing_configs() -> list[tuple[Path, Path]]:
    """Ensure each notebook has a mirrored JSON config under config/<stage>/<bu>/<name>.json"""
    missing: list[tuple[Path, Path]] = []
    for nb_path in NB_DIR.rglob("*.py"):
        if TESTS_DIR in nb_path.parents:
            continue
        # notebooks/<stage>/<bu>/<name>.py -> config/<stage>/<bu>/<name>.json
        rel = nb_path.relative_to(NB_DIR)
        if len(rel.parts) < 3:
            # Must be under stage/bu/name.py
            missing.append((nb_path, Path("<stage>/<bu>/<name>.json")))
            continue
        stage, bu, name = rel.parts[0], rel.parts[1], rel.stem
        expected_cfg = CONFIG_DIR / stage / bu / f"{name}.json"
        if not expected_cfg.exists():
            missing.append((nb_path, expected_cfg))
    return missing


def main() -> int:
    if not NB_DIR.exists():
        print("No notebooks/ directory found; skipping verification.")
        return 0

    missing_tests = notebooks_missing_tests()
    missing_pipelines = notebooks_missing_pipeline_refs()
    missing_configs = notebooks_missing_configs()

    failed = False
    if missing_tests:
        failed = True
        print("The following notebooks are missing associated unit test notebooks:")
        for nb, expected in missing_tests:
            print(f" - {nb} -> expected test: {expected}")

    if missing_pipelines:
        failed = True
        print("The following notebooks are not referenced by any pipeline YAML under pipelines/:")
        for nb in missing_pipelines:
            print(f" - {nb}")

    if missing_configs:
        failed = True
        print("The following notebooks are missing mirrored JSON configs under config/:")
        for nb, expected in missing_configs:
            print(f" - {nb} -> expected config: {expected}")

    if failed:
        print("Verification failed. Please add missing test notebooks and pipeline YAML references.")
        return 1

    print("Notebook verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

