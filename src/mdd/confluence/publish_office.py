"""publish_office.py — render + upload + body-callout for office publishing (spec S17).

Called by ``sync.py`` for every page whose frontmatter contains::

    confluence:
      publish_office: docx       # or pptx, or [docx, pptx]

Flow (per format):
  1. Compute SHA-256 of source markdown.
  2. Check cache in frontmatter; skip render if source + template + Quarto version match.
  3. Render to a temp file via the Quarto reverse converter.
  4. Compute SHA-256 of rendered file.  If it matches cached attachment_sha256,
     skip upload (byte-identical output).
  5. Check that no user-uploaded attachment with the same name already exists;
     raise OfficePublishCollisionError if so.
  6. Upload via the v1 multipart endpoint; record version number.
  7. Update frontmatter cache block.
  8. Rebuild body callout in storage XHTML via header.insert_office_callout.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.header import insert_office_callout, strip_office_callout
from mdd.confluence.managed import (
    ManagedConfig,
    build_page_info_from_page_data,
    classify_page,
    warn_managed,
)
from mdd.confluence.paths import sanitize
from mdd.converters.quarto import (
    QuartoDocxRenderer,
    QuartoNotFoundError,
    QuartoPptxRenderer,
    bundled_reference_doc,
    quarto_version,
)
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.converters.protocol import RenderResult

log = get_logger(__name__)


class OfficePublishCollisionError(Exception):
    """A user-uploaded attachment with the same name as our target already exists.

    The user must rename the existing attachment in Confluence before sync can
    publish the office file.
    """


class OfficePublishError(Exception):
    """General office-publish failure (Quarto render, upload, etc.)."""


# Sentinel used in the body callout (must match header.py's sentinel).
_CALLOUT_SENTINEL = "(this attachment is generated from the markdown source)"

# Accepted values for publish_office frontmatter key.
_VALID_FORMATS: frozenset[str] = frozenset({"docx", "pptx"})


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _FrontMatter:
    """Typed wrapper around the YAML frontmatter dict for a publishable page.

    Owns the small set of accessors and mutators that publish_office cares
    about: the ``publish_office`` key (opt-in formats) and the
    ``publish_office_state`` cache block. ``data`` is mutated in place; callers
    persist via ``write_frontmatter(md_path, fm.data, body_md)``.
    """

    data: dict[str, Any]

    def publish_formats(self) -> list[str]:
        """Extract ``publish_office`` value, returning a list of formats.

        Valid return values: [], ['docx'], ['pptx'], ['docx', 'pptx'].

        Raises:
            ValueError: if the value contains invalid format strings.
        """
        conf_raw: Any = self.data.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            return []
        conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
        po: Any = conf.get("publish_office")  # pyright: ignore[reportAny]

        if po is None:
            return []
        if isinstance(po, str):
            formats: list[str] = [po]
        elif isinstance(po, list):
            po_list: list[Any] = po  # pyright: ignore[reportUnknownVariableType]
            formats = [str(v) for v in po_list]
        else:
            raise ValueError(f"publish_office must be a string or list, got {type(po).__name__}")

        bad = [f for f in formats if f not in _VALID_FORMATS]
        if bad:
            raise ValueError(
                f"publish_office contains invalid format(s): {bad!r}. "
                f"Accepted values: {sorted(_VALID_FORMATS)}"
            )
        return formats

    def state(self, fmt: str) -> dict[str, Any]:
        """Return the per-format cache dict (may be empty)."""
        conf_raw: Any = self.data.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            return {}
        conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
        state_raw: Any = conf.get("publish_office_state")  # pyright: ignore[reportAny]
        if not isinstance(state_raw, dict):
            return {}
        state: dict[str, Any] = state_raw  # pyright: ignore[reportUnknownVariableType]
        fmt_raw: Any = state.get(fmt)  # pyright: ignore[reportAny]
        if not isinstance(fmt_raw, dict):
            return {}
        return fmt_raw  # pyright: ignore[reportReturnType, reportUnknownVariableType]

    def set_state(self, fmt: str, state_entry: dict[str, Any]) -> None:
        """Write the per-format cache dict in-place."""
        conf_raw: Any = self.data.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            return
        conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
        state_raw: Any = conf.get("publish_office_state")  # pyright: ignore[reportAny]
        if not isinstance(state_raw, dict):
            conf["publish_office_state"] = {}
            state_raw = conf["publish_office_state"]
        state: dict[str, Any] = state_raw  # pyright: ignore[reportUnknownVariableType]
        state[fmt] = state_entry


def _cache_hit(
    state: dict[str, Any],
    source_sha256: str,
    template_sha256: str,
    qversion: str,
) -> bool:
    """Return True when all three cache inputs match."""
    match state:
        case {
            "source_sha256": str(s),
            "template_sha256": str(t),
            "quarto_version": str(q),
        }:
            return s == source_sha256 and t == template_sha256 and q == qversion
        case _:
            return False


def _attachment_name(md_path: Path, fmt: str) -> str:
    """Return the Confluence attachment filename for *md_path* and *fmt*.

    Uses the spec-009 sanitiser on the stem, then appends the format extension.
    """
    stem = sanitize(md_path.stem)
    return f"{stem}.{fmt}"


def _attachment_relative_link(att: dict[str, Any]) -> str | None:
    """Return the v2 ``downloadLink`` or the v1 ``_links.download`` for this attachment.

    Both shapes are produced by different Confluence response versions; v2
    is preferred. Each candidate must be a relative path (starts with ``/``).
    """
    match att:
        case {"downloadLink": str(s)} if s.startswith("/"):
            return s
        case {"_links": {"download": str(s)}} if s.startswith("/"):
            return s
        case _:
            return None


def _find_attachment_by_title(
    attachments: list[dict[str, Any]],
    filename: str,
) -> dict[str, Any] | None:
    """Return the first attachment whose ``title`` equals ``filename``."""
    for att in attachments:
        title_raw: Any = att.get("title")  # pyright: ignore[reportAny]
        if isinstance(title_raw, str) and title_raw == filename:
            return att
    return None


@dataclass(frozen=True)
class _OfficeLink:
    """One office attachment's download URL + filename, for the body callout."""

    url: str
    filename: str


@dataclass
class PublishOfficeSummary:
    """Result of a single publish_office run for one page.

    ``body_xhtml`` holds the updated storage XHTML after the body callout has
    been rebuilt; on early-return paths (no opt-in, managed-elsewhere, Quarto
    missing, frontmatter parse error) it is the input body unchanged.
    """

    page_id: str
    body_xhtml: str = ""
    formats_attempted: list[str] = field(default_factory=list)
    formats_uploaded: list[str] = field(default_factory=list)
    formats_cache_hit: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _emit_render_warnings(render_result: RenderResult) -> None:
    """Print up to the first five Quarto render warnings to stderr."""
    for w in render_result.warnings[:5]:
        log.warning("quarto: %s", w)


@dataclass
class _PublishAction:
    """Render + upload office attachments for one page (spec S17).

    The constructor takes the raw inputs from :func:`publish`. :meth:`execute`
    runs the full pipeline (read frontmatter, parse formats, managed/Quarto
    guards, per-format render + upload, body callout) and returns a
    :class:`PublishOfficeSummary` whose ``body_xhtml`` holds the updated body.
    One instance corresponds to one ``publish()`` call and must not be reused.
    """

    client: ConfluenceClient
    page_id: str
    md_path: Path
    body_xhtml: str
    template_dir: Path | None = None
    dry_run: bool = False
    managed_config: ManagedConfig | None = None
    _page_data: dict[str, Any] | None = None

    summary: PublishOfficeSummary = field(init=False)
    fm: _FrontMatter = field(init=False)
    body_md: str = field(init=False, default="")
    formats: list[str] = field(init=False, default_factory=list)
    qversion: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.summary = PublishOfficeSummary(page_id=self.page_id, body_xhtml=self.body_xhtml)
        self.fm = _FrontMatter({})

    @property
    def page_data(self) -> dict[str, Any]:
        """Page API response dict, fetched lazily; ``{}`` on fetch failure."""
        if self._page_data is None:
            try:
                self._page_data = self.client.get_page(self.page_id)
            except Exception:
                self._page_data = {}
        return self._page_data

    @cached_property
    def source_sha256(self) -> str:
        """SHA-256 of the source markdown bytes (computed once on first read)."""
        return _hash_bytes(self.md_path.read_bytes())

    def execute(self) -> PublishOfficeSummary:
        fm_dict, self.body_md = read_frontmatter(self.md_path)
        self.fm = _FrontMatter(fm_dict)
        if not self._record_formats():
            return self.summary
        if self._is_managed_elsewhere():
            return self.summary
        if not self._record_quarto_version():
            return self.summary
        self._render_all_formats()
        return self.summary

    def _record_formats(self) -> bool:
        """Parse ``publish_office`` from frontmatter; False if invalid or empty."""
        try:
            self.formats = self.fm.publish_formats()
        except ValueError as exc:
            self.summary.failures.append(f"bad publish_office value: {exc}")
            return False
        return bool(self.formats)

    def _record_quarto_version(self) -> bool:
        """Capture Quarto version; False (with failure recorded) if Quarto is missing."""
        try:
            self.qversion = quarto_version()
        except QuartoNotFoundError as exc:
            log.warning("publish_office skipped for page %s: %s", self.page_id, exc)
            self.summary.failures.append(f"quarto not found: {exc}")
            return False
        return True

    def _render_all_formats(self) -> None:
        """Run the per-format render loop and rebuild the body callout."""
        updated_body = strip_office_callout(self.body_xhtml)
        callout_links: list[_OfficeLink] = []
        for fmt in self.formats:
            link = self._publish_one_format(fmt)
            if link is not None:
                callout_links.append(link)
        if callout_links:
            updated_body = insert_office_callout(
                updated_body, [(link.url, link.filename) for link in callout_links]
            )
        self.summary.body_xhtml = updated_body

    def _is_managed_elsewhere(self) -> bool:
        """Return True when spec S26 says this page is managed elsewhere."""
        if self.managed_config is None:
            return False
        page_info = build_page_info_from_page_data(self.page_data, self.body_xhtml)
        classification = classify_page(page_info, self.managed_config, self.client)
        if not classification.is_managed:
            return False
        warn_managed(self.page_id, classification, context="publish_office")
        return True

    def _existing_attachment_names(self) -> set[str]:
        """Return the set of attachment filenames already on the page."""
        attachments = self.client.list_page_attachments(self.page_id)
        names: set[str] = set()
        for att in attachments:
            title_raw: Any = att.get("title")  # pyright: ignore[reportAny]
            if isinstance(title_raw, str) and title_raw:
                names.add(title_raw)
        return names

    def _upload_and_get_version(self, file_path: Path) -> int:
        """Upload *file_path* and return the new attachment version number."""
        result = self.client.upload_attachment(self.page_id, file_path)
        match result:
            case {"results": [{"version": {"number": int(n)}}, *_]}:
                return n
            case {"results": [{"version": int(n)}, *_]}:
                return n
            case _:
                return 1

    def _attachment_url(self, filename: str) -> str:
        """Build a stable URL for the attachment download link in the callout.

        Uses the v2 ``/wiki/api/v2/pages/{id}/attachments`` endpoint to find the
        ``downloadLink`` and converts it to an absolute URL.  Falls back to the
        v1-style ``_links.download`` for any old fixture data, and finally to a
        generic attachment listing URL on failure.
        """
        try:
            attachments = self.client.list_page_attachments(self.page_id)
        except Exception:
            attachments = []
        att = _find_attachment_by_title(attachments, filename)
        if att is not None:
            rel = _attachment_relative_link(att)
            if rel is not None:
                return self.client.base_url + rel
        return f"{self.client.base_url}/wiki/rest/api/content/{self.page_id}/child/attachment"

    def _resolve_reference_doc(self, fmt: str, ext: str) -> Path | None:
        """Return the reference template path or None (with failure recorded)."""
        if self.template_dir is not None:
            candidate = self.template_dir / f"reference{ext}"
            if candidate.exists():
                return candidate
            log.warning(
                "reference template not found at %s; using bundled default for %s",
                candidate,
                ext,
            )
        try:
            return bundled_reference_doc(ext)
        except FileNotFoundError as exc:
            self.summary.failures.append(f"{fmt}: {exc}")
            return None

    def _try_frontmatter_cache_hit(
        self,
        fmt: str,
        state: dict[str, Any],
        template_sha256: str,
    ) -> _OfficeLink | None:
        """Return the callout link when the frontmatter cache matches, else None."""
        if not _cache_hit(state, self.source_sha256, template_sha256, self.qversion):
            return None
        cached_filename: Any = state.get("attachment_filename")  # pyright: ignore[reportAny]
        if not (isinstance(cached_filename, str) and cached_filename):
            return None
        self.summary.formats_cache_hit.append(fmt)
        log.debug("cache-hit: publish_office %s for %s", fmt, self.md_path.name)
        return _OfficeLink(url=self._attachment_url(cached_filename), filename=cached_filename)

    def _dry_run_link(self, fmt: str, attachment_filename: str) -> _OfficeLink:
        """Record a dry-run upload and return the placeholder callout link."""
        log.info(
            "(dry-run) would render and upload %s to page %s",
            attachment_filename,
            self.page_id,
        )
        self.summary.formats_uploaded.append(fmt)
        page_url = f"{self.client.base_url}/wiki/pages/viewpage.action?pageId={self.page_id}"
        return _OfficeLink(url=page_url, filename=attachment_filename)

    def _write_state(self, fmt: str, state_entry: dict[str, Any]) -> None:
        """Update the per-format cache block in frontmatter and persist to disk."""
        self.fm.set_state(fmt, state_entry)
        write_frontmatter(self.md_path, self.fm.data, self.body_md)

    def _try_rendered_output_cache_hit(
        self,
        fmt: str,
        state: dict[str, Any],
        attachment_filename: str,
        rendered_sha256: str,
        template_sha256: str,
    ) -> _OfficeLink | None:
        """Return a callout link when the rendered bytes match the cached upload."""
        cached_att_sha: Any = state.get("attachment_sha256")  # pyright: ignore[reportAny]
        if not (isinstance(cached_att_sha, str) and cached_att_sha == rendered_sha256):
            return None
        self.summary.formats_cache_hit.append(fmt)
        log.debug("cache-hit: publish_office %s rendered output unchanged", fmt)
        prior_version_raw: Any = state.get("attachment_version", 1)  # pyright: ignore[reportAny]
        prior_version = prior_version_raw if isinstance(prior_version_raw, int) else 1
        self._write_state(
            fmt,
            {
                "source_sha256": self.source_sha256,
                "template_sha256": template_sha256,
                "quarto_version": self.qversion,
                "attachment_filename": attachment_filename,
                "attachment_sha256": rendered_sha256,
                "attachment_version": prior_version,
            },
        )
        return _OfficeLink(
            url=self._attachment_url(attachment_filename), filename=attachment_filename
        )

    def _raise_on_collision(self, state: dict[str, Any], attachment_filename: str) -> None:
        """Raise OfficePublishCollisionError if a non-mdd attachment owns this name."""
        cached_our_filename: Any = state.get("attachment_filename")  # pyright: ignore[reportAny]
        is_our_attachment = (
            isinstance(cached_our_filename, str) and cached_our_filename == attachment_filename
        )
        if is_our_attachment:
            return
        existing_names = self._existing_attachment_names()
        if attachment_filename in existing_names:
            raise OfficePublishCollisionError(
                f"Attachment {attachment_filename!r} already exists on page "
                f"{self.page_id} and was not uploaded by mdd. "
                "Rename the existing attachment in Confluence before syncing."
            )

    def _render_and_upload(
        self,
        fmt: str,
        ref_doc: Path,
        state: dict[str, Any],
        template_sha256: str,
        attachment_filename: str,
    ) -> _OfficeLink | None:
        """Render + upload one format. Returns the callout link, or None on failure."""
        renderer = QuartoDocxRenderer() if fmt == "docx" else QuartoPptxRenderer()
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / attachment_filename
            render_result = renderer.render(self.md_path, dest=dest, reference_doc=ref_doc)
            _emit_render_warnings(render_result)
            rendered_sha256 = _hash_file(dest)

            rendered_cache = self._try_rendered_output_cache_hit(
                fmt, state, attachment_filename, rendered_sha256, template_sha256
            )
            if rendered_cache is not None:
                return rendered_cache

            self._raise_on_collision(state, attachment_filename)

            try:
                version = self._upload_and_get_version(dest)
            except ConfluenceError as exc:
                self.summary.failures.append(f"{fmt}: upload failed: {exc}")
                return None

            self._write_state(
                fmt,
                {
                    "source_sha256": self.source_sha256,
                    "template_sha256": template_sha256,
                    "quarto_version": self.qversion,
                    "attachment_filename": attachment_filename,
                    "attachment_sha256": rendered_sha256,
                    "attachment_version": version,
                },
            )
            self.summary.formats_uploaded.append(fmt)
            log.info(
                "publish-office: %s -> page %s (v%d)",
                attachment_filename,
                self.page_id,
                version,
            )
            return _OfficeLink(
                url=self._attachment_url(attachment_filename), filename=attachment_filename
            )

    def _publish_one_format(self, fmt: str) -> _OfficeLink | None:
        """Run the full render/upload lifecycle for one format and return its callout link."""
        self.summary.formats_attempted.append(fmt)
        ext = f".{fmt}"

        ref_doc = self._resolve_reference_doc(fmt, ext)
        if ref_doc is None:
            return None

        template_sha256 = _hash_file(ref_doc)
        state = self.fm.state(fmt)

        fm_cache = self._try_frontmatter_cache_hit(fmt, state, template_sha256)
        if fm_cache is not None:
            return fm_cache

        attachment_filename = _attachment_name(self.md_path, fmt)

        if self.dry_run:
            return self._dry_run_link(fmt, attachment_filename)

        try:
            return self._render_and_upload(
                fmt, ref_doc, state, template_sha256, attachment_filename
            )
        except OfficePublishCollisionError:
            raise
        except Exception as exc:
            log.exception("publish_office %s for %s: %s", fmt, self.md_path.name, exc)
            self.summary.failures.append(f"{fmt}: {exc}")
            return None


def publish(  # noqa: PLR0913
    client: ConfluenceClient,
    page_id: str,
    md_path: Path,
    body_xhtml: str,
    *,
    template_dir: Path | None = None,
    dry_run: bool = False,
    managed_config: ManagedConfig | None = None,
    page_data: dict[str, Any] | None = None,
) -> PublishOfficeSummary:
    """Render and upload office attachments for one page.

    Args:
        client: Authenticated Confluence client.
        page_id: Confluence page ID.
        md_path: Path to the local Markdown file.
        body_xhtml: Current storage XHTML for the page body.
        template_dir: Override directory for reference templates.  When ``None``,
            bundled defaults are used.
        dry_run: If True, skip rendering and uploading; log what would happen.
        managed_config: When provided, classified via spec S26 before any write.
            If managed, returns immediately with an empty summary (skip).
        page_data: Pre-fetched page API response dict (used to build PageInfo when
            *managed_config* is provided without already-fetched data).

    Returns:
        ``PublishOfficeSummary`` for the run. The updated storage XHTML (with
        the body callout rebuilt) is on ``summary.body_xhtml``; on early-return
        paths it equals the input ``body_xhtml``.

    Notes:
        - Quarto absence is a hard warning (logged to stderr); the body is returned
          unchanged and the summary records a failure.
        - Per-format render/upload failures are recorded in the summary and do NOT
          propagate as exceptions (best-effort policy per spec S14).
        - OfficePublishCollisionError IS propagated so the caller can surface it.
    """
    return _PublishAction(
        client=client,
        page_id=page_id,
        md_path=md_path,
        body_xhtml=body_xhtml,
        template_dir=template_dir,
        dry_run=dry_run,
        managed_config=managed_config,
        _page_data=page_data,
    ).execute()
