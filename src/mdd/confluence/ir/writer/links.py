"""``<ac:link>`` rendering: page, blog-post, attachment, URL, user, shortcut."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from xml.sax.saxutils import quoteattr

from .entities import emit_attrs

if TYPE_CHECKING:
    from mdd.ir.nodes import ConfluenceLink


def _link_attrs(tok: ConfluenceLink) -> str:
    """Build the ``<ac:link>`` attribute string.

    For anchor-kind links, ``ac:anchor`` lives in ``attributes`` (stored there
    by the reader). For markdown-sourced anchor links (``attributes`` empty),
    fall back to deriving it from ``tok.target``.
    """
    if tok.target_kind == "anchor" and tok.target and "ac:anchor" not in tok.attributes:
        return f" ac:anchor={quoteattr(tok.target)}" + emit_attrs(tok.attributes)
    return emit_attrs(tok.attributes)


def _emit_page_link(tok: ConfluenceLink, out: list[str]) -> None:
    a = f" ri:content-title={quoteattr(tok.target)}"
    if tok.space_key:
        a += f" ri:space-key={quoteattr(tok.space_key)}"
    if tok.version_at_save:
        a += f" ri:version-at-save={quoteattr(tok.version_at_save)}"
    out.append(f"<ri:page{a} />")


def _emit_blogpost_link(tok: ConfluenceLink, out: list[str]) -> None:
    a = f" ri:content-title={quoteattr(tok.target)}"
    if tok.space_key:
        a += f" ri:space-key={quoteattr(tok.space_key)}"
    if tok.posting_day:
        a += f" ri:posting-day={quoteattr(tok.posting_day)}"
    out.append(f"<ri:blog-post{a} />")


def _attachment_subpage_attrs(tok: ConfluenceLink) -> str:
    a = ""
    if tok.page_title:
        a += f" ri:content-title={quoteattr(tok.page_title)}"
    if tok.page_space_key:
        a += f" ri:space-key={quoteattr(tok.page_space_key)}"
    if tok.version_at_save:
        a += f" ri:version-at-save={quoteattr(tok.version_at_save)}"
    return a


def _emit_attachment_link(tok: ConfluenceLink, out: list[str]) -> None:
    a = f" ri:filename={quoteattr(tok.target)}"
    if tok.version_at_save:
        a += f" ri:version-at-save={quoteattr(tok.version_at_save)}"
    if tok.page_title or tok.page_space_key:
        out.append(f"<ri:attachment{a}>")
        out.append(f"<ri:page{_attachment_subpage_attrs(tok)} />")
        out.append("</ri:attachment>")
    else:
        out.append(f"<ri:attachment{a} />")


def _emit_url_link(tok: ConfluenceLink, out: list[str]) -> None:
    out.append(f"<ri:url ri:value={quoteattr(tok.target)} />")


def _emit_user_link(tok: ConfluenceLink, out: list[str]) -> None:
    extra = ""
    if tok.user_local_id:
        extra += f" ri:local-id={quoteattr(tok.user_local_id)}"
    out.append(f"<ri:user ri:account-id={quoteattr(tok.target)}{extra} />")


def _emit_shortcut_link(tok: ConfluenceLink, out: list[str]) -> None:
    out.append(f"<ri:shortcut ri:key={quoteattr(tok.target)} />")


_CONFLUENCE_LINK_TARGETS: dict[str, object] = {
    "page": _emit_page_link,
    "blogpost": _emit_blogpost_link,
    "attachment": _emit_attachment_link,
    "url": _emit_url_link,
    "user": _emit_user_link,
    "shortcut": _emit_shortcut_link,
}


def render_confluence_link(
    tok: ConfluenceLink,
    out: list[str],
    *,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # Deferred import to break the links.py ↔ inlines.py cycle.
    from .inlines import render_inlines  # noqa: PLC0415

    out.append(f"<ac:link{_link_attrs(tok)}>")
    emitter = _CONFLUENCE_LINK_TARGETS.get(tok.target_kind)
    if emitter is not None:
        emitter(tok, out)  # pyright: ignore[reportCallIssue]
    if tok.body_tokens:
        out.append("<ac:link-body>")
        render_inlines(tok.body_tokens, out, mode=mode)
        out.append("</ac:link-body>")
    out.append("</ac:link>")
