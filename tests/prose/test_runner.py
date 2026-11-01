"""Tests for the shared runner: the reflow write gates and CLI-level argument types."""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from mdd.commands.prose import _iso_date, _positive_int  # pyright: ignore[reportPrivateUsage]
from mdd.prose import gate, lint, runner
from mdd.prose.config import LintConfig, ProseConfig
from mdd.prose.lint import Edit
from mdd.prose.rules import RULES, Severity

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from mdd.prose.classify import Line

LONG = (
    "One sentence that is quite long and carries a clause, and then keeps going for "
    "long enough that the reflow has to break it somewhere. A second sentence.\n"
)


def config() -> ProseConfig:
    return ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})


def strict() -> ProseConfig:
    """Hard breaks not allowed: they are reported, and the fix leaves them alone."""
    return replace(config(), lint=LintConfig(allow_hard_break=False))


def damaging_fixer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the lint fix delete the trailing run, hard break and all, so the gate refuses."""

    def delete_every_run(
        line: Line, _config: LintConfig, *, breaks: bool, continued_construct: bool
    ) -> Iterable[Edit]:
        stripped = line.text.rstrip(" ")
        if stripped != line.text:
            yield Edit("trailing-whitespace", len(stripped), len(line.text), "", "damaged")

    monkeypatch.setattr(lint, "_trailing_whitespace", delete_every_run)


def options(**kwargs: object) -> runner.RunOptions:
    base: dict[str, object] = {"checks": ("reflow",), "as_of": dt.date(2026, 8, 24)}
    return runner.RunOptions(**{**base, **kwargs})  # pyright: ignore[reportArgumentType]


def test_non_equivalent_reflow_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")

    def never_equivalent(before: str, after: str) -> gate.Verdict:
        return gate.Verdict(passed=False, line=1, reason="test refusal")

    monkeypatch.setattr(gate, "verify", never_equivalent)
    result = runner.run([target], config(), options(write=True))
    assert "not-equivalent" in [f.rule for f in result.findings]
    assert target.read_text(encoding="utf-8") == LONG
    assert result.written == 0


def test_successful_reflow_write_drops_the_fixable_finding(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    result = runner.run([target], config(), options(write=True))
    assert result.findings == []
    assert result.written == 1


def test_reflow_off_reports_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    from dataclasses import replace

    cfg = replace(config(), severities={**config().severities, "reflow": Severity.OFF})
    result = runner.run([target], cfg, options(write=True))
    assert result.written == 0
    assert target.read_text(encoding="utf-8") == LONG


def test_a_refused_reflow_is_reported_as_unfixable_without_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")

    def never_equivalent(before: str, after: str) -> gate.Verdict:
        return gate.Verdict(passed=False, line=1, reason="test refusal")

    monkeypatch.setattr(gate, "verify", never_equivalent)
    found = runner.run([target], config(), options()).findings
    assert [(f.rule, f.fixable) for f in found] == [("reflow", False), ("not-equivalent", False)]
    assert found[1].message == (
        "the reflow fix would change the document (at line 1: test refusal); "
        "--write leaves this file unchanged"
    )


# A three-space hard break: deleting the run, as `trailing-whitespace` does,
# joins the two lines into one.
HARD_BREAK = "Intro.\n\nFirst line  \nsecond line.\n"


def test_lint_write_refuses_a_fix_that_drops_a_hard_break(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    damaging_fixer(monkeypatch)
    target = tmp_path / "a.md"
    _ = target.write_text(HARD_BREAK, encoding="utf-8")
    result = runner.run([target], config(), options(checks=("lint",), write=True))
    assert target.read_text(encoding="utf-8") == HARD_BREAK
    assert result.written == 0
    assert [(f.rule, f.line, f.fixable) for f in result.findings] == [
        ("trailing-whitespace", 3, False),
        ("not-equivalent", 3, False),
    ]
    assert "a hard line break was lost" in result.findings[1].message


def test_lint_check_and_write_agree_on_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    damaging_fixer(monkeypatch)
    target = tmp_path / "a.md"
    _ = target.write_text(HARD_BREAK, encoding="utf-8")
    checked = runner.run([target], config(), options(checks=("lint",))).findings
    written = runner.run([target], config(), options(checks=("lint",), write=True)).findings
    assert checked == written


def test_strict_lint_write_keeps_a_hard_break_and_fixes_the_rest(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("Intro.\n\nTwo  spaces  \nsecond line.\n", encoding="utf-8")
    result = runner.run([target], strict(), options(checks=("lint",), write=True))
    assert result.written == 1
    assert target.read_text(encoding="utf-8") == "Intro.\n\nTwo spaces  \nsecond line.\n"
    assert [(f.rule, f.line, f.fixable) for f in result.findings] == [
        ("trailing-whitespace", 3, False)
    ]


def test_lint_write_keeps_a_long_hard_break(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("Intro.\n\nFirst line   \nsecond line.\n", encoding="utf-8")
    result = runner.run([target], config(), options(checks=("lint",), write=True))
    assert result.findings == []
    assert result.written == 1
    assert target.read_text(encoding="utf-8") == HARD_BREAK


def test_lint_write_applies_a_fix_that_passes_the_gate(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("Intro.\n\nTwo  spaces.   \n", encoding="utf-8")
    checked = runner.run([target], config(), options(checks=("lint",))).findings
    assert [(f.rule, f.fixable) for f in checked] == [
        ("multiple-spaces", True),
        ("trailing-whitespace", True),
    ]
    result = runner.run([target], config(), options(checks=("lint",), write=True))
    assert result.findings == []
    assert result.written == 1
    assert target.read_text(encoding="utf-8") == "Intro.\n\nTwo spaces.\n"


def test_write_runs_one_writer_at_a_time() -> None:
    with pytest.raises(ValueError, match="one writer at a time"):
        _ = options(checks=("reflow", "lint"), write=True)
    assert options(checks=("reflow", "lint")).checks == ("reflow", "lint")


def test_iso_date_type_rejects_junk() -> None:
    assert _iso_date("2026-08-24") == dt.date(2026, 8, 24)
    with pytest.raises(argparse.ArgumentTypeError, match="ISO-8601"):
        _ = _iso_date("yesterday")


def test_positive_int_type_rejects_junk() -> None:
    assert _positive_int("7") == 7
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        _ = _positive_int("nope")
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        _ = _positive_int("0")


def test_a_failed_write_is_a_cross_cutting_finding(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    _ = real.write_text("Intro.\n\nTwo  spaces.\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    result = runner.run([link], config(), options(checks=("lint",), write=True))
    failures = [f for f in result.findings if f.rule == "write-failed"]
    assert [(f.check, f.line) for f in failures] == [("prose", 0)]
    assert "symlink" in failures[0].message
    assert result.failed


WRAPPED = (
    "This paragraph is wrapped at a fixed width and not at sentence ends. It\n"
    "has a second sentence that starts at the end of the first line. And a\n"
    "third one that does the same thing again.\n"
)


def test_a_wrapped_paragraph_is_reported_on_every_line(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(WRAPPED, encoding="utf-8")
    result = runner.run([target], config(), options())
    assert {f.line for f in result.findings if f.rule == "reflow"} == {1, 2, 3}


@pytest.mark.parametrize(
    "directive",
    [
        pytest.param("<!-- mdd-prose-ignore: reflow -->\n", id="line"),
        pytest.param("<!-- mdd-prose-ignore -->\n", id="bare"),
    ],
)
def test_a_line_directive_covers_the_whole_paragraph_below_for_reflow(
    tmp_path: Path, directive: str
) -> None:
    target = tmp_path / "a.md"
    source = directive + WRAPPED
    _ = target.write_text(source, encoding="utf-8")
    assert runner.run([target], config(), options()).findings == []
    written = runner.run([target], config(), options(write=True))
    assert written.findings == []
    assert target.read_text(encoding="utf-8") == source


def test_a_reflow_directive_over_a_clean_paragraph_is_unused(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(
        "<!-- mdd-prose-ignore: reflow -->\nOne sentence.\nAnother sentence.\n", encoding="utf-8"
    )
    cfg = replace(
        config(), severities={**config().severities, "unused-suppression": Severity.WARNING}
    )
    result = runner.run([target], cfg, options())
    assert [(f.rule, f.line) for f in result.findings] == [("unused-suppression", 1)]


def test_a_lint_directive_still_covers_only_its_next_line(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(
        "<!-- mdd-prose-ignore: trailing-whitespace -->\nFirst line. \nSecond line. \n",
        encoding="utf-8",
    )
    result = runner.run([target], config(), options(checks=("lint",)))
    assert [(f.rule, f.line) for f in result.findings] == [("trailing-whitespace", 3)]
