"""``mdd prose anchors`` — internal cross-references resolve.

The slugging rule is GitHub's, stated explicitly so a project can tell whether
its renderer agrees: lowercase the heading text; strip Markdown inline markup,
leaving its text; remove every character that is not a letter, digit, space,
hyphen or underscore; replace *each* remaining space with one hyphen.

Each space, not each run of spaces: a heading like ``### foo — bar`` loses the
em dash and keeps both spaces around it, so its anchor is ``foo--bar``.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from mdd.prose.classify import ClassifyError, LineClass, classify
from mdd.prose.report import Finding, make_excerpt
from mdd.prose.rules import Severity

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from mdd.prose.classify import Classified, Line
    from mdd.prose.config import ProseConfig

_ATX_MARKERS = re.compile(r"^ {0,3}(#{1,6})[ \t]*")
_EXPLICIT_ID = re.compile(r"[ \t]*\{#([^}\s]+)\}[ \t]*#*[ \t]*$")
_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_REF_LINK = re.compile(r"!?\[([^\]]*)\]\[[^\]]*\]")
_SLUG_DROP = re.compile(r"[^\w \-]", re.UNICODE)
_SETEXT_RULE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")

_SUGGESTION_CUTOFF = 0.6


def slug(heading_text: str) -> str:
    """Return the GitHub anchor slug for *heading_text*."""
    text = _LINK_TEXT.sub(r"\1", heading_text)
    text = _REF_LINK.sub(r"\1", text)
    text = _SLUG_DROP.sub("", text.lower())
    return text.strip().replace(" ", "-")


def heading_text(line: Line) -> str:
    """Return the visible text of a heading line, with any ``{#id}`` removed."""
    body = _ATX_MARKERS.sub("", line.text.strip())
    body = re.sub(r"[ \t]+#*$", "", body)
    return _EXPLICIT_ID.sub("", body).strip()


def explicit_id(line: Line) -> str | None:
    """Return the ``{#explicit-id}`` on a heading line, if it carries one."""
    match = _EXPLICIT_ID.search(line.text.rstrip())
    return match.group(1) if match is not None else None


@dataclass(frozen=True)
class Anchor:
    """One heading's resolved anchor."""

    line: int
    text: str
    slug: str


def _heading_lines(lines: Sequence[Line]) -> Iterable[Line]:
    for line in lines:
        if line.cls is not LineClass.HEADING:
            continue
        if _SETEXT_RULE.match(line.text) and not line.text.lstrip().startswith("#"):
            continue
        yield line


def anchors_of(classified: Classified) -> tuple[Anchor, ...]:
    """Return every heading anchor in *classified*, with collision numbering applied."""
    seen: dict[str, int] = {}
    out: list[Anchor] = []
    for line in _heading_lines(classified.lines):
        text = heading_text(line)
        base = explicit_id(line) or slug(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(
            Anchor(line=line.number, text=text, slug=base if count == 0 else f"{base}-{count}")
        )
    return tuple(out)


@dataclass
class AnchorIndex:
    """Cache of per-file anchor sets, so a hub file is classified once."""

    cache: dict[Path, tuple[Anchor, ...] | None] = field(default_factory=dict)

    def preload(self, path: Path, classified: Classified) -> None:
        """Record the anchors of an already-classified file."""
        self.cache[path.resolve()] = anchors_of(classified)

    def anchors(self, path: Path) -> tuple[Anchor, ...] | None:
        """Return *path*'s anchors, or ``None`` when it cannot be classified."""
        key = path.resolve()
        if key in self.cache:
            return self.cache[key]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            self.cache[key] = None
            return None
        result = classify(text)
        anchors = None if isinstance(result, ClassifyError) else anchors_of(result)
        self.cache[key] = anchors
        return anchors


@dataclass(frozen=True)
class InternalLink:
    """One internal link: where it was written, and what it points at."""

    line: int
    column: int
    raw: str
    target: str
    fragment: str


def _is_external(target: str) -> bool:
    return bool(urlsplit(target).scheme) or target.startswith("//")


def internal_links(classified: Classified) -> tuple[InternalLink, ...]:
    """Return every internal link in *classified*, external schemes excluded."""
    out: list[InternalLink] = []
    for line in classified.lines:
        if line.cls in (LineClass.FENCED_CODE, LineClass.INDENTED_CODE, LineClass.HTML_COMMENT):
            continue
        for ref in line.links:
            raw = ref.target
            if not raw or _is_external(raw):
                continue
            path_part, _, fragment = raw.partition("#")
            out.append(
                InternalLink(
                    line=line.number,
                    column=ref.start + 1,
                    raw=raw,
                    target=unquote(path_part),
                    fragment=unquote(fragment),
                )
            )
    return tuple(out)


def _suggestion(fragment: str, anchors: Sequence[Anchor]) -> str:
    close = difflib.get_close_matches(
        fragment, [a.slug for a in anchors], n=1, cutoff=_SUGGESTION_CUTOFF
    )
    return f"; did you mean {close[0]!r}?" if close else ""


def _resolve_target(path: Path, link: InternalLink) -> Path:
    return path if not link.target else (path.parent / link.target)


def _missing_file(path: Path, link: InternalLink, line: Line, config: ProseConfig) -> Finding:
    return Finding(
        path=path,
        line=link.line,
        column=link.column,
        check="anchors",
        rule="missing-file",
        message=f"link target {link.target!r} does not exist",
        severity=config.severity("missing-file"),
        excerpt=make_excerpt(line.text, link.column),
    )


def _missing_anchor(
    path: Path,
    link: InternalLink,
    line: Line,
    anchors: Sequence[Anchor],
    config: ProseConfig,
) -> Finding:
    where = link.target or "this file"
    return Finding(
        path=path,
        line=link.line,
        column=link.column,
        check="anchors",
        rule="missing-anchor",
        message=f"no heading in {where} slugs to {link.fragment!r}"
        + _suggestion(link.fragment, anchors),
        severity=config.severity("missing-anchor"),
        excerpt=make_excerpt(line.text, link.column),
    )


def _ambiguous(path: Path, anchors: Sequence[Anchor], config: ProseConfig) -> list[Finding]:
    severity = config.severity("ambiguous-anchor")
    if severity is Severity.OFF:
        return []
    counts: dict[str, int] = {}
    out: list[Finding] = []
    for anchor in anchors:
        counts[anchor.text] = counts.get(anchor.text, 0) + 1
        if counts[anchor.text] == 1:
            continue
        out.append(
            Finding(
                path=path,
                line=anchor.line,
                column=0,
                check="anchors",
                rule="ambiguous-anchor",
                message=(
                    f"heading {anchor.text!r} repeats; a link to it resolves by "
                    "document order and a reorder retargets it silently"
                ),
                severity=severity,
            )
        )
    return out


def _one_link(
    path: Path,
    link: InternalLink,
    line: Line,
    index: AnchorIndex,
    config: ProseConfig,
) -> Finding | None:
    """Resolve one internal link, returning the finding it produces or ``None``."""
    target = _resolve_target(path, link)
    if not target.exists():
        if config.severity("missing-file") is Severity.OFF:
            return None
        return _missing_file(path, link, line, config)
    if not link.fragment or config.severity("missing-anchor") is Severity.OFF:
        return None
    anchors = index.anchors(target)
    if anchors is None or link.fragment in {a.slug for a in anchors}:
        return None
    return _missing_anchor(path, link, line, anchors, config)


def _link_findings(
    path: Path,
    classified: Classified,
    index: AnchorIndex,
    config: ProseConfig,
) -> Iterable[Finding]:
    by_number = {line.number: line for line in classified.lines}
    for link in internal_links(classified):
        finding = _one_link(path, link, by_number[link.line], index, config)
        if finding is not None:
            yield finding


def run(
    path: Path,
    classified: Classified,
    config: ProseConfig,
    index: AnchorIndex,
) -> list[Finding]:
    """Check every internal link in *classified* and report duplicate headings."""
    index.preload(path, classified)
    own = anchors_of(classified)
    return [*_link_findings(path, classified, index, config), *_ambiguous(path, own, config)]
