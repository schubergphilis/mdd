"""The finding record and its two emitters.

One frozen dataclass is produced by every check and consumed by one emitter,
so the human and JSON formats cannot drift apart. Findings go to stdout;
progress, warnings and the run summary go to stderr via the logger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.prose.rules import Severity

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path
    from typing import TextIO

_EXCERPT_CONTEXT = 24
_EXCERPT_MAX = 96


@dataclass(frozen=True)
class Finding:
    """One reported problem, at a location, under a stable rule id."""

    path: Path
    line: int
    column: int
    check: str
    rule: str
    message: str
    severity: Severity
    excerpt: str | None = None
    fixable: bool = False


def make_excerpt(text: str, column: int) -> str:
    """Return a trimmed excerpt of *text* around the 1-based *column*.

    Excerpts quote source content into a CI log, which is a weaker boundary
    than the repository, so the window is deliberately small.
    """
    if column <= 0:
        trimmed = text.strip()
        return trimmed[:_EXCERPT_MAX] + ("…" if len(trimmed) > _EXCERPT_MAX else "")
    index = column - 1
    start = max(0, index - _EXCERPT_CONTEXT)
    end = min(len(text), index + _EXCERPT_CONTEXT)
    body = text[start:end]
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def format_human(finding: Finding, *, show_excerpt: bool) -> str:
    """Render *finding* in the ``path:line:column: severity: rule: message`` shape."""
    head = (
        f"{finding.path}:{finding.line}:{finding.column}: "
        f"{finding.severity.value}: {finding.rule}: {finding.message}"
    )
    if show_excerpt and finding.excerpt:
        return f"{head}\n    {finding.excerpt}"
    return head


def format_json(finding: Finding, *, show_excerpt: bool) -> str:
    """Render *finding* as one line of line-delimited JSON."""
    payload: dict[str, object] = {
        "path": str(finding.path),
        "line": finding.line,
        "column": finding.column,
        "severity": finding.severity.value,
        "check": finding.check,
        "rule": finding.rule,
        "message": finding.message,
        "fixable": finding.fixable,
    }
    if show_excerpt:
        payload["excerpt"] = finding.excerpt
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def emit(
    findings: Iterable[Finding],
    stream: TextIO,
    *,
    json_mode: bool,
    show_excerpt: bool,
) -> None:
    """Write every finding to *stream*, one record per line."""
    render = format_json if json_mode else format_human
    for finding in findings:
        print(render(finding, show_excerpt=show_excerpt), file=stream)  # program output


def sort_key(finding: Finding) -> tuple[str, int, int, str]:
    """Stable ordering: by path, then line, then column, then rule id."""
    return (str(finding.path), finding.line, finding.column, finding.rule)


def summarise(command: str, findings: Sequence[Finding], file_count: int) -> str:
    """Return the one-line run summary written to stderr."""
    errors = sum(1 for f in findings if f.severity is Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity is Severity.WARNING)
    if not errors and not warnings:
        return f"{command}: clean ({file_count} files)"
    fixable = sum(1 for f in findings if f.fixable)
    suffix = f" ({fixable} fixable with --write)" if fixable else ""
    plural_e = "error" if errors == 1 else "errors"
    plural_w = "warning" if warnings == 1 else "warnings"
    return f"{command}: {errors} {plural_e}, {warnings} {plural_w} in {file_count} files{suffix}"
