"""Data-quality rule helpers shared across pipelines.

Rules are plain ``{name: sql_boolean_expression}`` dicts — the exact shape the
SDP expectation decorators take (``@dp.expect_all*``). The helpers here derive
the inverse predicate used to route violating rows to a quarantine table, so a
single rule definition drives both the expectation and the quarantine filter.
"""

from __future__ import annotations

Rules = dict[str, str]


def all_rules_predicate(rules: Rules) -> str:
    """SQL predicate that is true only when every rule passes."""
    if not rules:
        return "true"
    return " AND ".join(f"({expr})" for expr in rules.values())


def violation_predicate(rules: Rules) -> str:
    """SQL predicate matching rows that violate at least one rule.

    Used by quarantine tables: ``df.where(violation_predicate(RULES))`` keeps
    exactly the rows that ``@dp.expect_all_or_drop(RULES)`` drops.
    """
    return f"NOT ({all_rules_predicate(rules)})"
