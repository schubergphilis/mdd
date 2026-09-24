"""Tests for scripts/spec-check.py link and cross-reference validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"


def _load_spec_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("spec_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["spec_check"] = module
    spec.loader.exec_module(module)
    return module


_module = _load_spec_check()

link_violations: Callable[[Path, int, str, set[str], set[str]], list[str]] = _module.link_violations  # pyright: ignore[reportAny]
core_spec_names: Callable[[tuple[Path, ...]], set[str]] = _module.core_spec_names  # pyright: ignore[reportAny]
collect_violations: Callable[[Path, set[str], set[str]], list[str]] = _module.collect_violations  # pyright: ignore[reportAny]
main: Callable[[], int] = _module.main  # pyright: ignore[reportAny]
xref_violations: Callable[[Path, list[tuple[int, str]]], list[str]] = _module.xref_violations  # pyright: ignore[reportAny]

SIBLINGS = {"S07-data-protection.md"}
CORE = {"S07-data-protection.md", "S14-confluence-sync.md"}


def _check(line: str) -> list[str]:
    return link_violations(Path("S99-x.md"), 3, line, SIBLINGS, CORE)


def test_valid_sibling_link_passes() -> None:
    assert _check("See [data protection](S07-data-protection.md).") == []
    assert _check("See [data protection](./S07-data-protection.md).") == []


def test_broken_sibling_link_reported() -> None:
    violations = _check("See [gone](S42-gone.md).")
    assert len(violations) == 1
    assert "broken sibling link → S42-gone.md" in violations[0]


def test_valid_core_url_passes() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S14-confluence-sync.md"
    assert _check(f"See [confluence sync]({url}).") == []


def test_core_url_ref_is_not_pinned_to_main() -> None:
    base = "https://github.com/schubergphilis/mdd/blob"
    for ref in ("v0.3.0", "9f1c2ab", "release/0.4"):
        url = f"{base}/{ref}/docs/spec/S14-confluence-sync.md"
        assert _check(f"See [{ref}]({url}).") == [], ref


def test_broken_core_url_reported() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md"
    violations = _check(f"See [typo]({url}).")
    assert len(violations) == 1
    assert "broken core spec link → S99-typo.md" in violations[0]


def test_bare_core_url_is_validated_too() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md"
    assert len(_check(url)) == 1


def test_urls_to_other_repos_are_ignored() -> None:
    assert (
        _check("[wrapper](https://github.com/lsimons/mdd-wrapper/blob/main/docs/spec/S99-x.md)")
        == []
    )


def test_core_names_union_over_reachable_checkouts(tmp_path: Path) -> None:
    local = tmp_path / "docs" / "spec"
    sibling = tmp_path / "core" / "docs" / "spec"
    local.mkdir(parents=True)
    sibling.mkdir(parents=True)
    _ = (local / "S44-open-source-split.md").write_text("", encoding="utf-8")
    _ = (sibling / "S14-confluence-sync.md").write_text("", encoding="utf-8")

    names = core_spec_names((local, sibling, tmp_path / "absent"))

    assert names == {"S44-open-source-split.md", "S14-confluence-sync.md"}


def test_links_inside_code_fences_are_skipped(tmp_path: Path) -> None:
    spec = tmp_path / "S99-x.md"
    _ = spec.write_text(
        "**Status:** Draft\n\n"
        "```markdown\n"
        "[gone](S42-gone.md)\n"
        "[typo](https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md)\n"
        "```\n",
        encoding="utf-8",
    )

    assert collect_violations(spec, SIBLINGS, CORE) == []


def _xref(*lines: str) -> list[str]:
    return xref_violations(Path("S99-x.md"), list(enumerate(lines, 10)))


def test_xref_relative_links_into_plan_and_research_reported() -> None:
    for target in (
        "../plan/P03-module-split.md",
        "../research/R02-attachments.md",
        "./../../docs/plan/",
        "research/004-foo.md",
    ):
        violations = _xref(f"See [the note]({target}).")
        assert any(f"link into plan/research → {target}" in v for v in violations), target


def test_xref_external_and_sibling_links_pass() -> None:
    assert _xref("See [S07](S07-data-protection.md).") == []
    assert _xref("See [upstream](https://example.com/research/paper.html).") == []


def test_xref_plan_and_research_numbers_reported() -> None:
    for token in ("P03", "P07", "R14", "R004"):
        violations = _xref(f"That was retired in {token} phase 5.")
        assert len(violations) == 1, token
        assert f"plan/research number {token!r}" in violations[0]


def test_xref_prose_forms_reported_once() -> None:
    for phrase in ("research 004", "research note R04", "Research doc 004", "plan 12"):
        violations = _xref(f"As described in {phrase}, this holds.")
        assert len(violations) == 1, phrase
        assert f"plan/research reference {phrase!r}" in violations[0]


def test_xref_legit_tokens_pass() -> None:
    assert _xref("The R1, R2, R3 and R4 round-trip gates must pass.") == []
    assert _xref("See S33 and the p95 latency; tests live in test_r12_x.py.") == []
    assert _xref("Specs and research notes are published; the plan is simple.") == []


def test_xref_credit_sentence_allowed() -> None:
    assert _xref("Originates from research note R03.") == []
    assert _xref("Originates from research note R02 (attachments).") == []
    assert _xref("Originates from", "research note R02.") == []


def test_xref_other_references_next_to_credit_still_reported() -> None:
    violations = _xref("Originates from research note R03; deferred per research note R03.")
    assert len(violations) == 1
    assert "'research note R03'" in violations[0]


def test_xref_matches_across_line_wrap_and_reports_start_line() -> None:
    violations = _xref("This is the pull side described in", "research", "note R02. More.")
    assert len(violations) == 1
    assert violations[0].startswith("S99-x.md:11: xref:")


def test_xref_skips_code_fences_and_does_not_join_paragraphs(tmp_path: Path) -> None:
    spec = tmp_path / "S99-x.md"
    _ = spec.write_text(
        "**Status:** Draft\n\n"
        "A paragraph ending in research\n\n"
        "note R02-like text is a new paragraph.\n\n"
        "```text\n"
        "research note R02 and P03 in a fence\n"
        "```\n"
        "Retired in P03 phase 5.\n",
        encoding="utf-8",
    )

    violations = collect_violations(spec, SIBLINGS, CORE)

    assert violations == [
        f"{spec}:5: xref: plan/research number 'R02'"
        " (specs must stand alone; copy the content in instead)",
        f"{spec}:10: xref: plan/research number 'P03'"
        " (specs must stand alone; copy the content in instead)",
    ]


def test_main_notes_that_xref_does_not_prove_self_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_dir = tmp_path / "docs" / "spec"
    spec_dir.mkdir(parents=True)
    _ = (spec_dir / "000-specs.md").write_text("Plans are P01, notes R01.\n", encoding="utf-8")
    _ = (spec_dir / "S99-x.md").write_text(
        "**Status:** Draft\n\nRetired in P03.\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert main() == 1

    captured = capsys.readouterr()
    assert "S99-x.md:3: xref:" in captured.out
    assert "000-specs.md" not in captured.out
    assert "does not prove a spec is self-contained" in captured.err
