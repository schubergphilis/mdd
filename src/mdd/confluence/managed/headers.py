"""Pull-side helpers for managed pages: header callout, PageInfo builder, warn."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mdd.confluence.client.errors import ConfluenceError
from mdd.confluence.remote_space import remote_space_key, space_key_from_payload
from mdd.utils.logging import get_logger

from ._api_coerce import dict_field, iter_dicts, str_field
from .classify import ManagedClassification, PageInfo

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient

    from .config import ManagedConfig

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
    """Build a :class:`PageInfo` from a Confluence API page dict, without API calls.

    The space key comes from ``spaceKey`` or ``_links.webui``; the ancestor
    chain from ``ancestors`` or, failing that, ``parentId`` alone. A v2
    ``GET /pages/{id}`` payload has no ancestor chain, so use
    :func:`resolve_page_info` wherever the result gates a push.
    """
    return PageInfo(
        page_id=str_field(page_data, "id"),
        space_key=space_key_from_payload(page_data),
        ancestor_ids=_extract_ancestor_ids(page_data),
        version_author_id=str_field(dict_field(page_data, "version"), "authorId"),
        body_storage=body_storage,
    )


class ManagedCheckError(ConfluenceError):
    """The page data the managed-elsewhere check needs could not be fetched."""


def _resolve_space_key(client: ConfluenceClient, page_data: dict[str, Any], page_id: str) -> str:
    """Return the page's space key, raising :class:`ManagedCheckError` when unknown."""
    try:
        space_key = remote_space_key(client, page_data)
    except ConfluenceError as exc:
        raise ManagedCheckError(
            f"could not look up the space of page {page_id} to check managed_spaces: {exc}"
        ) from exc
    if not space_key:
        raise ManagedCheckError(
            f"could not tell which space page {page_id} is in to check managed_spaces"
        )
    return space_key


def _resolve_ancestor_ids(
    client: ConfluenceClient, page_id: str, parent_ids: list[str]
) -> list[str]:
    """Return the full ancestor chain, raising :class:`ManagedCheckError` on failure."""
    try:
        ancestors = client.get_page_ancestors(page_id)
    except ConfluenceError as exc:
        raise ManagedCheckError(
            f"could not fetch the ancestors of page {page_id} to check managed_subtrees: {exc}"
        ) from exc
    ancestor_ids = [aid for aid in (str_field(anc, "id") for anc in ancestors) if aid]
    # Keep the direct parent from the page payload even if the chain omits it.
    ancestor_ids.extend(pid for pid in parent_ids if pid not in ancestor_ids)
    return ancestor_ids


def resolve_page_info(
    client: ConfluenceClient,
    page_data: dict[str, Any],
    body_storage: str,
    config: ManagedConfig,
) -> PageInfo:
    """Build a :class:`PageInfo` complete enough for *config*'s space and subtree rules.

    Looks the space up by id when ``managed_spaces`` is configured and the
    payload does not name the key, and fetches the full ancestor chain when
    ``managed_subtrees`` is configured and the direct parent is not already
    a configured root. Without those rules no extra call is made.

    Raises:
        ManagedCheckError: A lookup the configured rules need failed. Push
            paths treat this as a refusal: an unchecked page is not pushed.
    """
    info = build_page_info_from_page_data(page_data, body_storage)
    if config.managed_spaces and not info.space_key:
        info = replace(info, space_key=_resolve_space_key(client, page_data, info.page_id))
    if config.managed_subtrees and config.publisher_for_subtree(info.ancestor_ids) is None:
        info = replace(
            info, ancestor_ids=_resolve_ancestor_ids(client, info.page_id, info.ancestor_ids)
        )
    return info


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
