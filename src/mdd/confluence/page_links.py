"""Resolve relative ``.md`` links to Confluence page links before publishing.

A documentation tree links between its pages with relative paths —
``[setup](../ops/setup.md#tokens)``. Rendered verbatim that becomes
``<a href="../ops/setup.md#tokens">``, which is dead in Confluence: there is
no file at that path, only a page whose title the target file declares. This
pass runs on the parsed IR, between ``parse_markdown`` and
``render_confluence_storage``, and swaps every such ``Link`` for a
``ConfluenceLink`` of ``page`` kind whose target is the title the target
file would publish under (same rule as the page itself:
:func:`mdd.confluence.title.resolve_page_title`).

Working on the IR rather than the body text means code spans, fenced code
and reference-style links are the parser's problem, not a second regex
grammar's — a ``.md`` mention inside backticks is a ``Code`` node and never
reaches this pass.

Only the local → Confluence rendering leg calls this. Export and sync pull
never see relative ``.md`` links in the first place.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.title import resolve_page_title
from mdd.ir.nodes import ConfluenceLink, Emph, Inline, Link, Strikethrough, Strong
from mdd.ir.normalize import transform_text_blocks
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mdd.ir.document import Document

log = get_logger(__name__)


def split_relative_md_href(href: str) -> tuple[str, str] | None:
    """Return ``(path, fragment)`` when *href* is a relative link to a ``.md`` file.

    ``None`` for anything else: absolute URLs, ``mailto:``, root-relative
    paths, ``confluence-*:`` URIs, or a relative path that is not a ``.md``
    file. The ``.md`` test is case-insensitive so a ``README.MD`` on a
    case-preserving filesystem still resolves.
    """
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None
    if not parts.path.lower().endswith(".md"):
        return None
    return parts.path, parts.fragment


def _page_link(link: Link, title: str, fragment: str) -> ConfluenceLink:
    """Build the ``<ac:link><ri:page/></ac:link>`` node that replaces *link*.

    The fragment rides in ``attributes["ac:anchor"]`` — the slot the storage
    reader fills for ``<ac:link ac:anchor="…">`` — so the writer emits it on
    the round-trip the same way it would for an exported page.
    """
    attributes = {"ac:anchor": fragment} if fragment else {}
    return ConfluenceLink(
        target_kind="page",
        target=title,
        body_tokens=link.tokens,
        attributes=attributes,
    )


def _line_of(body_md: str, needle: str) -> int | None:
    """1-based line on which *needle* first appears in *body_md*, if at all.

    Best effort for the warning: the IR carries no source positions and the
    href in the node is already percent-decoded, so an encoded href in the
    source will not be found — the warning then names the file and href only.
    """
    idx = body_md.find(needle)
    if idx < 0:
        return None
    return body_md.count("\n", 0, idx) + 1


class _Resolver:
    """Per-document state: the source path, its body text and a title cache."""

    def __init__(self, md_path: Path, body_md: str) -> None:
        self._md_path = md_path
        self._body_md = body_md
        self._titles: dict[Path, str | None] = {}

    def _title_for(self, target: Path) -> str | None:
        """Publish title of *target*, ``None`` if it is not a readable file."""
        if target not in self._titles:
            self._titles[target] = self._read_title(target)
        return self._titles[target]

    @staticmethod
    def _read_title(target: Path) -> str | None:
        if not target.is_file():
            return None
        try:
            frontmatter, body = read_frontmatter(target)
        except OSError as exc:
            log.warning("cannot read link target %s: %s", target, exc)
            return None
        return resolve_page_title(frontmatter, body, target)

    def _warn_unresolved(self, href: str) -> None:
        line = _line_of(self._body_md, href)
        where = f"{self._md_path}:{line}" if line is not None else str(self._md_path)
        log.warning(
            "%s: link target %r does not exist; leaving the link as written.",
            where,
            href,
        )

    def resolve(self, link: Link) -> Inline:
        """Return the page link for *link*, or *link* itself when it does not apply."""
        split = split_relative_md_href(link.href)
        if split is None:
            return link
        rel_path, fragment = split
        target = (self._md_path.parent / rel_path).resolve()
        title = self._title_for(target)
        if title is None:
            self._warn_unresolved(link.href)
            return link
        return _page_link(link, title, fragment)


def _map_inlines(inlines: list[Inline], fn: Callable[[Link], Inline]) -> list[Inline]:
    """Apply *fn* to every ``Link``, descending through the inline containers.

    Only the wrappers that can hold a link are descended; a link body is
    left alone because a link inside a link is not valid CommonMark.
    """
    out: list[Inline] = []
    for node in inlines:
        if isinstance(node, Link):
            out.append(fn(node))
        elif isinstance(node, (Strong, Emph, Strikethrough)):
            out.append(replace(node, tokens=_map_inlines(node.tokens, fn)))
        else:
            out.append(node)
    return out


def resolve_page_links(doc: Document, md_path: Path, *, body_md: str = "") -> Document:
    """Replace relative ``.md`` links in *doc* with Confluence page links.

    *md_path* is the source file the links are relative to; *body_md* is
    its body text, used only to name a line in the warning for a target
    that does not exist. Links whose target is missing are left untouched.
    """
    resolver = _Resolver(md_path, body_md)
    return transform_text_blocks(doc, lambda inlines: _map_inlines(inlines, resolver.resolve))
