"""Suppression comments.

An HTML comment is used because it is invisible in every Markdown renderer and
survives round-tripping through the IR::

    <!-- mdd-prose-ignore: punctuation-outside-quote -->
    <!-- mdd-prose-ignore -->
    <!-- mdd-prose-ignore-file: reflow -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mdd.prose.report import Finding
from mdd.prose.rules import CROSS_CUTTING, RULES, Severity

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from mdd.prose.classify import Line
    from mdd.prose.config import ProseConfig

#: Stands for "every rule" in a bare suppression comment.
ALL = "*"

_DIRECTIVE = re.compile(
    r"<!--\s*mdd-prose-ignore(?P<file>-file)?\s*(?::\s*(?P<rules>[^>]*?))?\s*-->"
)


@dataclass(frozen=True)
class Site:
    """One suppression directive, where it was written and what it names."""

    line: int
    rule: str
    file_wide: bool


@dataclass
class Suppressions:
    """Every suppression in one file, plus which of them did any work."""

    next_line: dict[int, set[str]] = field(default_factory=dict)
    file_wide: set[str] = field(default_factory=set)
    sites: tuple[Site, ...] = ()
    used: set[Site] = field(default_factory=set)

    def _match(self, line: int, rule: str) -> Site | None:
        for site in self.sites:
            if site.rule not in (rule, ALL):
                continue
            if site.file_wide or site.line + 1 == line:
                return site
        return None

    def suppresses(self, line: int, rule: str) -> bool:
        """True when *rule* at *line* is suppressed; records the directive as used."""
        site = self._match(line, rule)
        if site is None:
            return False
        self.used.add(site)
        return True

    def unused(self) -> tuple[Site, ...]:
        """Return the directives that suppressed nothing."""
        return tuple(site for site in self.sites if site not in self.used)


def _rules_of(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return [ALL]
    return [part.strip() for part in raw.split(",") if part.strip()]


def collect(lines: Sequence[Line]) -> Suppressions:
    """Read every suppression directive out of *lines*."""
    sites: list[Site] = []
    for line in lines:
        for match in _DIRECTIVE.finditer(line.text):
            file_wide = match.group("file") is not None
            sites.extend(
                Site(line=line.number, rule=rule, file_wide=file_wide)
                for rule in _rules_of(match.group("rules"))
            )
    return Suppressions(sites=tuple(sites))


def _unknown_findings(
    path: Path, suppressions: Suppressions, config: ProseConfig
) -> Iterable[Finding]:
    severity = config.severity("unknown-suppression")
    if severity is Severity.OFF:
        return
    for site in suppressions.sites:
        if site.rule == ALL or site.rule in RULES:
            continue
        yield Finding(
            path=path,
            line=site.line,
            column=0,
            check=CROSS_CUTTING,
            rule="unknown-suppression",
            message=f"no rule is named {site.rule!r}",
            severity=severity,
        )


def _unused_findings(
    path: Path, suppressions: Suppressions, config: ProseConfig
) -> Iterable[Finding]:
    severity = config.severity("unused-suppression")
    if severity is Severity.OFF:
        return
    for site in suppressions.unused():
        yield Finding(
            path=path,
            line=site.line,
            column=0,
            check=CROSS_CUTTING,
            rule="unused-suppression",
            message=f"suppression of {site.rule!r} matched nothing",
            severity=severity,
        )


def audit(path: Path, suppressions: Suppressions, config: ProseConfig) -> list[Finding]:
    """Report suppressions that name no real rule, and (opt-in) ones that did nothing."""
    return [
        *_unknown_findings(path, suppressions, config),
        *_unused_findings(path, suppressions, config),
    ]
