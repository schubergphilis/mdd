"""CLI-level tests for `mdd prose`, driving the real argparse dispatcher."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mdd.cli import main as cli_main

if TYPE_CHECKING:
    from pathlib import Path

MESSY = "A sentence.  With two spaces and a space before a comma , and trailing space.   \n"
MIRRORED = "---\nconfluence:\n  page_id: '1'\n---\n\nA sentence.  Two spaces.\n"
LONG = (
    "One sentence that is quite long and carries a clause, and then keeps going for "
    "long enough that the reflow has to break it somewhere. A second sentence.\n"
)


def prose(args: list[str]) -> int:
    return cli_main(["prose", *args])


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "docs").mkdir()
    return tmp_path / "docs"


def test_group_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert prose([]) == 0
    assert "reflow" in capsys.readouterr().out


def test_lint_reports_and_exits_one(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    assert prose(["lint", "docs"]) == 1
    captured = capsys.readouterr()
    assert "multiple-spaces" in captured.out
    assert "space-before-punctuation" in captured.out
    assert "trailing-whitespace" in captured.out
    assert "errors" in captured.err


def test_clean_corpus_exits_zero(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text("A clean sentence.\n", encoding="utf-8")
    assert prose(["lint", "docs"]) == 0
    assert "clean (1 files)" in capsys.readouterr().err


def test_lint_write_fixes_and_then_passes(corpus: Path) -> None:
    target = corpus / "a.md"
    _ = target.write_text(MESSY, encoding="utf-8")
    assert prose(["lint", "--write", "docs"]) == 0
    assert target.read_text(encoding="utf-8") == (
        "A sentence. With two spaces and a space before a comma, and trailing space.\n"
    )
    assert prose(["lint", "docs"]) == 0


def test_lint_write_refuses_a_mirrored_file(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = corpus / "a.md"
    _ = target.write_text(MIRRORED, encoding="utf-8")
    assert prose(["lint", "--write", "docs"]) == 1
    assert "mirrored-file" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == MIRRORED


def test_allow_mirror_overrides_the_refusal(corpus: Path) -> None:
    target = corpus / "a.md"
    _ = target.write_text(MIRRORED, encoding="utf-8")
    assert prose(["lint", "--write", "--allow-mirror", "docs"]) == 0
    assert target.read_text(encoding="utf-8").endswith("A sentence. Two spaces.\n")


def test_write_with_json_is_a_usage_error(corpus: Path) -> None:
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _ = prose(["lint", "--write", "--json", "docs"])
    assert exc.value.code == 2


def test_json_output_is_line_delimited(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    assert prose(["lint", "--json", "docs"]) == 1
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records
    assert {"path", "line", "column", "severity", "check", "rule", "message"} <= set(records[0])


def test_no_excerpt_omits_the_quoted_fragment(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    assert prose(["lint", "--no-excerpt", "--json", "docs"]) == 1
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all("excerpt" not in record for record in records)


def test_ignored_files_are_not_linted(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    _ = (corpus / ".mddignore").write_text("a.md\n", encoding="utf-8")
    assert prose(["lint", "docs"]) == 0
    assert "clean (0 files)" in capsys.readouterr().err


def test_ignored_files_are_not_written(corpus: Path) -> None:
    target = corpus / "a.md"
    _ = target.write_text(MESSY, encoding="utf-8")
    _ = (corpus / ".mddignore").write_text("a.md\n", encoding="utf-8")
    assert prose(["lint", "--write", "docs"]) == 0
    assert target.read_text(encoding="utf-8") == MESSY


def test_min_severity_warning_gates_on_warnings(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ = (corpus / "a.md").write_text("A sentence with a space.\n", encoding="utf-8")
    assert prose(["lint", "docs"]) == 0
    assert prose(["lint", "--min-severity", "warning", "docs"]) == 1
    assert "invisible-space" in capsys.readouterr().out


def test_anchors_reports_a_broken_link(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text("# Title\n\n[x](#nope)\n", encoding="utf-8")
    assert prose(["anchors", "docs"]) == 1
    assert "missing-anchor" in capsys.readouterr().out


def test_reflow_check_only_does_not_write(corpus: Path) -> None:
    target = corpus / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    assert prose(["reflow", "docs"]) == 1
    assert target.read_text(encoding="utf-8") == LONG


def test_reflow_write_applies_and_is_idempotent(corpus: Path) -> None:
    target = corpus / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    assert prose(["reflow", "--write", "docs"]) == 0
    first = target.read_text(encoding="utf-8")
    assert first != LONG
    assert prose(["reflow", "docs"]) == 0


def test_reflow_width_override(corpus: Path) -> None:
    target = corpus / "a.md"
    clauses = "Alpha beta gamma, delta epsilon zeta, eta theta iota, kappa lambda mu.\n"
    _ = target.write_text(clauses, encoding="utf-8")
    assert prose(["reflow", "docs"]) == 0
    assert prose(["reflow", "--write", "--width", "30", "--min-line", "5", "docs"]) == 0
    assert len(target.read_text(encoding="utf-8").splitlines()) == 4


def test_freshness_needs_configuring_but_the_subcommand_still_runs(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ = (corpus / "a.md").write_text("---\nlast-verified: 2000-01-01\n---\n", encoding="utf-8")
    assert prose(["freshness", "--as-of", "2026-08-24", "--min-severity", "warning", "docs"]) == 1
    assert "stale" in capsys.readouterr().out


def test_freshness_max_age_override(corpus: Path) -> None:
    _ = (corpus / "a.md").write_text("---\nlast-verified: 2026-08-01\n---\n", encoding="utf-8")
    args = ["freshness", "--as-of", "2026-08-24", "--max-age", "5", "--min-severity", "warning"]
    assert prose([*args, "docs"]) == 1


def test_check_runs_the_default_set_only(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text(LONG + MESSY, encoding="utf-8")
    assert prose(["check", "docs"]) == 1
    out = capsys.readouterr().out
    assert "multiple-spaces" in out
    assert "reflow" not in out


def test_check_honours_a_config_that_enables_reflow(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = corpus.parent / "prose.yaml"
    _ = config.write_text("prose:\n  checks:\n    reflow: error\n", encoding="utf-8")
    _ = (corpus / "a.md").write_text(LONG, encoding="utf-8")
    assert prose(["check", "--config", str(config), "docs"]) == 1
    assert "reflow" in capsys.readouterr().out


def test_check_with_every_check_off_exits_zero(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = corpus.parent / "prose.yaml"
    _ = config.write_text("prose:\n  checks:\n    lint: off\n    anchors: off\n", encoding="utf-8")
    _ = (corpus / "a.md").write_text(MESSY, encoding="utf-8")
    assert prose(["check", "--config", str(config), "docs"]) == 0
    assert "no enabled checks" in capsys.readouterr().err


def test_missing_config_is_an_operational_failure(corpus: Path) -> None:
    assert prose(["lint", "--config", "absent.yaml", "docs"]) == 1


def test_absent_path_is_an_operational_failure(corpus: Path) -> None:
    assert prose(["lint", "nope"]) == 1


def test_unparseable_file_is_reported_and_skipped(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ = (corpus / "a.md").write_text("```\nunclosed\n", encoding="utf-8")
    assert prose(["lint", "docs"]) == 1
    assert "parse-error" in capsys.readouterr().out


def test_suppression_comment_silences_a_finding(corpus: Path) -> None:
    _ = (corpus / "a.md").write_text(
        "<!-- mdd-prose-ignore: multiple-spaces -->\nA  b.\n", encoding="utf-8"
    )
    assert prose(["lint", "docs"]) == 0


def test_unknown_suppression_is_reported(corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ = (corpus / "a.md").write_text("<!-- mdd-prose-ignore: nope -->\nA b.\n", encoding="utf-8")
    assert prose(["lint", "--min-severity", "warning", "docs"]) == 1
    assert "unknown-suppression" in capsys.readouterr().out


def test_only_unfixable_findings_leave_the_file_alone(corpus: Path) -> None:
    target = corpus / "a.md"
    text = "A sentence with a space.\n"
    _ = target.write_text(text, encoding="utf-8")
    assert prose(["lint", "--write", "docs"]) == 0
    assert target.read_text(encoding="utf-8") == text


def test_whitespace_inside_masked_constructs_survives_a_write(corpus: Path) -> None:
    target = corpus / "a.md"
    text = "Run `a  b ;` and see  this.\n"
    _ = target.write_text(text, encoding="utf-8")
    assert prose(["lint", "--write", "docs"]) == 0
    assert target.read_text(encoding="utf-8") == "Run `a  b ;` and see this.\n"


def test_unreadable_file_is_an_operational_failure(corpus: Path) -> None:
    _ = (corpus / "a.md").write_bytes(b"\xff\xfe\x00bad")
    assert prose(["lint", "docs"]) == 1
