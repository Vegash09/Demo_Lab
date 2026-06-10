"""Parameter helpers for the non-SDP lanes (notebook tasks, python-file tasks).

SDP pipelines read parameters from Spark conf via
:func:`datalab.config.pipeline_conf`. Job tasks get theirs from the job
``parameters:`` block in ``resources/*.job.yml`` — notebooks as widgets
(populated through ``base_parameters``), python files as ``--flag`` argv
entries. These helpers resolve them with the same fail-fast contract, so a
missing parameter always points at the resource file to fix, whatever the lane.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def notebook_params(dbutils, names: Sequence[str]) -> dict[str, str]:
    """Resolve required notebook widgets, failing fast on absent/empty ones.

    ``dbutils`` is passed in (not imported) so unit tests can supply a fake.
    Widget names must match the job parameter names — the job's
    ``base_parameters`` mapping is what populates them on a triggered run.
    """
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        try:
            value = dbutils.widgets.get(name)
        except Exception:
            value = ""
        if value:
            values[name] = value
        else:
            missing.append(name)
    if missing:
        raise ValueError(
            f"Missing notebook parameter(s) {missing}. Declare each under the "
            "job's 'parameters:' block and the task's 'base_parameters' in "
            "resources/*.job.yml (widget name == job parameter name)."
        )
    return values


def cli_params(argv: Sequence[str] | None, names: Sequence[str]) -> dict[str, str]:
    """Parse required ``--kebab-case`` flags for spark_python_task entry points.

    ``names`` use snake_case; the matching flag is the kebab-case form
    (``gold_schema`` → ``--gold-schema``). Pass ``argv=None`` in production to
    read ``sys.argv``; tests pass an explicit list.
    """
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    for name in names:
        parser.add_argument(f"--{name.replace('_', '-')}", dest=name)
    try:
        namespace, _unknown = parser.parse_known_args(argv)
    except argparse.ArgumentError as exc:
        raise ValueError(
            f"Could not parse CLI parameters: {exc}. Flags are passed via the "
            "task 'parameters:' list in resources/*.job.yml."
        ) from exc
    missing = [name for name in names if not getattr(namespace, name)]
    if missing:
        raise ValueError(
            f"Missing CLI parameter(s) {missing}. Pass each as "
            "'--<kebab-case-name> {{job.parameters.<name>}}' in the task "
            "'parameters:' list in resources/*.job.yml."
        )
    return {name: getattr(namespace, name) for name in names}
