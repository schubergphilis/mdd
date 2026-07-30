"""Tests for mdd.ai.reports — markdown rendering of review findings."""

from __future__ import annotations

from pathlib import Path

from mdd.ai.judges import (
    DuplicateFinding,
    InconsistencyFinding,
    ReviewSummary,
    StaleFinding,
)
from mdd.ai.reports import choose_report_path, render_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_summary(**kwargs: int) -> ReviewSummary:
    s = ReviewSummary()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_duplicates_section_present(self) -> None:
        findings = [
            DuplicateFinding(
                path_a=Path("A.md"),
                path_b=Path("B.md"),
                overlap="high",
                summary="Both cover the same onboarding steps.",
                shared_sections=["laptop provisioning", "IT portal"],
                suggested_action="Merge into B.md and deprecate A.md.",
            )
        ]
        md = render_report(
            duplicates=findings,
            scope="Engineering",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "## Likely duplicates" in md
        assert "`A.md` ↔ `B.md`" in md
        assert "laptop provisioning" in md
        assert "Merge into B.md" in md

    def test_no_duplicates_message(self) -> None:
        md = render_report(
            duplicates=[],
            scope="test",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "_No high-overlap pairs found._" in md

    def test_inconsistencies_section_present(self) -> None:
        findings = [
            InconsistencyFinding(
                path_a=Path("Process/Deployment.md"),
                path_b=Path("Platform/Deployment.md"),
                contradictions=[
                    {
                        "page_a_quote": "blue-green is the default",
                        "page_b_quote": "canary is the default",
                        "issue": "Conflicting default rollout strategy",
                    }
                ],
            )
        ]
        md = render_report(
            inconsistencies=findings,
            scope="docs",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "## Possible inconsistencies" in md
        assert "Conflicting default rollout" in md
        assert "blue-green" in md
        assert "canary" in md

    def test_no_inconsistencies_message(self) -> None:
        md = render_report(
            inconsistencies=[],
            scope="test",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "_No contradictions found._" in md

    def test_stale_section_present(self) -> None:
        findings = [
            StaleFinding(
                stale_path=Path("Tech/Old.md"),
                replacement_path=Path("Platform/New.md"),
                confidence="high",
                evidence="The new page covers all six steps with updated tooling.",
                last_updated="2021-06-15",
            )
        ]
        md = render_report(
            stale=findings,
            scope="docs",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "## Stale content" in md
        assert "Tech/Old.md" in md
        assert "Platform/New.md" in md
        assert "2021-06-15" in md
        assert "all six steps" in md

    def test_no_stale_message(self) -> None:
        md = render_report(
            stale=[],
            scope="test",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "_No superseded pages found._" in md

    def test_all_modes_present(self) -> None:
        md = render_report(
            duplicates=[],
            inconsistencies=[],
            stale=[],
            scope="all",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "## Likely duplicates" in md
        assert "## Possible inconsistencies" in md
        assert "## Stale content" in md

    def test_only_requested_sections_present(self) -> None:
        md = render_report(
            duplicates=[],
            scope="test",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "## Likely duplicates" in md
        assert "## Possible inconsistencies" not in md
        assert "## Stale content" not in md

    def test_run_summary_footer(self) -> None:
        summary = _make_summary(pairs_judged=10, api_calls=8, cached_calls=2, errors=0)
        md = render_report(
            duplicates=[],
            scope="test",
            run_date="2026-05-08",
            summary=summary,
        )
        assert "## Run summary" in md
        assert "pairs_judged" in md or "Pairs judged" in md
        assert "10" in md

    def test_header_contains_scope_and_date(self) -> None:
        md = render_report(
            duplicates=[],
            scope="MySpace",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "MySpace" in md
        assert "2026-05-08" in md

    def test_modes_in_summary_footer(self) -> None:
        md = render_report(
            duplicates=[],
            stale=[],
            scope="test",
            run_date="2026-05-08",
            summary=_make_summary(),
        )
        assert "duplicates" in md
        assert "stale" in md


# ---------------------------------------------------------------------------
# choose_report_path
# ---------------------------------------------------------------------------


class TestChooseReportPath:
    def test_returns_expected_path(self, tmp_path: Path) -> None:
        p = choose_report_path(tmp_path, "2026-05-08", "Engineering")
        assert p == tmp_path / "2026-05-08-Engineering.md"

    def test_no_collision_returns_base(self, tmp_path: Path) -> None:
        p = choose_report_path(tmp_path, "2026-05-08", "docs")
        assert p.name == "2026-05-08-docs.md"

    def test_collision_appends_suffix(self, tmp_path: Path) -> None:
        base = tmp_path / "2026-05-08-docs.md"
        base.write_text("existing")
        p = choose_report_path(tmp_path, "2026-05-08", "docs")
        assert p.name == "2026-05-08-docs-2.md"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        (tmp_path / "2026-05-08-docs.md").write_text("1")
        (tmp_path / "2026-05-08-docs-2.md").write_text("2")
        p = choose_report_path(tmp_path, "2026-05-08", "docs")
        assert p.name == "2026-05-08-docs-3.md"

    def test_scope_with_slash_sanitised(self, tmp_path: Path) -> None:
        p = choose_report_path(tmp_path, "2026-05-08", "mdd/docs")
        assert "/" not in p.name
        assert "mdd-docs" in p.name

    def test_suffix_param(self, tmp_path: Path) -> None:
        p = choose_report_path(tmp_path, "2026-05-08", "docs", suffix="-preview")
        assert p.name == "2026-05-08-docs-preview.md"
