"""Markdown report renderer for mdd ai review findings.

Usage::

    from mdd.ai.reports import render_report

    md = render_report(
        duplicates=[...],
        inconsistencies=[...],
        stale=[...],
        scope="SPACE",
        run_date="2026-05-08",
        summary=summary,
    )
    Path("docs/review/2026-05-08-SPACE.md").write_text(md)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.ai.judges import (
        DuplicateFinding,
        InconsistencyFinding,
        ReviewSummary,
        StaleFinding,
    )


def _render_duplicates(findings: list[DuplicateFinding]) -> str:
    """Render the duplicates section."""
    lines: list[str] = ["## Likely duplicates", ""]
    if not findings:
        lines.append("_No high-overlap pairs found._")
        lines.append("")
        return "\n".join(lines)

    for f in findings:
        lines.append(f"### `{f.path_a}` ↔ `{f.path_b}`")
        lines.append("")
        lines.append(f"**Overlap:** {f.overlap}")
        lines.append("")
        if f.summary:
            lines.append(f"**Summary:** {f.summary}")
            lines.append("")
        if f.shared_sections:
            sections = ", ".join(f.shared_sections)
            lines.append(f"**Shared sections:** {sections}")
            lines.append("")
        if f.suggested_action:
            lines.append(f"**Suggested action:** {f.suggested_action}")
            lines.append("")

    return "\n".join(lines)


def _render_inconsistencies(findings: list[InconsistencyFinding]) -> str:
    """Render the inconsistencies section."""
    lines: list[str] = ["## Possible inconsistencies", ""]
    if not findings:
        lines.append("_No contradictions found._")
        lines.append("")
        return "\n".join(lines)

    for f in findings:
        lines.append(f"### `{f.path_a}` and `{f.path_b}`")
        lines.append("")
        for c in f.contradictions:
            issue = c.get("issue", "")
            quote_a = c.get("page_a_quote", "")
            quote_b = c.get("page_b_quote", "")
            lines.append(f"- **Issue:** {issue}")
            if quote_a:
                lines.append(f'  - `{f.path_a}`: "{quote_a}"')
            if quote_b:
                lines.append(f'  - `{f.path_b}`: "{quote_b}"')
        lines.append("")

    return "\n".join(lines)


def _render_stale(findings: list[StaleFinding]) -> str:
    """Render the stale content section."""
    lines: list[str] = ["## Stale content", ""]
    if not findings:
        lines.append("_No superseded pages found._")
        lines.append("")
        return "\n".join(lines)

    for f in findings:
        lines.append(f"### `{f.stale_path}`")
        lines.append("")
        if f.last_updated:
            lines.append(f"- Last updated {f.last_updated}")
        lines.append(f"- **Likely superseded by:** `{f.replacement_path}`")
        if f.evidence:
            lines.append(f"- **Evidence:** {f.evidence}")
        lines.append(
            "- **Suggested action:** archive or delete the stale page; "
            "add a redirect note pointing at the newer page."
        )
        lines.append("")

    return "\n".join(lines)


def _render_summary(summary: ReviewSummary, modes: list[str]) -> str:
    """Render a small run-summary footer."""
    lines: list[str] = [
        "---",
        "",
        "## Run summary",
        "",
        f"- **Modes:** {', '.join(modes)}",
        f"- **Pairs judged:** {summary.pairs_judged}",
        f"- **API calls:** {summary.api_calls}  |  **Cached:** {summary.cached_calls}",
        f"- **Errors:** {summary.errors}",
        "",
    ]
    return "\n".join(lines)


def render_report(
    *,
    duplicates: list[DuplicateFinding] | None = None,
    inconsistencies: list[InconsistencyFinding] | None = None,
    stale: list[StaleFinding] | None = None,
    scope: str,
    run_date: str,
    summary: ReviewSummary,
) -> str:
    """Render the full markdown review report.

    Sections are only included for the modes that were actually run
    (non-None). At least one mode must be provided.
    """
    modes: list[str] = []
    sections: list[str] = []

    header = f"# AI Review Report\n\n**Scope:** {scope}  \n**Date:** {run_date}\n"

    if duplicates is not None:
        modes.append("duplicates")
        sections.append(_render_duplicates(duplicates))

    if inconsistencies is not None:
        modes.append("inconsistencies")
        sections.append(_render_inconsistencies(inconsistencies))

    if stale is not None:
        modes.append("stale")
        sections.append(_render_stale(stale))

    body = "\n".join(sections)
    footer = _render_summary(summary, modes)

    return f"{header}\n{body}\n{footer}"


def choose_report_path(
    output_dir: Path,
    run_date: str,
    scope: str,
    *,
    suffix: str = "",
) -> Path:
    """Choose a non-colliding report path under *output_dir*.

    Format: ``<output_dir>/<run_date>-<scope><suffix>.md``

    If the path already exists, appends ``-2``, ``-3``, etc. until free.
    """
    safe_scope = scope.replace("/", "-").replace(" ", "-")
    base_name = f"{run_date}-{safe_scope}{suffix}"
    candidate = output_dir / f"{base_name}.md"
    if not candidate.exists():
        return candidate

    # Bounded: 9 same-day same-scope report attempts is already pathological.
    for n in range(2, 11):
        candidate = output_dir / f"{base_name}-{n}.md"
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"choose_report_path({base_name}): more than 9 collisions on the same "
        f"day — refusing to keep escalating filenames"
    )
