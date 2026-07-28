"""``<ac:link>`` → ``ConfluenceLink`` handler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mdd.ir.nodes import ConfluenceLink, Inline, Text

from .attrs import all_attrs_ordered

_AC = "http://atlassian.com/content"
_RI = "http://atlassian.com/repository/confluence/1.0"

_AC_LINK_BODY = f"{{{_AC}}}link-body"
_AC_PLAIN_LINK_BODY = f"{{{_AC}}}plain-text-link-body"
_AC_ANCHOR = f"{{{_AC}}}anchor"

_RI_PAGE = f"{{{_RI}}}page"
_RI_BLOG_POST = f"{{{_RI}}}blog-post"
_RI_ATTACHMENT = f"{{{_RI}}}attachment"
_RI_URL = f"{{{_RI}}}url"
_RI_USER = f"{{{_RI}}}user"
_RI_SPACE = f"{{{_RI}}}space"
_RI_SHORTCUT = f"{{{_RI}}}shortcut"


@dataclass
class _LinkState:
    target_kind: str = "url"
    target: str = ""
    space_key: str = ""
    version_at_save: str = ""
    posting_day: str = ""
    page_title: str = ""
    page_space_key: str = ""
    user_local_id: str = ""
    body_tokens: list[Inline] = field(default_factory=list)


def _read_page_child(child: Any, state: _LinkState) -> None:
    state.target_kind = "page"
    state.target = child.get(f"{{{_RI}}}content-title") or ""
    state.space_key = child.get(f"{{{_RI}}}space-key") or ""
    state.version_at_save = child.get(f"{{{_RI}}}version-at-save") or ""


def _read_blogpost_child(child: Any, state: _LinkState) -> None:
    state.target_kind = "blogpost"
    state.target = child.get(f"{{{_RI}}}content-title") or ""
    state.space_key = child.get(f"{{{_RI}}}space-key") or ""
    state.posting_day = child.get(f"{{{_RI}}}posting-day") or ""


def _read_attachment_child(child: Any, state: _LinkState) -> None:
    state.target_kind = "attachment"
    state.target = child.get(f"{{{_RI}}}filename") or ""
    state.version_at_save = child.get(f"{{{_RI}}}version-at-save") or ""
    for sub in child:
        sub_tag = sub.tag if isinstance(sub.tag, str) else ""
        if sub_tag == _RI_PAGE:
            state.page_title = sub.get(f"{{{_RI}}}content-title") or ""
            state.page_space_key = sub.get(f"{{{_RI}}}space-key") or ""
        elif sub_tag == _RI_SPACE:
            state.space_key = sub.get(f"{{{_RI}}}space-key") or ""


def _dispatch_child(child: Any, state: _LinkState, read_inline_children: Any) -> None:
    tag = child.tag if isinstance(child.tag, str) else ""
    if tag == _RI_PAGE:
        _read_page_child(child, state)
    elif tag == _RI_BLOG_POST:
        _read_blogpost_child(child, state)
    elif tag == _RI_ATTACHMENT:
        _read_attachment_child(child, state)
    elif tag == _RI_URL:
        state.target_kind = "url"
        state.target = child.get(f"{{{_RI}}}value") or ""
    elif tag == _RI_USER:
        state.target_kind = "user"
        state.target = child.get(f"{{{_RI}}}account-id") or child.get(f"{{{_RI}}}userkey") or ""
        state.user_local_id = child.get(f"{{{_RI}}}local-id") or ""
    elif tag == _RI_SHORTCUT:
        state.target_kind = "shortcut"
        state.target = child.get(f"{{{_RI}}}key") or ""
    elif tag in {_AC_LINK_BODY, _AC_PLAIN_LINK_BODY}:
        state.body_tokens = read_inline_children(child)


def read_ac_link(
    node: Any,
    read_inline_children: Any,
    *,
    block_level: bool = False,
) -> ConfluenceLink:
    """Parse an ``<ac:link>`` element into a ``ConfluenceLink``.

    ``block_level=True`` sets ``ConfluenceLink.block_level=True`` so the
    storage writer emits the link bare on the round-trip instead of
    re-wrapping it in a ``<p>``.
    """
    state = _LinkState()
    anchor = node.get(_AC_ANCHOR)
    if anchor:
        state.target_kind = "anchor"
        state.target = anchor

    for child in node:
        _dispatch_child(child, state, read_inline_children)

    if not state.body_tokens:
        text_in = node.text or ""
        if text_in:
            state.body_tokens = [Text(text_in)]

    return ConfluenceLink(
        target_kind=state.target_kind,  # type: ignore[arg-type]
        target=state.target,
        body_tokens=state.body_tokens,
        block_level=block_level,
        space_key=state.space_key,
        version_at_save=state.version_at_save,
        posting_day=state.posting_day,
        page_title=state.page_title,
        page_space_key=state.page_space_key,
        user_local_id=state.user_local_id,
        attributes=all_attrs_ordered(node),
    )
