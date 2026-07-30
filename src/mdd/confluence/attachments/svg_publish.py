"""Rasterize SVGs referenced as markdown images to PNG before publish.

Confluence Cloud does not render SVG attachments inline (XSS hardening — it
shows a download link instead), so an SVG referenced as a markdown *image*
must be rasterized to PNG before ``mdd confluence update-page`` /
``create-page`` can make it display. ``sync_attachments_for_update``
otherwise uploads referenced local files byte-for-byte with no conversion —
this module fills that gap, mirroring in reverse what the export/pull side
already does via ``SvgToPngConverter`` (see ``sync_all.py``).

Scope: only markdown *image* syntax (``![alt](src)``, including the
``confluence-attachment:`` scheme) is rasterized and rewritten. A plain
``[text](confluence-attachment:foo.svg)`` *link* is left untouched — that is
a deliberate reference to the source file for download, not a display
reference, so the raw SVG still gets uploaded byte-for-byte via the normal
:func:`~.update.sync_attachments_for_update` path. Reference-style images
(``![alt][label]``) and raw HTML ``<img>``/``<picture>`` tags are not (yet)
detected — tracked as a follow-up.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.converters.svg import SvgToPngConverter
from mdd.utils.logging import get_logger

from ._types import AttachmentManifestEntry
from ._version import extract_upload_version
from .scan import clean_attachment_uri, strip_code_for_scan

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient

log = get_logger(__name__)

# Full-match variant of scan.py's ``_IMG_REF_RE``: captures alt text
# separately so a matched ref can be reconstructed after rewriting its url.
_IMG_REF_FULL_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<paren>[^)]+)\)")
_URL_AND_TITLE_RE = re.compile(r"\s*(?P<url>\S+?)(?P<title>\s+[\"'(].*)?\s*$")


def _split_url_and_title_parts(paren_content: str) -> tuple[str, str]:
    """Split paren content into ``(url, title_suffix)``.

    Like ``scan.split_url_and_title``, but also returns the title slot (with
    its leading whitespace, verbatim) so callers can reconstruct the full
    paren content after substituting the url.
    """
    m = _URL_AND_TITLE_RE.match(paren_content.strip())
    if not m:
        return paren_content.strip(), ""
    return m.group("url"), m.group("title") or ""


def scan_local_svg_image_refs(body_md: str) -> set[str]:
    """Return basenames of local ``.svg`` files referenced via markdown
    *image* syntax (``![alt](src)``, including the ``confluence-attachment:``
    scheme). See module docstring for what is deliberately excluded.
    """
    scan_text = strip_code_for_scan(body_md)
    basenames: set[str] = set()
    for m in _IMG_REF_FULL_RE.finditer(scan_text):
        url, _title = _split_url_and_title_parts(m.group("paren"))
        src = url.strip("<>")
        if not src or src.startswith(("http://", "https://")):
            continue
        name = Path(clean_attachment_uri(src)).name
        if name.lower().endswith(".svg"):
            basenames.add(name)
    return basenames


def _new_attachment_target(raw_url: str, new_basename: str) -> str:
    """Return ``<new_basename>[;extras]``, preserving *raw_url*'s
    ``;key=value`` suffix (export round-trips carry ``;version-at-save=N``).
    """
    stripped = raw_url.removeprefix("confluence-attachment:")
    _, sep, extras = stripped.partition(";")
    return f"{new_basename};{extras}" if sep else new_basename


def _rewrite_img_match(m: re.Match[str], png_by_svg_basename: dict[str, str]) -> str | None:
    """Return the replacement text for one image match, or None to leave it as-is."""
    alt = m.group("alt")
    url, title = _split_url_and_title_parts(m.group("paren"))
    basename = Path(clean_attachment_uri(url.strip("<>"))).name
    new_basename = png_by_svg_basename.get(basename)
    if new_basename is None:
        return None
    new_target = _new_attachment_target(url, new_basename)
    return f"![{alt}](confluence-attachment:{new_target}{title})"


def rewrite_svg_refs_to_png(body_md: str, png_by_svg_basename: dict[str, str]) -> str:
    """Rewrite markdown *image* refs pointing at a rasterized ``.svg`` to a
    ``confluence-attachment:`` URI for its ``.svg.png`` sibling, so the IR
    writer (``macros.py``) emits ``<ac:image><ri:attachment/></ac:image>``
    instead of a bare ``<img>``.

    Refs inside fenced code blocks or inline code spans are left untouched.
    """
    if not png_by_svg_basename:
        return body_md
    scan_text = strip_code_for_scan(body_md)
    edits: list[tuple[int, int, str]] = []
    for m in _IMG_REF_FULL_RE.finditer(scan_text):
        repl = _rewrite_img_match(m, png_by_svg_basename)
        if repl is not None:
            edits.append((m.start(), m.end(), repl))
    if not edits:
        return body_md

    out: list[str] = []
    pos = 0
    for start, end, repl in edits:
        out.append(body_md[pos:start])
        out.append(repl)
        pos = end
    out.append(body_md[pos:])
    return "".join(out)


def _upload_rasterized_png(
    client: ConfluenceClient,
    page_id: str,
    png_path: Path,
    png_basename: str,
    manifest_by_name: dict[str, AttachmentManifestEntry],
) -> AttachmentManifestEntry:
    """Upload *png_path* unless its hash matches the cached manifest entry."""
    sha256 = hashlib.sha256(png_path.read_bytes()).hexdigest()
    existing = manifest_by_name.get(png_basename)
    if existing is not None and existing.sha256 == sha256:
        return existing
    result = client.upload_attachment(page_id, png_path)
    return AttachmentManifestEntry(
        filename=png_basename,
        sha256=sha256,
        version=extract_upload_version(result),
    )


def rasterize_and_upload_svg_images(
    client: ConfluenceClient,
    page_id: str,
    body_md: str,
    resolved: dict[str, Path],
    manifest_by_name: dict[str, AttachmentManifestEntry],
) -> tuple[dict[str, AttachmentManifestEntry], str]:
    """Rasterize SVGs referenced as markdown images, upload the PNGs, and
    rewrite those image refs to point at the uploaded PNG attachment.

    *resolved* is the basename → absolute-path map already computed by
    :func:`~.update.sync_attachments_for_update` for the same body — the raw
    SVG itself is uploaded there unchanged (this function only adds the
    rasterized PNG as an extra attachment).

    Returns:
        ``(new manifest entries keyed by png basename, rewritten body_md)``;
        the caller merges the entries into its own manifest dict.
    """
    svg_basenames = scan_local_svg_image_refs(body_md) & resolved.keys()
    if not svg_basenames:
        return {}, body_md

    converter = SvgToPngConverter()
    png_by_svg: dict[str, str] = {}
    new_entries: dict[str, AttachmentManifestEntry] = {}
    for basename in svg_basenames:
        svg_path = resolved[basename]
        if not svg_path.exists():
            continue
        try:
            result = converter.convert(svg_path)
        except (RuntimeError, ValueError) as exc:
            log.warning(
                "SVG rasterization failed for %s: %s; the reference is left "
                "pointing at the raw SVG (Confluence will show a download "
                "link, not an inline image).",
                svg_path,
                exc,
            )
            continue
        png_basename = result.output_path.name
        png_by_svg[basename] = png_basename
        new_entries[png_basename] = _upload_rasterized_png(
            client, page_id, result.output_path, png_basename, manifest_by_name
        )

    rewritten_body = rewrite_svg_refs_to_png(body_md, png_by_svg) if png_by_svg else body_md
    return new_entries, rewritten_body
