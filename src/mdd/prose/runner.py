"""Parse once, classify once, check many.

Every subcommand is a consumer of one shared per-file artefact: the text, plus
the line and span classification. ``mdd prose check`` therefore costs barely
more than the most expensive single check, and the checks cannot disagree about
what prose is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from mdd.prose import anchors as anchors_check
from mdd.prose import freshness as freshness_check
from mdd.prose import gate, suppress
from mdd.prose import lint as lint_check
from mdd.prose.classify import ClassifyError, classify, join_lines
from mdd.prose.reflow import apply as reflow_apply
from mdd.prose.report import Finding
from mdd.prose.rules import CROSS_CUTTING, Severity
from mdd.prose.write import (
    atomic_write,
    mirror_finding,
    mirror_reason,
    refusal_finding,
    write_failure,
)
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified
    from mdd.prose.config import ProseConfig

log = get_logger(__name__)

#: The checks that can rewrite a file.
WRITERS: tuple[str, ...] = ("reflow", "lint")


@dataclass(frozen=True)
class RunOptions:
    """What one invocation asked for."""

    checks: tuple[str, ...]
    write: bool = False
    allow_mirror: bool = False
    as_of: dt.date = field(default_factory=dt.date.today)
    freshness_only: str | None = None

    def __post_init__(self) -> None:
        # Each writer computes its fix from, and gates it against, the file as
        # it was read. A second writer in the same pass would compute from
        # stale text and overwrite the first one's output.
        writers = [name for name in WRITERS if name in self.checks]
        if self.write and len(writers) > 1:
            msg = f"--write runs one writer at a time, got {', '.join(writers)}"
            raise ValueError(msg)


@dataclass(frozen=True)
class _Unit:
    """One file, read and classified once."""

    path: Path
    text: str
    classified: Classified


@dataclass
class RunResult:
    """Every finding, the files looked at and written, and whether the run itself failed."""

    findings: list[Finding] = field(default_factory=list)
    file_count: int = 0
    written_paths: list[Path] = field(default_factory=list)
    failed: bool = False

    @property
    def written(self) -> int:
        """How many files a ``--write`` run rewrote."""
        return len(self.written_paths)


def _read(path: Path, result: RunResult) -> str | ClassifyError | None:
    """Return the file's text, why it cannot be read as text, or ``None`` if it cannot be read.

    The bytes are decoded without newline translation. With translation every
    CRLF file arrives as LF, and a writer then re-emits the whole file with the
    wrong line endings while reporting that it changed nothing.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        log.error("cannot read %s: %s", path, exc)
        result.failed = True
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1
        return ClassifyError(line, f"not valid UTF-8 at byte {exc.start}")


def _parse_error(path: Path, error: ClassifyError, config: ProseConfig) -> list[Finding]:
    severity = config.severity("parse-error")
    if severity is Severity.OFF:
        return []
    return [
        Finding(
            path=path,
            line=error.line,
            column=0,
            check=CROSS_CUTTING,
            rule="parse-error",
            message=f"{error.reason}; every check skipped this file",
            severity=severity,
        )
    ]


def _refuse_mirror(
    path: Path, text: str, check: str, config: ProseConfig, options: RunOptions
) -> Finding | None:
    if options.allow_mirror:
        return None
    reason = mirror_reason(text)
    return None if reason is None else mirror_finding(path, check, reason, config)


def _write(
    path: Path, text: str, check: str, config: ProseConfig, result: RunResult
) -> Finding | None:
    """Write *text*, or report the failure. One bad file must not end the run."""
    try:
        atomic_write(path, text)
    except OSError as exc:
        log.error("cannot write %s: %s", path, exc)
        result.failed = True
        return write_failure(path, check, str(exc), config)
    result.written_paths.append(path)
    return None


def _unfixable(findings: Sequence[Finding]) -> list[Finding]:
    return [replace(f, fixable=False) if f.fixable else f for f in findings]


@dataclass(frozen=True)
class _Fix:
    """One writer's proposal for one file: the rewritten text and what it reports."""

    check: str
    text: str
    findings: tuple[Finding, ...]


def _gated_fix(
    unit: _Unit, fix: _Fix, config: ProseConfig, options: RunOptions, result: RunResult
) -> list[Finding]:
    """Gate a writer's fix, then write it if ``--write`` asked for that.

    The gate runs with and without ``--write``, so the check-only report and
    the write agree on what is fixable: a fix the gate refuses is reported as
    not fixable, with the refusal, in both modes.
    """
    verdict = gate.verify(unit.text, fix.text)
    if not verdict.passed:
        return [*_unfixable(fix.findings), refusal_finding(unit.path, fix.check, verdict, config)]
    if not options.write or fix.text == unit.text:
        return list(fix.findings)
    refusal = _refuse_mirror(unit.path, unit.text, fix.check, config, options)
    if refusal is not None:
        return [*fix.findings, refusal]
    failure = _write(unit.path, fix.text, fix.check, config, result)
    if failure is not None:
        return [*fix.findings, failure]
    return [f for f in fix.findings if not f.fixable]


def _held_lines(classified: Classified, suppressions: suppress.Suppressions) -> frozenset[int]:
    """Return every line of every paragraph a ``reflow`` suppression covers.

    Reflow rewrites a whole paragraph or none of it, so a paragraph is held
    back when any of its lines is covered: the fix never edits a line whose
    finding the author silenced.
    """
    held_blocks = {
        line.block
        for line in classified.lines
        if line.block >= 0 and suppressions.covers(line.number, "reflow")
    }
    return frozenset(line.number for line in classified.lines if line.block in held_blocks)


def _without(classified: Classified, held: frozenset[int]) -> Classified:
    """Return *classified* with the *held* lines out of reflow's reach."""
    lines = tuple(
        replace(line, block=-1) if line.number in held else line for line in classified.lines
    )
    return replace(classified, lines=lines)


def _run_reflow(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
    suppressions: suppress.Suppressions,
) -> list[Finding]:
    rewrite = reflow_apply.reflow_text(unit.classified, config.reflow)
    if not rewrite.changed:
        return []
    findings = reflow_apply.findings(unit.path, unit.classified, config, rewrite)
    if config.severity("reflow") is Severity.OFF:
        return findings
    held = _held_lines(unit.classified, suppressions)
    if held:
        rewrite = reflow_apply.reflow_text(_without(unit.classified, held), config.reflow)
        findings = [replace(f, fixable=False) if f.line in held else f for f in findings]
    fix = _Fix(check="reflow", text=rewrite.text, findings=tuple(findings))
    return _gated_fix(unit, fix, config, options, result)


def _run_lint(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
    suppressions: suppress.Suppressions,
) -> list[Finding]:
    outcome = lint_check.run(unit.path, unit.classified, config, suppressions.suppresses)
    if outcome.fixed is None:
        return list(outcome.findings)
    fixed_text = join_lines(
        [line.text for line in outcome.fixed.lines],
        outcome.fixed.newline,
        final_newline=outcome.fixed.final_newline,
    )
    fix = _Fix(check="lint", text=fixed_text, findings=outcome.findings)
    return _gated_fix(unit, fix, config, options, result)


def _check_file(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
    index: anchors_check.AnchorIndex,
    suppressions: suppress.Suppressions,
) -> list[Finding]:
    findings: list[Finding] = []
    if "reflow" in options.checks:
        findings.extend(_run_reflow(unit, config, options, result, suppressions))
    if "lint" in options.checks:
        findings.extend(_run_lint(unit, config, options, result, suppressions))
    if "anchors" in options.checks:
        findings.extend(anchors_check.run(unit.path, unit.classified, config, index))
    if "freshness" in options.checks:
        findings.extend(
            freshness_check.run(
                unit.path, unit.text, config, as_of=options.as_of, only=options.freshness_only
            )
        )
    return findings


def _filter(findings: Sequence[Finding], suppressions: suppress.Suppressions) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity is not Severity.OFF
        and not suppressions.suppresses(finding.line, finding.rule)
    ]


def run(
    paths: Sequence[Path],
    config: ProseConfig,
    options: RunOptions,
) -> RunResult:
    """Run every requested check over every file in *paths*."""
    result = RunResult()
    index = anchors_check.AnchorIndex()
    for path in paths:
        text = _read(path, result)
        if text is None:
            continue
        result.file_count += 1
        if isinstance(text, ClassifyError):
            result.findings.extend(_parse_error(path, text, config))
            continue
        classified = classify(text)
        if isinstance(classified, ClassifyError):
            result.findings.extend(_parse_error(path, classified, config))
            continue
        suppressions = suppress.collect(classified.lines)
        unit = _Unit(path=path, text=text, classified=classified)
        findings = _check_file(unit, config, options, result, index, suppressions)
        result.findings.extend(_filter(findings, suppressions))
        result.findings.extend(suppress.audit(path, suppressions, config))
    return result
