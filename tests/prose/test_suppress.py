"""Tests for suppression comments."""

from __future__ import annotations

from pathlib import Path

from mdd.prose.classify import Classified, classify
from mdd.prose.config import ProseConfig
from mdd.prose.rules import RULES, Severity
from mdd.prose.suppress import audit, collect

PATH = Path("doc.md")


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified)
    return result


def config(**severities: Severity) -> ProseConfig:
    base = {rule.rule: rule.default for rule in RULES.values()}
    return ProseConfig(severities={**base, **severities})


def test_named_rule_suppresses_the_next_line() -> None:
    doc = ok("<!-- mdd-prose-ignore: multiple-spaces -->\na  b\n")
    suppressions = collect(doc.lines)
    assert suppressions.suppresses(2, "multiple-spaces")
    assert not suppressions.suppresses(2, "trailing-whitespace")
    assert not suppressions.suppresses(3, "multiple-spaces")


def test_bare_form_suppresses_every_rule() -> None:
    suppressions = collect(ok("<!-- mdd-prose-ignore -->\na  b\n").lines)
    assert suppressions.suppresses(2, "anything-at-all")


def test_comma_separated_list() -> None:
    doc = ok("<!-- mdd-prose-ignore: multiple-spaces, blank-run -->\na  b\n")
    suppressions = collect(doc.lines)
    assert suppressions.suppresses(2, "multiple-spaces")
    assert suppressions.suppresses(2, "blank-run")


def test_file_wide_form_applies_anywhere() -> None:
    doc = ok("a  b\n\n<!-- mdd-prose-ignore-file: multiple-spaces -->\n")
    suppressions = collect(doc.lines)
    assert suppressions.suppresses(1, "multiple-spaces")
    assert suppressions.suppresses(99, "multiple-spaces")
    assert not suppressions.suppresses(1, "blank-run")


def test_bare_file_wide_form() -> None:
    suppressions = collect(ok("<!-- mdd-prose-ignore-file -->\n").lines)
    assert suppressions.suppresses(50, "reflow")


def test_unknown_rule_id_is_a_warning() -> None:
    doc = ok("<!-- mdd-prose-ignore: no-such-rule -->\na\n")
    findings = audit(PATH, collect(doc.lines), config())
    assert [(f.rule, f.severity) for f in findings] == [("unknown-suppression", Severity.WARNING)]


def test_unused_suppression_is_off_by_default() -> None:
    doc = ok("<!-- mdd-prose-ignore: multiple-spaces -->\nclean line\n")
    assert audit(PATH, collect(doc.lines), config()) == []


def test_unused_suppression_when_enabled() -> None:
    doc = ok("<!-- mdd-prose-ignore: multiple-spaces -->\nclean line\n")
    cfg = config(**{"unused-suppression": Severity.WARNING})
    findings = audit(PATH, collect(doc.lines), cfg)
    assert [f.rule for f in findings] == ["unused-suppression"]


def test_a_used_suppression_is_not_reported_as_unused() -> None:
    doc = ok("<!-- mdd-prose-ignore: multiple-spaces -->\na  b\n")
    suppressions = collect(doc.lines)
    assert suppressions.suppresses(2, "multiple-spaces")
    cfg = config(**{"unused-suppression": Severity.WARNING})
    assert audit(PATH, suppressions, cfg) == []


def test_unknown_suppression_off_reports_nothing() -> None:
    doc = ok("<!-- mdd-prose-ignore: no-such-rule -->\na\n")
    cfg = config(**{"unknown-suppression": Severity.OFF})
    assert audit(PATH, collect(doc.lines), cfg) == []


def test_bare_form_is_never_an_unknown_rule() -> None:
    doc = ok("<!-- mdd-prose-ignore -->\na  b\n")
    assert audit(PATH, collect(doc.lines), config()) == []
