from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


def load_notebook_module(path: str | Path) -> Any:
    """Load a notebook module from a repository-relative path.

    Accepts extensionless paths (e.g. 'notebooks/x/y/z') and will try '.py'.
    Returns the imported module object.
    """
    root = Path(__file__).resolve().parents[2]
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    # if extensionless, assume .py
    if p.suffix == "":
        p = p.with_suffix(".py")
    if not p.exists():
        raise FileNotFoundError(f"Notebook file not found: {p}")

    mod_name = f"nb_{p.stem}_{abs(hash(p.as_posix()))}"
    spec = spec_from_file_location(mod_name, p.as_posix())
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {p}")
    mod = module_from_spec(spec)
    # Predefine globals often assumed by notebooks to avoid eager initialisation
    # during import in test environments.
    try:
        setattr(mod, "spark", object())
    except Exception:
        pass
    try:
        setattr(mod, "dbutils", None)
    except Exception:
        pass
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def load_notebook_module_for_test(test_file: str | Path) -> Any:
    """Derive the notebook path from a unit test path and import it.

    Expected test path pattern:
      notebooks/tests/unit_testing/<stage>/<domain>/test_<name>.py
    Derived notebook path:
      notebooks/<stage>/<domain>/<name>.py
    """
    tf = Path(test_file).resolve()
    try:
        rel = tf.relative_to(Path(__file__).resolve().parents[2])
    except ValueError:
        # If running outside repo root, just use the filename logic
        rel = Path("notebooks/tests/unit_testing") / tf.name

    parts = rel.parts
    # Find anchor 'notebooks', 'tests', 'unit_testing'
    try:
        nb_idx = parts.index("notebooks")
    except ValueError:
        # fallback: assume path already starts at tests/unit_testing
        nb_idx = -3
    try:
        stage = parts[nb_idx + 3]
        domain = parts[nb_idx + 4]
        filename = parts[nb_idx + 5]
    except Exception as exc:
        raise ValueError(f"Unexpected test path layout for {tf}") from exc

    if not filename.startswith("test_") or not filename.endswith(".py"):
        raise ValueError(f"Test file name must be test_*.py, got {filename}")

    nb_name = filename[len("test_") : -len(".py")]
    nb_rel = Path("notebooks") / stage / domain / f"{nb_name}.py"
    return load_notebook_module(nb_rel)
