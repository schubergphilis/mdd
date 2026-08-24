"""Tests for the freshness gate."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

from mdd.prose.config import FreshnessConfig, ProseConfig
from mdd.prose.freshness import run
from mdd.prose.rules import RULES, Severity

PATH = Path("doc.md")
TODAY = dt.date(2026, 8, 24)


def config(**kwargs: object) -> ProseConfig:
    base = ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})
    return replace(base, **kwargs)  # pyright: ignore[reportAny]


def rules(text: str, cfg: ProseConfig | None = None, only: str | None = None) -> list[str]:
    return [f.rule for f in run(PATH, text, cfg or config(), as_of=TODAY, only=only)]


def test_fresh_file_is_clean() -> None:
    assert rules("---\nlast-verified: 2026-08-01\n---\n\nBody.\n") == []


def test_stale_file_is_a_warning() -> None:
    text = "---\nlast-verified: 2020-01-01\n---\n\nBody.\n"
    findings = run(PATH, text, config(), as_of=TODAY)
    assert [f.rule for f in findings] == ["stale"]
    assert findings[0].severity is Severity.WARNING
    assert "over the 180-day threshold" in findings[0].message


def test_missing_field_is_off_by_default() -> None:
    assert rules("---\ntitle: a\n---\n\nBody.\n") == []


def test_missing_field_when_enabled() -> None:
    cfg = config(severities={"missing-review-date": Severity.WARNING})
    assert rules("---\ntitle: a\n---\n\nBody.\n", cfg) == ["missing-review-date"]


def test_no_frontmatter_at_all_counts_as_missing() -> None:
    cfg = config(severities={"missing-review-date": Severity.WARNING})
    assert rules("Body only.\n", cfg) == ["missing-review-date"]


def test_malformed_date_is_an_error() -> None:
    assert rules("---\nlast-verified: yesterday\n---\n") == ["malformed-review-date"]


def test_date_objects_from_yaml_are_accepted() -> None:
    assert rules("---\nlast-verified: 2026-08-01\n---\n") == []


def test_datetime_is_accepted() -> None:
    assert rules("---\nlast-verified: 2026-08-01 10:00:00\n---\n") == []


def test_non_scalar_value_is_malformed() -> None:
    assert rules("---\nlast-verified: [1, 2]\n---\n") == ["malformed-review-date"]


def test_configured_field_name_is_honoured() -> None:
    cfg = config(freshness=FreshnessConfig(review_field="reviewed", max_age_days=10))
    assert rules("---\nreviewed: 2020-01-01\n---\n", cfg) == ["stale"]


def test_only_missing_skips_the_staleness_check() -> None:
    assert rules("---\nlast-verified: 2020-01-01\n---\n", only="missing") == []


def test_only_stale_skips_the_missing_check() -> None:
    cfg = config(severities={"missing-review-date": Severity.WARNING})
    assert rules("---\ntitle: a\n---\n", cfg, only="stale") == []


def test_rules_set_to_off_report_nothing() -> None:
    cfg = config(severities={"stale": Severity.OFF, "malformed-review-date": Severity.OFF})
    assert rules("---\nlast-verified: 2020-01-01\n---\n", cfg) == []
    assert rules("---\nlast-verified: nope\n---\n", cfg) == []


def test_finding_is_whole_file() -> None:
    findings = run(PATH, "---\nlast-verified: 2020-01-01\n---\n", config(), as_of=TODAY)
    assert (findings[0].line, findings[0].column) == (0, 0)
    assert findings[0].check == "freshness"
