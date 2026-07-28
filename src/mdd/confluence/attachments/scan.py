"""Scan a markdown body for local image / attachment references."""

from __future__ import annotations

import re
import urllib.parse

_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
# A plain markdown link with a ``confluence-attachment:`` target rides
# the same upload path as an image: the sibling file must be attached
# to the page so the rendered ``<ac:link><ri:attachment …/></ac:link>``
# resolves at view time.
_ATTACHMENT_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(confluence-attachment:([^)]+)\)")
# Reference-style image: ``![alt][label]`` (collapsed: ``![alt][]``;
# shortcut: ``![label]``) — the bracketed label points at a separate
# ``[label]: url`` definition, not at the image source directly.
_IMG_FULL_REF_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
_IMG_SHORTCUT_REF_RE = re.compile(r"!\[([^\]]+)\](?![\[(:])")
# Link reference definitions, CommonMark §4.7: ``[label]: destination [title]``.
# Anchored to start of line (after up to 3 spaces) per the spec.
_REF_DEF_RE = re.compile(
    r"^ {0,3}\[([^\]]+)\]:\s*<?([^\s<>]+)>?(?:\s+[\"'(].*?[\"')])?\s*$",
    re.MULTILINE,
)
_FENCE_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})")


def collect_ref_defs(body_md: str) -> dict[str, str]:
    """Extract ``[label]: url`` reference definitions, keyed by lowercased label.

    CommonMark §4.7: reference labels are matched case-insensitively after
    Unicode case folding and whitespace normalisation.
    """
    defs: dict[str, str] = {}
    for m in _REF_DEF_RE.finditer(body_md):
        label = " ".join(m.group(1).split()).lower()
        if label and label not in defs:
            defs[label] = m.group(2)
    return defs


def strip_code_for_scan(body_md: str) -> str:
    """Return body_md with fenced code blocks and inline code spans blanked out.

    Image-reference patterns that appear inside backtick code spans or fenced
    code blocks are author prose (documentation examples), not actual links,
    so the upload scanner must ignore them. Code regions are replaced with
    whitespace rather than removed so line/column offsets stay aligned.
    """
    lines = body_md.splitlines(keepends=True)
    out: list[str] = []
    fence: str | None = None
    for line in lines:
        if fence is None:
            m = _FENCE_RE.match(line)
            if m:
                fence = m.group("fence")[0] * len(m.group("fence"))
                out.append(" " * len(line.rstrip("\n")) + line[len(line.rstrip("\n")) :])
                continue
            out.append(line)
        else:
            stripped = line.lstrip(" ")
            if stripped.startswith(fence[0]) and stripped.rstrip("\n").rstrip() == fence:
                fence = None
            out.append(" " * len(line.rstrip("\n")) + line[len(line.rstrip("\n")) :])
    text = "".join(out)

    # Blank out inline code spans. CommonMark allows multi-backtick delimiters
    # (e.g. ``code with ` inside``); match the longest delimiter first so the
    # short-form regex doesn't gobble half of a long-form span.
    def _blank(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    for n in (3, 2, 1):
        ticks = "`" * n
        esc = re.escape(ticks)
        pattern = re.compile(rf"{esc}(?!`)(.+?)(?<!`){esc}(?!`)", re.DOTALL)
        text = pattern.sub(_blank, text)
    return text


def split_url_and_title(paren_content: str) -> str:
    """Drop the optional ``"title"`` / ``'title'`` slot from CommonMark link/image
    paren content. ``url`` → ``url``; ``url "title"`` → ``url``.
    """
    text = paren_content.strip()
    # CommonMark allows " or ' delimiters (and parenthesised titles, but those
    # don't occur in our writer output). The URL ends at the first run of
    # whitespace before a quote.
    m = re.match(r"\s*(\S+?)(?:\s+[\"'(].*)?\s*$", text)
    return m.group(1) if m else text


def clean_attachment_uri(uri: str) -> str:
    """Strip ``confluence-attachment:`` scheme + ``;extras`` and URL-decode.

    Returns the bare filename. If *uri* does not use the scheme, the input is
    returned unchanged (after URL decoding) so callers can pass any image src
    through this normaliser.
    """
    uri = uri.removeprefix("confluence-attachment:")
    uri = uri.split(";", 1)[0]
    return urllib.parse.unquote(uri)


def scan_local_image_refs(body_md: str) -> list[str]:
    """Return all local (non-HTTP) image source paths found in body_md.

    Skips ``![alt](src)`` patterns inside fenced code blocks or inline code
    spans, which are author prose rather than real image references. Also
    walks reference-style images (``![alt][label]``, ``![alt][]``, and the
    shortcut ``![label]``), resolving the bracketed label against the
    ``[label]: url`` definitions in *body_md* — without resolution the
    upload scanner would use the literal label as a filename and warn that
    a non-existent file was missing.

    Image refs that use the ``confluence-attachment:`` synthetic URI emitted
    by ``render_markdown`` are normalised back to a bare filename: the scheme
    prefix, the semicolon-delimited extras, the markdown ``"title"`` slot, and
    URL-encoding are all stripped.
    """
    refs: list[str] = []
    scan_text = strip_code_for_scan(body_md)
    ref_defs = collect_ref_defs(scan_text)

    def _maybe_local(src: str) -> None:
        src = src.strip("<>")
        if src and not src.startswith(("http://", "https://")):
            refs.append(src)

    for m in _IMG_REF_RE.finditer(scan_text):
        url = split_url_and_title(m.group(1))
        _maybe_local(clean_attachment_uri(url))
    for m in _ATTACHMENT_LINK_RE.finditer(scan_text):
        # ``confluence-attachment:`` URIs are always relative filenames,
        # never absolute http(s) URLs — strip semicolon-delimited extras
        # (e.g. ``;version-at-save=3``) and the markdown ``"title"`` slot so
        # the upload uses the bare name.
        url = split_url_and_title(m.group(1))
        _maybe_local(urllib.parse.unquote(url.split(";", 1)[0]))
    for m in _IMG_FULL_REF_RE.finditer(scan_text):
        alt = m.group(1)
        label_raw = m.group(2)
        # Collapsed reference: ``![alt][]`` falls back to ``alt`` as the label.
        label = " ".join((label_raw or alt).split()).lower()
        url = ref_defs.get(label)
        if url is not None:
            _maybe_local(clean_attachment_uri(url))
    for m in _IMG_SHORTCUT_REF_RE.finditer(scan_text):
        label = " ".join(m.group(1).split()).lower()
        url = ref_defs.get(label)
        if url is not None:
            _maybe_local(clean_attachment_uri(url))
    return refs
