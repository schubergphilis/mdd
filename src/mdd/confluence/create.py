"""Create a new Confluence page from a local Markdown file (spec 009d).

Two-phase create
----------------
Confluence has no "create with attachments in one shot" endpoint, so we use
a two-step sequence:

1. POST a stub page with a marker title ``"<title> (creating…)"`` and an
   empty body.  This gives us the ``page_id`` we need before uploading
   attachments.
2. Upload any locally-referenced image files as attachments to that page_id.
3. Render the markdown body to storage XHTML.
4. PUT the final title + body as version 2.

If step 4 fails, the stub page is left on Confluence with the ``(creating…)``
marker in its title.  Recovery: fix whatever caused the error, then run
``mdd confluence update page <file>`` — the frontmatter will already contain
the page_id written after step 1, so the update path will finish the job.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pydantic import ValidationError

from mdd.confluence.attachments import (
    AttachmentCollisionError,
    AttachmentManifestEntry,
    sync_attachments_for_update,
)
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.header import get_mirror_url, insert_mdd_footer, strip_export_header
from mdd.confluence.ir import render_confluence_storage
from mdd.confluence.models import ConfluenceBlock, ConfluenceV2PageMinimal
from mdd.confluence.url import parse as parse_url
from mdd.markdown.ir import parse_markdown
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.config import ConfluenceConfig

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


def _extract_h1(body_md: str) -> str | None:
    """Return the text of the first ATX H1 heading found in body_md, or None."""
    m = _H1_RE.search(body_md)
    return m.group(1).strip() if m else None


def _conf_block_from_fm(fm: dict[str, Any]) -> ConfluenceBlock | None:
    """Validate ``fm['confluence']`` into a typed block, or ``None`` if absent/invalid.

    A ``ValidationError`` becomes ``None`` (treated as "no usable
    metadata") with a log warning — the caller decides whether to
    proceed.  This mirrors today's behaviour for create-page, which
    silently fell through on bad frontmatter and then errored on the
    missing-space-key check.
    """
    raw: object = fm.get("confluence")
    if raw is None:
        return None
    try:
        return ConfluenceBlock.model_validate(raw)
    except ValidationError as exc:
        log.warning("invalid confluence frontmatter: %s", exc)
        return None


def _resolve_user(client: ConfluenceClient, account_id: str) -> str:
    try:
        user = client.get_user(account_id)
    except ConfluenceError as exc:
        log.warning("could not resolve display name for account %r: %s", account_id, exc)
        return ""
    dn: object = user.get("displayName", "")
    return str(dn) if isinstance(dn, str) and dn else ""


def _extract_page_meta(page: dict[str, Any], exported_at: str) -> dict[str, Any]:
    """Pull commonly-needed scalar fields out of a Confluence page API response."""
    parsed = ConfluenceV2PageMinimal.model_validate(page)
    version = parsed.version
    return {
        "page_id": parsed.id,
        "title": parsed.title,
        "status": parsed.status or "current",
        "space_id": parsed.space_id,
        "parent_id": parsed.parent_id or None,
        "version_num": version.number if version is not None else 1,
        "version_author_id": (version.author_id if version is not None else None) or None,
        "version_created_at": (version.created_at if version is not None else None) or exported_at,
        "webui_url": parsed.links.webui if parsed.links is not None else "",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class _CreateAbort(Exception):
    """Internal sentinel: a sub-step has decided to terminate ``create_page``."""

    def __init__(self, rc: int) -> None:
        super().__init__(f"create_page abort rc={rc}")
        self.rc = rc


@dataclass(frozen=True)
class _CliFlags:
    """The three optional CLI flags that can override frontmatter values."""

    space_key: str | None
    parent: str | None
    title: str | None


@dataclass(frozen=True)
class _CreateInputs:
    """Resolved CLI/frontmatter inputs needed to drive create_page."""

    space_key: str
    title: str
    parent_id: str | None


def _resolve_space_key(cli_space: str | None, block: ConfluenceBlock | None) -> str:
    """Return the explicit ``--space`` or the frontmatter ``confluence.space_key``."""
    if cli_space:
        return cli_space
    if block is not None and block.space_key:
        return block.space_key
    log.error(
        "no space key provided. Use --space or add 'confluence.space_key' to frontmatter.",
    )
    raise _CreateAbort(1)


def _resolve_title(cli_title: str | None, body_md: str, md_path: Path) -> str:
    """Return ``--title`` flag, the first H1 in the body, or the filename stem."""
    if cli_title:
        return cli_title
    return _extract_h1(body_md) or md_path.stem


def _resolve_parent_id(
    parent: str | None,
    block: ConfluenceBlock | None,
    config: ConfluenceConfig,
) -> str | None:
    """Resolve the ``--parent`` flag (numeric/URL) or fall back to frontmatter."""
    if parent:
        if parent.isdigit():
            return parent
        config_host = urlparse(config.url).hostname or None
        try:
            page_ref = parse_url(parent, expected_host=config_host)
        except ValueError as exc:
            log.error("invalid parent reference: %s", exc)
            raise _CreateAbort(1) from exc
        return page_ref.page_id or None
    return block.parent_id if block is not None and block.parent_id else None


def _validate_idempotency(md_path: Path, block: ConfluenceBlock | None) -> None:
    """Refuse to create a page when ``confluence.page_id`` already exists."""
    if block is not None and block.page_id:
        log.error(
            "%s already has 'confluence.page_id' in frontmatter (%r). "
            "Use 'mdd confluence update page' to push changes to an existing page.",
            md_path,
            block.page_id,
        )
        raise _CreateAbort(1)


def _resolve_inputs(
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    config: ConfluenceConfig,
    flags: _CliFlags,
) -> _CreateInputs:
    """Validate idempotency and gather the three CLI-vs-frontmatter inputs."""
    block = _conf_block_from_fm(frontmatter)
    _validate_idempotency(md_path, block)
    return _CreateInputs(
        space_key=_resolve_space_key(flags.space_key, block),
        title=_resolve_title(flags.title, body_md, md_path),
        parent_id=_resolve_parent_id(flags.parent, block, config),
    )


def _fetch_space_id(client: ConfluenceClient, space_key: str) -> str:
    """Look up the space id for *space_key*, aborting with rc=1 on any failure."""
    try:
        space_data = client.get_space(space_key)
    except ConfluenceError as exc:
        log.error("Confluence API: %s", exc)
        raise _CreateAbort(1) from exc
    space_id = ConfluenceV2PageMinimal.model_validate(space_data).id
    if not space_id:
        log.error("could not determine space ID for space key %r.", space_key)
        raise _CreateAbort(1)
    return space_id


def _build_stub_url(
    stub_page: dict[str, Any],
    config: ConfluenceConfig,
    space_key: str,
    page_id: str,
) -> str:
    """Best-effort canonical URL from the stub-page POST response."""
    parsed = ConfluenceV2PageMinimal.model_validate(stub_page)
    stub_webui = parsed.links.webui if parsed.links is not None else ""
    if stub_webui.startswith("http"):
        return stub_webui
    if stub_webui:
        return f"{config.url}{stub_webui}"
    return f"{config.url}/wiki/spaces/{space_key}/pages/{page_id}"


def _post_stub_page(
    client: ConfluenceClient,
    *,
    space_id: str,
    space_key: str,
    parent_id: str | None,
    title: str,
    config: ConfluenceConfig,
) -> tuple[str, str]:
    """POST the stub page and return ``(page_id, stub_url)``."""
    stub_title = f"{title} (creating…)"
    try:
        stub_page = client.post_page(
            space_id=space_id,
            parent_id=parent_id,
            title=stub_title,
            body="",
        )
    except ConfluenceError as exc:
        log.error("Confluence API - POST stub: %s", exc)
        raise _CreateAbort(1) from exc
    page_id = ConfluenceV2PageMinimal.model_validate(stub_page).id
    if not page_id:
        log.error("POST stub page did not return a page ID.")
        raise _CreateAbort(1)
    return page_id, _build_stub_url(stub_page, config, space_key, page_id)


def _abort_with_recovery_hint(reason: str, page_id: str) -> None:
    """Print the standard ``stub page created, run update`` recovery message."""
    log.error(
        "%s. A stub page was created with ID %r. "
        "The frontmatter has been updated with the page_id so you can run "
        "'mdd confluence update page' to finish.",
        reason,
        page_id,
    )


def _sync_attachments(
    client: ConfluenceClient,
    page_id: str,
    body_stripped: str,
    md_path: Path,
) -> tuple[list[AttachmentManifestEntry], str]:
    """Upload locally-referenced images to the stub page, aborting with rc=1 on failure."""
    try:
        return sync_attachments_for_update(
            client,
            page_id,
            body_stripped,
            md_path.parent,
            [],
        )
    except (ConfluenceError, AttachmentCollisionError, OSError) as exc:
        _abort_with_recovery_hint(f"attachment sync: {exc}", page_id)
        raise _CreateAbort(1) from exc


def _render_create_xhtml(body_stripped: str, md_path: Path, page_id: str) -> str:
    """Render the local markdown to storage XHTML and append the MDD footer."""
    try:
        body_xhtml = render_confluence_storage(parse_markdown(body_stripped))
    except (ValueError, KeyError) as exc:
        _abort_with_recovery_hint(f"markdown conversion: {exc}", page_id)
        raise _CreateAbort(1) from exc
    return insert_mdd_footer(body_xhtml, get_mirror_url(md_path))


def _put_final_create(
    client: ConfluenceClient,
    page_id: str,
    title: str,
    body_xhtml: str,
    message: str,
) -> dict[str, Any]:
    """PUT the final page body as version 2, mapping API errors to rc=1."""
    try:
        return client.put_page(page_id, title, body_xhtml, version=2, message=message)
    except ConfluenceError as exc:
        _abort_with_recovery_hint(f"Confluence API — PUT final body: {exc}", page_id)
        raise _CreateAbort(1) from exc


def _final_conf_block(  # noqa: PLR0913 — every field belongs in the frontmatter block
    final_page: dict[str, Any],
    config: ConfluenceConfig,
    inputs: _CreateInputs,
    space_id: str,
    updated_manifest: list[AttachmentManifestEntry],
    *,
    exported_at: str,
    updated_by: str,
) -> tuple[dict[str, Any], str]:
    """Build the final ``confluence:`` frontmatter block and return ``(block, page_url)``."""
    meta = _extract_page_meta(final_page, exported_at)
    webui = meta["webui_url"]
    if webui:
        page_url = webui if webui.startswith("http") else f"{config.url}{webui}"
    else:
        page_url = f"{config.url}/wiki/spaces/{inputs.space_key}/pages/{meta['page_id']}"

    attachments_list = [
        {"filename": e.filename, "sha256": e.sha256, "version": e.version} for e in updated_manifest
    ]
    conf_block: dict[str, Any] = {
        "url": page_url,
        "page_id": meta["page_id"],
        "space_key": inputs.space_key,
        "space_id": meta["space_id"] or space_id,
        "parent_id": meta["parent_id"],
        "status": meta["status"],
        "version": meta["version_num"],
        "updated_at": meta["version_created_at"],
        "updated_by": updated_by,
        "exported_at": exported_at,
    }
    if attachments_list:
        conf_block["attachments"] = attachments_list
    return conf_block, page_url


def _run_create(  # noqa: PLR0913 — keyword-only orchestration call, all args are required
    client: ConfluenceClient,
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    config: ConfluenceConfig,
    inputs: _CreateInputs,
    message: str,
) -> str:
    """Run the post-input-resolution lifecycle and return the final page URL."""
    space_id = _fetch_space_id(client, inputs.space_key)
    page_id, stub_url = _post_stub_page(
        client,
        space_id=space_id,
        space_key=inputs.space_key,
        parent_id=inputs.parent_id,
        title=inputs.title,
        config=config,
    )

    # Write partial frontmatter so a downstream failure leaves a recoverable record.
    _write_partial_frontmatter(
        md_path,
        frontmatter,
        body_md,
        page_id=page_id,
        space_key=inputs.space_key,
        space_id=space_id,
        parent_id=inputs.parent_id,
        exported_at=datetime.now(UTC).isoformat(),
        url=stub_url,
    )

    body_stripped = strip_export_header(body_md)
    updated_manifest, body_stripped = _sync_attachments(client, page_id, body_stripped, md_path)

    # Refresh partial frontmatter now that we have the attachment manifest.
    _write_partial_frontmatter(
        md_path,
        frontmatter,
        body_md,
        page_id=page_id,
        space_key=inputs.space_key,
        space_id=space_id,
        parent_id=inputs.parent_id,
        exported_at=datetime.now(UTC).isoformat(),
        url=stub_url,
        attachments=[
            {"filename": e.filename, "sha256": e.sha256, "version": e.version}
            for e in updated_manifest
        ],
    )

    body_xhtml = _render_create_xhtml(body_stripped, md_path, page_id)
    final_page = _put_final_create(client, page_id, inputs.title, body_xhtml, message)

    exported_at = datetime.now(UTC).isoformat()
    meta = _extract_page_meta(final_page, exported_at)
    version_author_id = meta["version_author_id"]
    updated_by = _resolve_user(client, version_author_id) if version_author_id else ""

    conf_block, page_url = _final_conf_block(
        final_page,
        config,
        inputs,
        space_id,
        updated_manifest,
        exported_at=exported_at,
        updated_by=updated_by,
    )
    frontmatter["confluence"] = conf_block
    write_frontmatter(md_path, frontmatter, body_md)
    return page_url


def create_page(
    md_path: Path,
    config: ConfluenceConfig,
    *,
    space_key: str | None = None,
    parent: str | None = None,
    title: str | None = None,
    message: str = "Created via mdd",
) -> int:
    """Create a new Confluence page from a local Markdown file.

    Args:
        md_path:   Path to the local ``.md`` file.
        config:    Resolved Confluence connection config.
        space_key: Target space key.  Falls back to ``confluence.space_key``
                   in frontmatter, then errors.
        parent:    Parent page — numeric ID or Confluence page URL.
                   Falls back to ``confluence.parent_id`` in frontmatter,
                   then defaults to ``None`` (space root).
        title:     Page title.  Falls back to ``confluence.title`` in
                   frontmatter, then the first H1 in the body, then errors.
        message:   Version comment stored in Confluence page history.

    Returns:
        0 on success, 1 on error.
    """
    try:
        frontmatter, body_md = read_frontmatter(md_path)
    except OSError as exc:
        log.error("reading %s: %s", md_path, exc)
        return 1

    try:
        inputs = _resolve_inputs(
            md_path,
            frontmatter,
            body_md,
            config,
            _CliFlags(space_key=space_key, parent=parent, title=title),
        )
    except _CreateAbort as abort:
        return abort.rc

    def token_resolver() -> str:
        return config.api_token

    try:
        with ConfluenceClient(config.url, config.username, token_resolver) as client:
            page_url = _run_create(client, md_path, frontmatter, body_md, config, inputs, message)
    except _CreateAbort as abort:
        return abort.rc

    log.info("Created: %s", page_url)
    return 0


def _write_partial_frontmatter(  # noqa: PLR0913
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    *,
    page_id: str,
    space_key: str,
    space_id: str,
    parent_id: str | None,
    exported_at: str,
    url: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Write a partial frontmatter so update page can recover from a failed create.

    Includes ``url`` (so update can link back without an extra GET) and the
    attachment manifest uploaded so far (so update does not re-upload them).
    """
    conf_block: dict[str, Any] = {
        "url": url,
        "page_id": page_id,
        "space_key": space_key,
        "space_id": space_id,
        "parent_id": parent_id,
        "status": "current",
        "version": 1,
        "exported_at": exported_at,
    }
    if attachments:
        conf_block["attachments"] = attachments
    frontmatter["confluence"] = conf_block
    with contextlib.suppress(OSError):
        write_frontmatter(md_path, frontmatter, body_md)
