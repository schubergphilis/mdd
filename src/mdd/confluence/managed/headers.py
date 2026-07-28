"""Pull-side helpers for managed pages: header callout, PageInfo builder, warn."""

from __future__ import annotations

from typing import Any

from mdd.utils.logging import get_logger

from ._api_coerce import dict_field, iter_dicts, str_field
from .classify import ManagedClassification, PageInfo

log = get_logger(__name__)


def managed_export_header(
    classification: ManagedClassification,
    export_date: str,
) -> str:
    """Build the managed-aware export header callout for pull-side stamping.

    Used by export.py / sync.py when stamping managed pages.

    Args:
        classification: The result of :func:`classify_page`.
        export_date: ``YYYY-MM-DD`` string.

    Returns:
        Markdown blockquote string (with trailing newline).
    """
    publisher_name = classification.publisher_name or "unknown publisher"
    source_url = classification.source_url or ""

    if source_url:
        source_line = f"> This page is published from\n> <{source_url}>."
    else:
        source_line = f"> This page is managed by {publisher_name}."

    return (
        f"> **Confluence export (managed by {publisher_name})**\n"
        f">\n"
        f"{source_line}\n"
        f"> Edit there; this mirror is read-only.\n"
        f"> Exported on {export_date}.\n"
    )


def _extract_ancestor_ids(page_data: dict[str, Any]) -> list[str]:
    """Return the ancestor-id chain from the API response.

    Prefers the ``ancestors`` list (set when the caller passed
    ``include-ancestors``); falls back to a single-element list built from
    ``parentId`` when ancestors is absent.
    """
    ancestor_ids = [
        aid for aid in (str_field(anc, "id") for anc in iter_dicts(page_data, "ancestors")) if aid
    ]
    if ancestor_ids:
        return ancestor_ids
    parent = str_field(page_data, "parentId")
    return [parent] if parent else []


def build_page_info_from_page_data(
    page_data: dict[str, Any],
    body_storage: str,
) -> PageInfo:
    """Build a :class:`PageInfo` from a Confluence API page dict.

    Used by export.py and sync.py to construct the input for :func:`classify_page`.
    """
    return PageInfo(
        page_id=str_field(page_data, "id"),
        space_key=str_field(page_data, "spaceKey"),
        ancestor_ids=_extract_ancestor_ids(page_data),
        version_author_id=str_field(dict_field(page_data, "version"), "authorId"),
        body_storage=body_storage,
    )


def warn_managed(
    page_id: str,
    classification: ManagedClassification,
    context: str = "",
) -> None:
    """Print a managed-page warning to stderr."""
    label = context + " " if context else ""
    reason = classification.reason.value if classification.reason else "unknown"
    publisher = classification.publisher_name or "unknown"
    log.warning(
        "managed: %spage %s is managed by %r (reason: %s); skipping push.",
        label,
        page_id,
        publisher,
        reason,
    )
