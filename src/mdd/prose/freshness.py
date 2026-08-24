"""``mdd prose freshness`` — content that goes stale.

``--as-of DATE`` overrides "today" so the check is reproducible in a test and
in a CI job rebuilt from an old commit. Without it the check is a pure function
of the corpus *and the clock*, which is as deterministic as a freshness check
can be.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from mdd.prose.report import Finding
from mdd.prose.rules import Severity
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.prose.config import ProseConfig


def _coerce_date(value: object) -> dt.date | None:
    """Return *value* as a date, or ``None`` when it is not an ISO-8601 date."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _finding(path: Path, rule: str, message: str, config: ProseConfig) -> Finding:
    return Finding(
        path=path,
        line=0,
        column=0,
        check="freshness",
        rule=rule,
        message=message,
        severity=config.severity(rule),
    )


def _report(path: Path, rule: str, message: str, config: ProseConfig) -> list[Finding]:
    if config.severity(rule) is Severity.OFF:
        return []
    return [_finding(path, rule, message, config)]


def _review_value(text: str, field: str) -> object | None:
    split = split_frontmatter(text)
    mapping = parse_yaml_mapping(split[0]) if split is not None else None
    return mapping.get(field) if mapping is not None else None


def run(
    path: Path,
    text: str,
    config: ProseConfig,
    *,
    as_of: dt.date,
    only: str | None = None,
) -> list[Finding]:
    """Check *path*'s review date. *only* narrows the run to ``missing`` or ``stale``."""
    field = config.freshness.review_field
    raw = _review_value(text, field)

    if raw is None:
        if only == "stale":
            return []
        return _report(path, "missing-review-date", f"no {field!r} field in frontmatter", config)
    if only == "missing":
        return []

    parsed = _coerce_date(raw)
    if parsed is None:
        message = f"{field}: {raw!r} is not an ISO-8601 date"
        return _report(path, "malformed-review-date", message, config)

    age = (as_of - parsed).days
    if age <= config.freshness.max_age_days:
        return []
    message = f"{field} is {age} days old, over the {config.freshness.max_age_days}-day threshold"
    return _report(path, "stale", message, config)
