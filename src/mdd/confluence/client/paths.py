"""Path validation and attachment-download URL construction."""

from __future__ import annotations

from typing import Any

from .errors import ConfluenceError


def assert_relative_api_path(path: str, label: str) -> None:
    """Raise ConfluenceError if *path* is not a relative URL path.

    API-supplied pagination/download paths must be relative (start with ``/``)
    and must not contain a scheme (``://``).  Accepting absolute foreign URLs
    would forward auth credentials to an unintended host (SSRF).
    """
    if "://" in path or not path.startswith("/"):
        raise ConfluenceError(f"{label} returned a non-relative URL {path!r}; refusing to follow")


def rest_attachment_download_path(attachment: dict[str, Any]) -> str:
    """Build the REST attachment download URL from a v2 attachment dict.

    Returns the path ``/wiki/rest/api/content/{page_id}/child/attachment/{att_id}/download``.

    This endpoint accepts Basic auth + API token even on tenants where
    Atlassian has gated the legacy ``/wiki/download/attachments/...`` path
    to OAuth-only (see Atlassian's 19-Nov-2025 changelog removing several
    ``/download/attachments/`` internal API paths).  It
    302-redirects to a CDN URL carrying a short-lived signed JWT, which
    httpx follows transparently when ``follow_redirects=True``.

    Requires both ``pageId`` and ``id`` to be present on the attachment
    dict — both are top-level fields on every v2 listing result.
    """
    pid_raw: Any = attachment.get("pageId")  # pyright: ignore[reportAny]
    aid_raw: Any = attachment.get("id")  # pyright: ignore[reportAny]
    page_id = pid_raw if isinstance(pid_raw, str) and pid_raw else None
    att_id = aid_raw if isinstance(aid_raw, str) and aid_raw else None
    if page_id is None or att_id is None:
        title_raw: Any = attachment.get("title", "")  # pyright: ignore[reportAny]
        title = title_raw if isinstance(title_raw, str) and title_raw else "<unknown>"
        raise ConfluenceError(
            f"Cannot build attachment download URL for {title!r}: "
            f"v2 attachment dict must carry both 'pageId' and 'id' "
            f"(got pageId={page_id!r}, id={att_id!r})"
        )
    # Validate against path traversal — both IDs go directly into the URL.
    if not page_id.isalnum() or not att_id.isalnum():
        raise ConfluenceError(
            f"Refusing to build attachment download URL with non-alphanumeric "
            f"identifiers (pageId={page_id!r}, id={att_id!r})"
        )
    return f"/wiki/rest/api/content/{page_id}/child/attachment/{att_id}/download"
