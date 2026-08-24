"""The rule registry: every rule id, its owning check, default severity and fixability.

Rule ids are part of the public interface — they appear in findings, in
suppression comments and in ``prose.yaml``. Renaming one is a breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    """A rule's resolved severity. ``OFF`` means the rule does not report."""

    ERROR = "error"
    WARNING = "warning"
    OFF = "off"


#: Checks that a project can enable, disable or re-severity.
CHECK_NAMES: tuple[str, ...] = ("reflow", "lint", "anchors", "freshness")

#: The pseudo-check that owns the cross-cutting rules. Always runs.
CROSS_CUTTING = "prose"

#: Checks that run when no config file names any.
DEFAULT_ENABLED: tuple[str, ...] = ("lint", "anchors")


@dataclass(frozen=True)
class Rule:
    """One rule's static metadata."""

    check: str
    rule: str
    default: Severity
    fixable: bool = False


_RULES: tuple[Rule, ...] = (
    Rule(CROSS_CUTTING, "parse-error", Severity.ERROR),
    Rule(CROSS_CUTTING, "unknown-suppression", Severity.WARNING),
    Rule(CROSS_CUTTING, "unused-suppression", Severity.OFF),
    Rule(CROSS_CUTTING, "mirrored-file", Severity.ERROR),
    Rule("reflow", "reflow", Severity.ERROR, fixable=True),
    Rule("reflow", "not-equivalent", Severity.ERROR),
    Rule("lint", "multiple-spaces", Severity.ERROR, fixable=True),
    Rule("lint", "space-before-punctuation", Severity.ERROR, fixable=True),
    Rule("lint", "blank-run", Severity.ERROR, fixable=True),
    Rule("lint", "trailing-whitespace", Severity.ERROR, fixable=True),
    Rule("lint", "punctuation-outside-quote", Severity.OFF),
    Rule("lint", "invisible-space", Severity.WARNING),
    Rule("anchors", "missing-file", Severity.ERROR),
    Rule("anchors", "missing-anchor", Severity.ERROR),
    Rule("anchors", "ambiguous-anchor", Severity.WARNING),
    Rule("freshness", "stale", Severity.WARNING),
    Rule("freshness", "missing-review-date", Severity.OFF),
    Rule("freshness", "malformed-review-date", Severity.ERROR),
)

RULES: dict[str, Rule] = {r.rule: r for r in _RULES}

#: The `lint` rules `--write` is allowed to fix. Each is a whitespace deletion
#: inside a single line with exactly one correct outcome.
LINT_FIXABLE: tuple[str, ...] = (
    "multiple-spaces",
    "space-before-punctuation",
    "blank-run",
    "trailing-whitespace",
)


def rules_for(check: str) -> tuple[Rule, ...]:
    """Return every rule owned by *check*, in registry order."""
    return tuple(r for r in _RULES if r.check == check)
