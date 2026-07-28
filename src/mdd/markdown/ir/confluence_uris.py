"""Synthetic URI scheme for ConfluenceLink / ConfluenceImage round-trips.

Spec S30 §"Synthetic URIs for Confluence link family":

    confluence-page:<space>/<title>         page link (space optional)
    confluence-attachment:<filename>         attachment link or image
    confluence-blogpost:<space>/<title>      blog-post link
    confluence-user:<accountId>              user mention
    confluence-shortcut:<key>/<target>       shortcut link
    confluence-image-url:<url>               image from external URL

Extras (space, anchor, width, …) ride on semicolon-delimited query segments:
    confluence-page:MDD/Home;anchor=intro;version-at-save=3

Public surface:

    parse_confluence_uri(uri)  -> ConfluenceLink | ConfluenceImage | None
    render_confluence_uri(node) -> str
"""

from __future__ import annotations

import urllib.parse

from mdd.ir.nodes import ConfluenceImage, ConfluenceLink

_LINK_SCHEMES: dict[str, str] = {
    "confluence-page": "page",
    "confluence-attachment": "attachment",
    "confluence-blogpost": "blogpost",
    "confluence-anchor": "anchor",
    "confluence-user": "user",
    "confluence-shortcut": "shortcut",
}

# Schemes that produce ConfluenceImage when found in an image src.
_IMAGE_SRC_SCHEMES: set[str] = {"confluence-attachment", "confluence-image-url"}


def parse_confluence_link_uri(uri: str) -> ConfluenceLink | None:
    """Parse *uri* as a link target; return ConfluenceLink or None."""
    scheme, _, rest = uri.partition(":")
    if not rest:
        return None
    if scheme in _LINK_SCHEMES:
        raw_target, raw_extras = _split_extras(rest)
        kind = _LINK_SCHEMES[scheme]
        if kind in ("page", "blogpost"):
            raw_target, raw_extras = _unpack_space_and_anchor(raw_target, raw_extras)
        anchor = raw_extras.get("anchor", "")
        attributes = {"ac:anchor": anchor} if anchor else {}
        return ConfluenceLink(
            target_kind=kind,  # pyright: ignore[reportArgumentType]
            target=raw_target,
            space_key=raw_extras.get("space-key", ""),
            version_at_save=raw_extras.get("version-at-save", ""),
            posting_day=raw_extras.get("posting-day", ""),
            page_title=raw_extras.get("page-title", ""),
            page_space_key=raw_extras.get("page-space-key", ""),
            user_local_id=raw_extras.get("ri-local-id", ""),
            attributes=attributes,
        )
    return None


def parse_confluence_image_uri(uri: str) -> ConfluenceImage | None:
    """Parse *uri* as an image source; return ConfluenceImage or None."""
    scheme, _, rest = uri.partition(":")
    if not rest:
        return None
    if scheme in _IMAGE_SRC_SCHEMES:
        target, raw_extras = _split_extras(rest)
        source_kind: str = "attachment" if scheme == "confluence-attachment" else "url"
        # Move image presentation attrs into attributes with ac: prefix.
        attributes = {f"ac:{k}": v for k, v in raw_extras.items()}
        attachment_version = raw_extras.get("version-at-save") or None
        return ConfluenceImage(
            source_kind=source_kind,  # pyright: ignore[reportArgumentType]
            source=target,
            attachment_version=attachment_version,
            attributes=attributes,
        )
    return None


def parse_confluence_uri(uri: str) -> ConfluenceLink | ConfluenceImage | None:
    """Return a typed node if *uri* matches a known confluence-* scheme, else None.

    Prefers ConfluenceImage for image schemes; ConfluenceLink for link schemes.
    When the same scheme can be both (confluence-attachment), returns ConfluenceImage.
    Use :func:`parse_confluence_link_uri` / :func:`parse_confluence_image_uri`
    for context-specific parsing.
    """
    scheme, _, rest = uri.partition(":")
    if not rest:
        return None
    if scheme in _IMAGE_SRC_SCHEMES:
        return parse_confluence_image_uri(uri)
    return parse_confluence_link_uri(uri)


def _render_image_uri(node: ConfluenceImage) -> str:
    scheme = "confluence-image-url" if node.source_kind == "url" else "confluence-attachment"
    uri = f"{scheme}:{_pct(node.source)}"
    for key, value in node.attributes.items():
        if key.startswith("ac:"):
            uri += f";{key[3:]}={_pct(value)}"
    return uri


def _render_link_extras(node: ConfluenceLink, uri: str) -> str:
    if node.space_key:
        uri += f";space-key={_pct(node.space_key)}"
    if anchor := node.attributes.get("ac:anchor"):
        uri += f";anchor={_pct(anchor)}"
    if node.version_at_save:
        uri += f";version-at-save={_pct(node.version_at_save)}"
    if node.posting_day:
        uri += f";posting-day={_pct(node.posting_day)}"
    if node.page_title:
        uri += f";page-title={_pct(node.page_title)}"
    if node.page_space_key:
        uri += f";page-space-key={_pct(node.page_space_key)}"
    if node.user_local_id:
        uri += f";ri-local-id={_pct(node.user_local_id)}"
    return uri


_LINK_SCHEMES_OUT: dict[str, str] = {
    "page": "confluence-page",
    "attachment": "confluence-attachment",
    "blogpost": "confluence-blogpost",
    "anchor": "confluence-anchor",
    "user": "confluence-user",
    "shortcut": "confluence-shortcut",
}


def render_confluence_uri(node: ConfluenceLink | ConfluenceImage) -> str:
    """Build the synthetic URI for a ConfluenceLink or ConfluenceImage."""
    if isinstance(node, ConfluenceImage):
        return _render_image_uri(node)
    if node.target_kind == "url":
        return node.target
    scheme = _LINK_SCHEMES_OUT[node.target_kind]
    return _render_link_extras(node, f"{scheme}:{_pct(node.target)}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_extras(raw: str) -> tuple[str, dict[str, str]]:
    """Split ``target;key=value;key2=value2`` into (target, extras)."""
    parts = raw.split(";")
    target = urllib.parse.unquote(parts[0])
    extras: dict[str, str] = {}
    for part in parts[1:]:
        if not part:
            continue
        key, _, value = part.partition("=")
        extras[key] = urllib.parse.unquote(value)
    return target, extras


def _unpack_space_and_anchor(target: str, extras: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Accept ``[Space/]Title[#Anchor]`` convenience form.

    The canonical written form rides on ``;space-key=`` / ``;anchor=``
    extras (see :func:`render_confluence_uri`), but markdown-first
    authors often write ``confluence-page:MDD/Home#intro``. Hoist the
    optional ``<space>/`` prefix into ``extras["space-key"]`` and the
    optional ``#<anchor>`` suffix into ``extras["anchor"]`` so both
    forms produce the same IR — and so the storage writer can emit
    ``<ri:page ri:space-key="…" ri:content-title="…" ac:anchor="…" />``
    in either case.

    Explicit extras win: if the URI already carries
    ``;space-key=`` / ``;anchor=`` we leave the target untouched.
    """
    if "#" in target and "anchor" not in extras:
        target, _, anchor = target.rpartition("#")
        if anchor:
            extras = {**extras, "anchor": anchor}
    if "/" in target and "space-key" not in extras:
        space, _, rest = target.partition("/")
        if space and rest:
            target = rest
            extras = {**extras, "space-key": space}
    return target, extras


def _pct(text: str) -> str:
    """Percent-encode characters that would break the URI shape."""
    return urllib.parse.quote(text, safe="/")
