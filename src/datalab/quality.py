"""DEPRECATED — data quality is now databrickslabs/dqx via the framework.

Rules live in ``config/<domain>/*.yml`` (``quality.checks``, dqx metadata
format) and are applied by ``datalab.framework.dq.DQAdapter``. These helpers
remain only so pre-framework branches keep importing during the transition;
new code must not use them.
"""

from __future__ import annotations

import warnings

Rules = dict[str, str]

_DEPRECATION = (
    "datalab.quality is deprecated: define rules in config/<domain>/*.yml "
    "(dqx metadata) — see datalab.framework.dq and docs/FRAMEWORK.md"
)


def all_rules_predicate(rules: Rules) -> str:
    """SQL predicate that is true only when every rule passes. DEPRECATED."""
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    if not rules:
        return "true"
    return " AND ".join(f"({expr})" for expr in rules.values())


def violation_predicate(rules: Rules) -> str:
    """SQL predicate matching rows violating at least one rule. DEPRECATED."""
    warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)
    if not rules:
        return "false"
    return "NOT (" + " AND ".join(f"({expr})" for expr in rules.values()) + ")"
