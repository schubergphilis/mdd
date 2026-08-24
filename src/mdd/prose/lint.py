"""``mdd prose lint`` — mechanical slips, and the whitespace autofixes.

Every rule is expressed as a set of :class:`Edit` values over one line. A
finding and a fix are then the same object seen twice, which is what keeps
``--write`` from ever fixing something the check did not report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from mdd.prose.classify import LineClass
from mdd.prose.inline import mask_flags, span_at
from mdd.prose.report import Finding, make_excerpt
from mdd.prose.rules import LINT_FIXABLE, RULES, Severity

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified, Line
    from mdd.prose.config import LintConfig, ProseConfig

_MULTIPLE_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+(?=[,;:.!?])")
_TRAILING = re.compile(r"[ \t]+$")
_HARD_BREAK = "  "

_QUOTES = "\"'“”‘’"
_LITERAL_PREFIXES = ("-", "--", "/", "$", "<")

#: Characters that look like a plain space and are not one.
INVISIBLE_SPACES: dict[str, str] = {
    " ": "no-break space",
    " ": "figure space",
    " ": "thin space",
    " ": "hair space",
    "​": "zero-width space",
    " ": "narrow no-break space",
    "　": "ideographic space",
    "﻿": "zero-width no-break space",
}

_LINT_LINE_CLASSES = (LineClass.PROSE, LineClass.BLANK)


@dataclass(frozen=True)
class Edit:
    """A replacement of ``text[start:end]``, and the rule that asked for it."""

    rule: str
    start: int
    end: int
    replacement: str
    message: str


def _unmasked(line: Line) -> list[bool]:
    flags = mask_flags(len(line.text), line.masks)
    return [not flag for flag in flags]


def _multiple_spaces(line: Line) -> Iterable[Edit]:
    open_at = len(line.prefix)
    body_end = len(line.text.rstrip())
    free = _unmasked(line)
    for match in _MULTIPLE_SPACES.finditer(line.text):
        if match.start() < open_at or match.end() >= body_end:
            continue
        if not free[match.start()]:
            continue
        yield Edit(
            rule="multiple-spaces",
            start=match.start(),
            end=match.end(),
            replacement=" ",
            message=f"{match.end() - match.start()} spaces between words",
        )


def _is_sentence_punctuation(text: str, index: int) -> bool:
    """True when the mark at *index* really is punctuation rather than part of a token.

    ``.md``, ``:80`` and ``...`` all put one of these characters after a space
    without the space being a mistake, and deleting it corrupts the text. A
    false skip only loses a finding.
    """
    if text.startswith(("...", "…"), index):
        return False
    following = text[index + 1 : index + 2]
    return not following.isalnum()


def _space_before_punctuation(line: Line) -> Iterable[Edit]:
    open_at = len(line.prefix)
    free = _unmasked(line)
    for match in _SPACE_BEFORE_PUNCT.finditer(line.text):
        if match.start() <= open_at or match.end() >= len(line.text):
            continue
        if not free[match.start()] or not free[match.end()]:
            continue
        if not _is_sentence_punctuation(line.text, match.end()):
            continue
        yield Edit(
            rule="space-before-punctuation",
            start=match.start(),
            end=match.end(),
            replacement="",
            message=f"space before {line.text[match.end()]!r}",
        )


def _trailing_whitespace(line: Line, config: LintConfig) -> Iterable[Edit]:
    match = _TRAILING.search(line.text)
    if match is None:
        return
    run = match.group(0)
    if config.allow_hard_break and run == _HARD_BREAK:
        return
    yield Edit(
        rule="trailing-whitespace",
        start=match.start(),
        end=match.end(),
        replacement="",
        message=f"{len(run)} trailing whitespace characters",
    )


def _invisible_space(line: Line) -> Iterable[Edit]:
    free = _unmasked(line)
    for index, char in enumerate(line.text):
        name = INVISIBLE_SPACES.get(char)
        if name is None or not free[index]:
            continue
        yield Edit(
            rule="invisible-space",
            start=index,
            end=index + 1,
            replacement=char,
            message=f"{name} (U+{ord(char):04X}) where a plain space was probably meant",
        )


def _quoted_interior(text: str, quote_at: int, quote: str) -> str | None:
    """Return the interior of the quoted span closing at *quote_at*, or ``None``."""
    opener = text.rfind(quote, 0, quote_at)
    if quote in "”’":
        opener = text.rfind("“" if quote == "”" else "‘", 0, quote_at)
    if opener == -1:
        return None
    return text[opener + 1 : quote_at]


def _looks_literal(interior: str | None, config: LintConfig) -> bool:
    """True when a quoted span looks like a literal rather than like prose.

    Deliberately conservative: a false skip loses a finding, a false flag
    corrupts text.
    """
    if interior is None:
        return True
    if not interior or not interior.strip():
        return True
    if " " not in interior and "\t" not in interior:
        return True
    if interior.startswith(_LITERAL_PREFIXES):
        return True
    return any(pattern.search(interior) for pattern in config.literal_quote_patterns)


def _quote_candidates(line: Line, config: LintConfig) -> Iterable[tuple[int, int]]:
    """Yield ``(quote_index, mark_index)`` pairs the configured convention rejects."""
    if config.quote_punctuation == "off":
        return
    inside = config.quote_punctuation == "inside"
    for index in range(len(line.text) - 1):
        first, second = line.text[index], line.text[index + 1]
        if inside and first in _QUOTES and second in ",.":
            yield index, index + 1
        elif not inside and first in ",." and second in _QUOTES:
            yield index + 1, index


def _punctuation_outside_quote(line: Line, config: LintConfig) -> Iterable[Edit]:
    free = _unmasked(line)
    for quote_index, mark_index in _quote_candidates(line, config):
        if not free[quote_index] or not free[mark_index]:
            continue
        if span_at(line.masks, quote_index) is not None:
            continue
        interior = _quoted_interior(line.text, quote_index, line.text[quote_index])
        if _looks_literal(interior, config):
            continue
        target = "inside" if config.quote_punctuation == "inside" else "outside"
        yield Edit(
            rule="punctuation-outside-quote",
            start=min(quote_index, mark_index),
            end=max(quote_index, mark_index) + 1,
            replacement=line.text[min(quote_index, mark_index) : max(quote_index, mark_index) + 1],
            message=f"house style puts {line.text[mark_index]!r} {target} the closing quote",
        )


def _blank_run(lines: Sequence[Line]) -> Iterable[tuple[Line, Edit]]:
    run = 0
    for line in lines:
        if line.cls is not LineClass.BLANK:
            run = 0
            continue
        run += 1
        if run > 1:
            yield (
                line,
                Edit(
                    rule="blank-run",
                    start=0,
                    end=len(line.text),
                    replacement="",
                    message="more than one consecutive blank line",
                ),
            )


def _line_edits(line: Line, config: LintConfig) -> list[Edit]:
    if line.cls is LineClass.BLANK:
        return list(_trailing_whitespace(line, config))
    if line.cls is not LineClass.PROSE:
        return []
    return [
        *_multiple_spaces(line),
        *_space_before_punctuation(line),
        *_trailing_whitespace(line, config),
        *_invisible_space(line),
        *_punctuation_outside_quote(line, config),
    ]


def _finding(path: Path, line: Line, edit: Edit, config: ProseConfig) -> Finding:
    rule = RULES[edit.rule]
    return Finding(
        path=path,
        line=line.number,
        column=edit.start + 1,
        check="lint",
        rule=edit.rule,
        message=edit.message,
        severity=config.severity(edit.rule),
        excerpt=make_excerpt(line.text, edit.start + 1),
        fixable=rule.fixable,
    )


def apply_edits(text: str, edits: Sequence[Edit]) -> str:
    """Apply *edits* to *text*, rightmost first so earlier offsets stay valid."""
    out = text
    for edit in sorted(edits, key=lambda e: e.start, reverse=True):
        out = out[: edit.start] + edit.replacement + out[edit.end :]
    return out


@dataclass(frozen=True)
class LintResult:
    """What one lint pass found, and the fixed file if there is anything to write."""

    findings: tuple[Finding, ...]
    fixed: Classified | None


def _fixable_edits(edits: Sequence[Edit], config: ProseConfig) -> list[Edit]:
    return [
        edit
        for edit in edits
        if edit.rule in LINT_FIXABLE and config.severity(edit.rule) is not Severity.OFF
    ]


def _drop_blank_lines(lines: list[Line], drop: set[int]) -> list[Line]:
    return [line for line in lines if line.number not in drop]


def run(path: Path, classified: Classified, config: ProseConfig) -> LintResult:
    """Lint *classified*, returning findings and — for ``--write`` — the fixed file."""
    findings: list[Finding] = []
    lines = list(classified.lines)
    dropped: set[int] = set()
    changed = False

    if config.severity("blank-run") is not Severity.OFF:
        for blank_line, edit in _blank_run(classified.lines):
            findings.append(_finding(path, blank_line, edit, config))
            dropped.add(blank_line.number)
            changed = True

    for index, line in enumerate(lines):
        edits = [
            e for e in _line_edits(line, config.lint) if config.severity(e.rule) is not Severity.OFF
        ]
        findings.extend(_finding(path, line, edit, config) for edit in edits)
        fixes = _fixable_edits(edits, config)
        if not fixes:
            continue
        new_text = apply_edits(line.text, fixes)
        if new_text != line.text:
            lines[index] = replace(line, text=new_text)
            changed = True

    fixed = replace(classified, lines=tuple(_drop_blank_lines(lines, dropped))) if changed else None
    return LintResult(findings=tuple(findings), fixed=fixed)
