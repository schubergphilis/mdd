"""Tests for the mechanical lint and its whitespace autofixes."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from mdd.prose.classify import Classified, classify, join_lines
from mdd.prose.config import LintConfig, ProseConfig
from mdd.prose.lint import apply_edits, run
from mdd.prose.rules import RULES, Severity

PATH = Path("doc.md")


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified)
    return result


def defaults(**kwargs: object) -> ProseConfig:
    base = ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})
    return replace(base, **kwargs)  # pyright: ignore[reportAny]


def rules_found(text: str, config: ProseConfig | None = None) -> list[str]:
    outcome = run(PATH, ok(text), config or defaults())
    return [finding.rule for finding in outcome.findings]


def fixed_text(text: str, config: ProseConfig | None = None) -> str:
    outcome = run(PATH, ok(text), config or defaults())
    assert outcome.fixed is not None
    return join_lines(
        [line.text for line in outcome.fixed.lines],
        outcome.fixed.newline,
        final_newline=outcome.fixed.final_newline,
    )


def test_multiple_spaces_is_found_and_fixed() -> None:
    assert rules_found("a  b\n") == ["multiple-spaces"]
    assert fixed_text("a  b\n") == "a b\n"


def test_multiple_spaces_inside_code_is_ignored() -> None:
    assert rules_found("a `b  c` d\n") == []


def test_space_before_punctuation_is_found_and_fixed() -> None:
    assert rules_found("a word ; then\n") == ["space-before-punctuation"]
    assert fixed_text("a word ; then\n") == "a word; then\n"


def test_space_before_punctuation_inside_code_is_ignored() -> None:
    assert rules_found("run `foo ;` now\n") == []


def test_space_before_a_file_extension_is_not_a_finding() -> None:
    assert rules_found("an untracked local-authored .md file\n") == []


def test_space_before_an_ellipsis_is_not_a_finding() -> None:
    assert rules_found("the list is `a`, `b`, ...) and more\n") == []


def test_space_before_a_port_number_is_not_a_finding() -> None:
    assert rules_found("bind to the host :8080 instead\n") == []


def test_trailing_whitespace_allows_the_two_space_hard_break() -> None:
    assert rules_found("a  \nb\n") == []
    assert rules_found("a   \nb\n") == ["trailing-whitespace"]


def test_strict_mode_rejects_the_hard_break() -> None:
    config = defaults(lint=LintConfig(allow_hard_break=False))
    assert rules_found("a  \nb\n", config) == ["trailing-whitespace"]
    assert fixed_text("a  \nb\n", config) == "a\nb\n"


def test_trailing_tab_is_always_a_finding() -> None:
    assert rules_found("a\t\nb\n") == ["trailing-whitespace"]


def test_blank_run_is_found_and_collapsed() -> None:
    assert rules_found("a\n\n\n\nb\n") == ["blank-run", "blank-run"]
    assert fixed_text("a\n\n\n\nb\n") == "a\n\nb\n"


def test_blank_line_inside_a_fence_is_not_a_blank_run() -> None:
    assert rules_found("```\n\n\n```\n") == []


def test_whitespace_only_blank_line_is_trimmed() -> None:
    assert rules_found("a\n   \nb\n") == ["trailing-whitespace"]
    assert fixed_text("a\n   \nb\n") == "a\n\nb\n"


def test_invisible_space_is_a_warning_and_not_fixable() -> None:
    outcome = run(PATH, ok("a b\n"), defaults())
    assert [f.rule for f in outcome.findings] == ["invisible-space"]
    assert outcome.findings[0].severity is Severity.WARNING
    assert not outcome.findings[0].fixable
    assert outcome.fixed is None


def test_punctuation_outside_quote_is_off_by_default() -> None:
    assert rules_found('he said "a thing", and left\n') == []


def test_punctuation_outside_quote_when_enabled() -> None:
    config = defaults(severities={"punctuation-outside-quote": Severity.ERROR})
    assert rules_found('he said "a thing", and left\n', config) == ["punctuation-outside-quote"]


def test_literal_quoted_span_is_skipped() -> None:
    config = defaults(severities={"punctuation-outside-quote": Severity.ERROR})
    assert rules_found('the flag is "--dry-run", not the other\n', config) == []


def test_configured_literal_pattern_is_skipped() -> None:
    config = defaults(
        severities={"punctuation-outside-quote": Severity.ERROR},
        lint=LintConfig(literal_quote_patterns=(re.compile(r"^mdd "),)),
    )
    assert rules_found('run "mdd prose check", then stop\n', config) == []


def test_outside_convention_inverts_the_check() -> None:
    config = defaults(
        severities={"punctuation-outside-quote": Severity.ERROR},
        lint=LintConfig(quote_punctuation="outside"),
    )
    assert rules_found('he said "a thing," and left\n', config) == ["punctuation-outside-quote"]
    assert rules_found('he said "a thing", and left\n', config) == []


def test_quote_convention_off_reports_nothing() -> None:
    config = defaults(
        severities={"punctuation-outside-quote": Severity.ERROR},
        lint=LintConfig(quote_punctuation="off"),
    )
    assert rules_found('he said "a thing", and left\n', config) == []


def test_a_rule_set_to_off_is_neither_reported_nor_fixed() -> None:
    config = defaults(severities={"multiple-spaces": Severity.OFF})
    outcome = run(PATH, ok("a  b\n"), config)
    assert outcome.findings == ()
    assert outcome.fixed is None


def test_fixing_is_idempotent() -> None:
    once = fixed_text("a  b ; c   \n\n\n\nd\n")
    assert rules_found(once) == []


def test_masked_whitespace_survives_a_fix() -> None:
    text = "a `b  c` d  e\n"
    assert fixed_text(text) == "a `b  c` d e\n"


def test_non_prose_lines_are_untouched() -> None:
    text = "| a  | b  |\n|---|---|\n| 1  | 2 |\n"
    assert rules_found(text) == []


def test_apply_edits_applies_right_to_left() -> None:
    from mdd.prose.lint import Edit

    edits = [
        Edit(rule="r", start=0, end=1, replacement="X", message=""),
        Edit(rule="r", start=4, end=5, replacement="Y", message=""),
    ]
    assert apply_edits("abcde", edits) == "XbcdY"


def test_findings_carry_a_column_and_an_excerpt() -> None:
    outcome = run(PATH, ok("word  word\n"), defaults())
    finding = outcome.findings[0]
    assert finding.column == 5
    assert finding.excerpt == "word  word"
    assert finding.check == "lint"
