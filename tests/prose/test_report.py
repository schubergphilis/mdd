"""Tests for the finding record and its two emitters."""

from __future__ import annotations

import io
import json
from pathlib import Path

from mdd.prose.report import (
    Finding,
    emit,
    format_human,
    format_json,
    make_excerpt,
    sort_key,
    summarise,
)
from mdd.prose.rules import Severity


def finding(**kwargs: object) -> Finding:
    base: dict[str, object] = {
        "path": Path("a.md"),
        "line": 4,
        "column": 7,
        "check": "lint",
        "rule": "multiple-spaces",
        "message": "2 spaces between words",
        "severity": Severity.ERROR,
        "excerpt": "a  b",
        "fixable": True,
    }
    return Finding(**{**base, **kwargs})  # pyright: ignore[reportArgumentType]


def test_human_format_matches_the_editor_shape() -> None:
    rendered = format_human(finding(), show_excerpt=False)
    assert rendered == "a.md:4:7: error: multiple-spaces: 2 spaces between words"


def test_human_format_appends_the_excerpt() -> None:
    assert format_human(finding(), show_excerpt=True).endswith("\n    a  b")


def test_json_format_carries_every_field() -> None:
    payload = json.loads(format_json(finding(), show_excerpt=True))
    assert payload == {
        "path": "a.md",
        "line": 4,
        "column": 7,
        "severity": "error",
        "check": "lint",
        "rule": "multiple-spaces",
        "message": "2 spaces between words",
        "excerpt": "a  b",
        "fixable": True,
    }


def test_json_format_omits_the_excerpt_on_request() -> None:
    assert "excerpt" not in json.loads(format_json(finding(), show_excerpt=False))


def test_emit_writes_one_record_per_line() -> None:
    stream = io.StringIO()
    emit([finding(), finding(line=9)], stream, json_mode=True, show_excerpt=False)
    assert len(stream.getvalue().splitlines()) == 2


def test_excerpt_windows_around_the_column() -> None:
    text = "x" * 100
    assert make_excerpt(text, 50) == "…" + "x" * 48 + "…"


def test_whole_line_excerpt_is_capped() -> None:
    assert make_excerpt("y" * 200, 0).endswith("…")


def test_short_whole_line_excerpt_is_not_capped() -> None:
    assert make_excerpt("  short  ", 0) == "short"


def test_excerpt_at_the_start_has_no_leading_ellipsis() -> None:
    assert make_excerpt("abc", 1) == "abc"


def test_sort_key_orders_by_path_line_column_rule() -> None:
    ordered = sorted(
        [finding(line=9), finding(line=4, column=2), finding(line=4, column=1)], key=sort_key
    )
    assert [(f.line, f.column) for f in ordered] == [(4, 1), (4, 2), (9, 7)]


def test_summary_when_clean() -> None:
    assert summarise("mdd prose lint", [], 214) == "mdd prose lint: clean (214 files)"


def test_summary_counts_and_pluralises() -> None:
    findings = [finding(), finding(severity=Severity.WARNING, fixable=False)]
    assert summarise("mdd prose check", findings, 214) == (
        "mdd prose check: 1 error, 1 warning in 214 files (1 fixable with --write)"
    )


def test_summary_without_fixables() -> None:
    findings = [finding(fixable=False), finding(fixable=False)]
    assert summarise("mdd prose check", findings, 3) == (
        "mdd prose check: 2 errors, 0 warnings in 3 files"
    )
