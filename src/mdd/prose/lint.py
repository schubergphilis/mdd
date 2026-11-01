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
from mdd.prose.quotes import looks_literal, quote_candidates, quoted_interior
from mdd.prose.report import Finding, make_excerpt
from mdd.prose.rules import LINT_FIXABLE, RULES, Severity

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified, Line
    from mdd.prose.config import LintConfig, ProseConfig

_MULTIPLE_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+(?=[,;:.!?])")
_TRAILING = re.compile(r"[ \t]+$")
_HARD_BREAK = "  "

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


@dataclass(frozen=True)
class Edit:
    """A replacement of ``text[start:end]``, and the rule that asked for it."""

    rule: str
    start: int
    end: int
    replacement: str
    message: str
    #: False when the rule is fixable in general but this occurrence is not:
    #: the edit is reported and never applied.
    fixable: bool = True


def _unmasked(line: Line) -> list[bool]:
    flags = mask_flags(len(line.text), line.masks)
    return [not flag for flag in flags]


def _describe_run(run: str) -> str:
    """Name a run of spaces and tabs the way a reader would count it."""
    if "\t" not in run:
        return f"{len(run)} spaces"
    if " " not in run:
        return f"{len(run)} tabs"
    return f"a run of {len(run)} spaces and tabs"


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
            message=f"{_describe_run(match.group(0))} between words",
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
    # Whitelist, not blacklist. Real sentence punctuation is followed by
    # whitespace, end of line, or a closing bracket/quote. Rejecting only
    # alphanumerics still ate the space in `directory ./configs` and `up .. one`.
    return following == "" or following in " \t)]}>\"'”’»"


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


def _unfixable_reason(line: Line, start: int, run: str, *, breaks: bool, keep_break: bool) -> str:
    """Why the trailing run at *start* must be reported but not fixed, or ``""``.

    Both cases sit before a line the paragraph continues on. A backslash left
    at the end of the line becomes a hard line break, and a tab there is kept
    by mdd's model, so deleting it changes the document even though the
    rendered text looks the same.
    """
    if not breaks:
        return ""
    if "\t" in run:
        return "; not fixed: a tab before a continuation line is kept by mdd's model"
    if not keep_break and line.text[:start].endswith("\\"):
        return "; not fixed: deleting it would make the backslash a hard line break"
    return ""


def _trailing_whitespace(
    line: Line, config: LintConfig, *, breaks: bool, continued_construct: bool
) -> Iterable[Edit]:
    """Flag trailing whitespace; *breaks* says the paragraph continues on the next line.

    Two or more trailing spaces before a continuation line are a hard line
    break, and deleting them joins the two lines. So a longer run there is
    trimmed to exactly two spaces, the one hard break the rule allows. When
    hard breaks are not allowed at all the break is reported but not fixed:
    removing it changes the document, which is the author's call.
    """
    match = _TRAILING.search(line.text)
    if match is None:
        return
    run = match.group(0)
    hard_break = breaks and run.endswith(_HARD_BREAK)
    if config.allow_hard_break and run == _HARD_BREAK:
        return
    # Masks are computed over the block's *rstripped* content, so a span that
    # reaches the end of the visible content may be a construct that carries
    # on across the soft break, with this run inside it. That is only possible
    # when the next line opens with a span too; then skip. Losing a finding is
    # the acceptable direction; rewriting a code span is not.
    if continued_construct and any(span.end >= match.start() for span in line.masks):
        return
    if hard_break and not config.allow_hard_break:
        yield Edit(
            rule="trailing-whitespace",
            start=match.start(),
            end=match.end(),
            replacement=run,
            message=f"{len(run)} trailing spaces make a hard line break, and hard breaks are off",
            fixable=False,
        )
        return
    reason = _unfixable_reason(line, match.start(), run, breaks=breaks, keep_break=hard_break)
    yield Edit(
        rule="trailing-whitespace",
        start=match.start(),
        end=match.end(),
        replacement=_HARD_BREAK if hard_break else "",
        message=f"{len(run)} trailing whitespace characters"
        + ("; a hard line break needs exactly two spaces" if hard_break else "")
        + reason,
        fixable=not reason,
    )


def _backslash_break(line: Line, config: LintConfig, *, breaks: bool) -> Iterable[Edit]:
    """Flag a trailing backslash that makes a hard line break, when hard breaks are off.

    Only a line the paragraph continues after ends in a break: at the end of a
    paragraph the backslash is literal, and an even run of them is escaped
    backslashes. Removing the break joins two lines, so like the two-space form
    it is reported under ``trailing-whitespace`` and never fixed.
    """
    if config.allow_hard_break or not breaks:
        return
    run = len(line.text) - len(line.text.rstrip("\\"))
    if run % 2 == 0:
        return
    at = len(line.text) - 1
    # Unlike trailing whitespace, the backslash is content, so the masks say
    # whether it sits in a code span or another literal construct.
    if not _unmasked(line)[at]:
        return
    yield Edit(
        rule="trailing-whitespace",
        start=at,
        end=at + 1,
        replacement="\\",
        message="a trailing backslash makes a hard line break, and hard breaks are off",
        fixable=False,
    )


_BYTE_ORDER_MARK = "\ufeff"


def _is_byte_order_mark(line: Line, index: int) -> bool:
    """True for a U+FEFF that opens the file, where it is a byte order mark."""
    return line.number == 1 and index == 0 and line.text.startswith(_BYTE_ORDER_MARK)


def _invisible_space(line: Line) -> Iterable[Edit]:
    free = _unmasked(line)
    for index, char in enumerate(line.text):
        name = INVISIBLE_SPACES.get(char)
        if name is None or not free[index] or _is_byte_order_mark(line, index):
            continue
        yield Edit(
            rule="invisible-space",
            start=index,
            end=index + 1,
            replacement=char,
            message=f"{name} (U+{ord(char):04X}) where a plain space was probably meant",
        )


def _punctuation_outside_quote(line: Line, config: LintConfig) -> Iterable[Edit]:
    free = _unmasked(line)
    for quote_index, mark_index in quote_candidates(line, config):
        if not free[quote_index] or not free[mark_index]:
            continue
        if span_at(line.masks, quote_index) is not None:
            continue
        interior = quoted_interior(line.text, quote_index, line.text[quote_index])
        if looks_literal(interior, config):
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


def _line_edits(
    line: Line, config: LintConfig, *, breaks: bool, continued_construct: bool
) -> list[Edit]:
    if line.cls is LineClass.BLANK:
        return list(_trailing_whitespace(line, config, breaks=False, continued_construct=False))
    if line.cls is not LineClass.PROSE:
        return []
    return [
        *_multiple_spaces(line),
        *_space_before_punctuation(line),
        *_trailing_whitespace(line, config, breaks=breaks, continued_construct=continued_construct),
        *_backslash_break(line, config, breaks=breaks),
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
        fixable=rule.fixable and edit.fixable,
    )


#: Which rule wins when two fixable edits cover the same span. Trailing
#: whitespace deletes the whole run; collapsing it first would leave a single
#: trailing space behind, still a finding on a rerun.
_EDIT_PRECEDENCE: tuple[str, ...] = (
    "trailing-whitespace",
    "multiple-spaces",
)


def _edit_priority(edit: Edit) -> tuple[int, int, int]:
    rank = (
        _EDIT_PRECEDENCE.index(edit.rule)
        if edit.rule in _EDIT_PRECEDENCE
        else len(_EDIT_PRECEDENCE)
    )
    return (rank, edit.start, -edit.end)


def apply_edits(text: str, edits: Sequence[Edit]) -> str:
    """Apply *edits* to *text*, rightmost first so earlier offsets stay valid.

    Overlapping edits are dropped rather than applied. Two rules can match the
    same whitespace run, and applying both leaves the second one's end offset
    stale, so it deletes a character outside the run it matched.
    """
    out = text
    applied: list[Edit] = []
    for edit in sorted(edits, key=_edit_priority):
        if any(edit.start < done.end and done.start < edit.end for done in applied):
            continue
        applied.append(edit)
    for edit in sorted(applied, key=lambda e: e.start, reverse=True):
        out = out[: edit.start] + edit.replacement + out[edit.end :]
    return out


#: Answers "is this rule suppressed at this line?". Injected so the fixer and
#: the reporter consult one source of truth.
type RuleFilter = Callable[[int, str], bool]


def _never_suppressed(_line: int, _rule: str) -> bool:
    return False


@dataclass(frozen=True)
class LintResult:
    """What one lint pass found, and the fixed file if there is anything to write."""

    findings: tuple[Finding, ...]
    fixed: Classified | None


def _fixable_edits(
    edits: Sequence[Edit], config: ProseConfig, line: int, suppressed: RuleFilter
) -> list[Edit]:
    """The subset of *edits* `--write` may apply.

    A suppressed rule is excluded here, not merely dropped from the report. An
    author who writes `<!-- mdd-prose-ignore: trailing-whitespace -->` has opted
    out of the change, not just out of being told about it.
    """
    return [
        edit
        for edit in edits
        if edit.rule in LINT_FIXABLE
        and edit.fixable
        and config.severity(edit.rule) is not Severity.OFF
        and not suppressed(line, edit.rule)
    ]


def _drop_blank_lines(lines: list[Line], drop: set[int]) -> list[Line]:
    return [line for line in lines if line.number not in drop]


def _continues(line: Line, following: Line | None) -> bool:
    """True when *following* carries on the paragraph *line* is in."""
    return (
        following is not None
        and line.cls is LineClass.PROSE
        and following.cls is LineClass.PROSE
        and following.block == line.block
    )


def _opens_on_a_span(line: Line) -> bool:
    """True when *line*'s content starts inside a masked span.

    A span clipped from one that began on the line before starts exactly at the
    content's first column, so this is the only way such a span can show.
    """
    return any(span.start <= len(line.prefix) for span in line.masks)


def _lint_one_line(
    path: Path,
    line: Line,
    config: ProseConfig,
    suppressed: RuleFilter,
    findings: list[Finding],
    *,
    following: Line | None,
) -> Line | None:
    """Append *line*'s findings and return its fixed form, or ``None`` if unchanged."""
    breaks = _continues(line, following)
    continued_construct = breaks and following is not None and _opens_on_a_span(following)
    edits = [
        e
        for e in _line_edits(
            line, config.lint, breaks=breaks, continued_construct=continued_construct
        )
        if config.severity(e.rule) is not Severity.OFF
    ]
    findings.extend(_finding(path, line, edit, config) for edit in edits)
    fixes = _fixable_edits(edits, config, line.number, suppressed)
    if not fixes:
        return None
    new_text = apply_edits(line.text, fixes)
    return replace(line, text=new_text) if new_text != line.text else None


def run(
    path: Path,
    classified: Classified,
    config: ProseConfig,
    suppressed: RuleFilter = _never_suppressed,
) -> LintResult:
    """Lint *classified*, returning findings and — for ``--write`` — the fixed file."""
    findings: list[Finding] = []
    lines = list(classified.lines)
    dropped: set[int] = set()
    changed = False

    if config.severity("blank-run") is not Severity.OFF:
        for blank_line, edit in _blank_run(classified.lines):
            findings.append(_finding(path, blank_line, edit, config))
            if not suppressed(blank_line.number, edit.rule):
                dropped.add(blank_line.number)
                changed = True

    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else None
        fixed = _lint_one_line(path, line, config, suppressed, findings, following=following)
        if fixed is not None:
            lines[index] = fixed
            changed = True

    fixed = replace(classified, lines=tuple(_drop_blank_lines(lines, dropped))) if changed else None
    return LintResult(findings=tuple(findings), fixed=fixed)
