"""Parse once, classify once, check many.

Every subcommand is a consumer of one shared per-file artefact: the text, plus
the line and span classification. ``mdd prose check`` therefore costs barely
more than the most expensive single check, and the checks cannot disagree about
what prose is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mdd.prose import anchors as anchors_check
from mdd.prose import freshness as freshness_check
from mdd.prose import lint as lint_check
from mdd.prose import suppress
from mdd.prose.classify import ClassifyError, classify, join_lines
from mdd.prose.reflow import apply as reflow_apply
from mdd.prose.report import Finding
from mdd.prose.rules import CROSS_CUTTING, Severity
from mdd.prose.write import atomic_write, mirror_finding, mirror_reason
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified
    from mdd.prose.config import ProseConfig

log = get_logger(__name__)


@dataclass(frozen=True)
class RunOptions:
    """What one invocation asked for."""

    checks: tuple[str, ...]
    write: bool = False
    allow_mirror: bool = False
    as_of: dt.date = field(default_factory=dt.date.today)
    freshness_only: str | None = None


@dataclass(frozen=True)
class _Unit:
    """One file, read and classified once."""

    path: Path
    text: str
    classified: Classified


@dataclass
class RunResult:
    """Every finding, how many files were looked at, and whether the run itself failed."""

    findings: list[Finding] = field(default_factory=list)
    file_count: int = 0
    written: int = 0
    failed: bool = False


def _read(path: Path, result: RunResult) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.error("cannot read %s: %s", path, exc)
        result.failed = True
        return None


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


def _run_reflow(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
) -> list[Finding]:
    path, text, classified = unit.path, unit.text, unit.classified
    rewrite = reflow_apply.reflow_text(classified, config.reflow)
    if not rewrite.changed:
        return []
    findings = reflow_apply.findings(path, classified, config, rewrite)
    if not options.write or config.severity("reflow") is Severity.OFF:
        return findings
    refusal = _refuse_mirror(path, text, "reflow", config, options)
    if refusal is not None:
        return [*findings, refusal]
    if not reflow_apply.equivalent(text, rewrite.text):
        return [
            *findings,
            Finding(
                path=path,
                line=0,
                column=0,
                check="reflow",
                rule="not-equivalent",
                message="reflow changed the rendered document; the file was left unchanged",
                severity=config.severity("not-equivalent"),
            ),
        ]
    atomic_write(path, rewrite.text)
    result.written += 1
    return [f for f in findings if not f.fixable]


def _run_lint(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
) -> list[Finding]:
    path, text, classified = unit.path, unit.text, unit.classified
    outcome = lint_check.run(path, classified, config)
    findings = list(outcome.findings)
    if not options.write or outcome.fixed is None:
        return findings
    refusal = _refuse_mirror(path, text, "lint", config, options)
    if refusal is not None:
        return [*findings, refusal]
    fixed_text = join_lines(
        [line.text for line in outcome.fixed.lines],
        outcome.fixed.newline,
        final_newline=outcome.fixed.final_newline,
    )
    atomic_write(path, fixed_text)
    result.written += 1
    return [f for f in findings if not f.fixable]


def _check_file(
    unit: _Unit,
    config: ProseConfig,
    options: RunOptions,
    result: RunResult,
    index: anchors_check.AnchorIndex,
) -> list[Finding]:
    findings: list[Finding] = []
    if "reflow" in options.checks:
        findings.extend(_run_reflow(unit, config, options, result))
    if "lint" in options.checks:
        findings.extend(_run_lint(unit, config, options, result))
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
        classified = classify(text)
        if isinstance(classified, ClassifyError):
            result.findings.extend(_parse_error(path, classified, config))
            continue
        suppressions = suppress.collect(classified.lines)
        unit = _Unit(path=path, text=text, classified=classified)
        findings = _check_file(unit, config, options, result, index)
        result.findings.extend(_filter(findings, suppressions))
        result.findings.extend(suppress.audit(path, suppressions, config))
    return result
