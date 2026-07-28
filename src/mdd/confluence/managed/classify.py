"""Classify a Confluence page against the managed-elsewhere detection cascade."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ._api_coerce import dict_field, iter_dicts

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import ManagedConfig, PublisherEntry


class ManagedReason(StrEnum):
    READ_ONLY = "READ_ONLY"
    MANAGED_SPACE = "MANAGED_SPACE"
    MANAGED_SUBTREE = "MANAGED_SUBTREE"
    PUBLISHER_ACCOUNT_MATCH = "PUBLISHER_ACCOUNT_MATCH"
    BODY_MARKER = "BODY_MARKER"


@dataclass(frozen=True)
class ManagedClassification:
    """Result of classifying a Confluence page."""

    is_managed: bool
    reason: ManagedReason | None = None
    publisher_name: str | None = None  # None for READ_ONLY
    source_url: str | None = None
    message: str | None = None  # rendered with substitutions


@dataclass
class PageInfo:
    """Minimal page data needed for the classify cascade."""

    page_id: str
    space_key: str
    ancestor_ids: list[str]  # ordered root-to-parent, excluding self
    version_author_id: str  # account ID of the last version's author
    body_storage: str  # full storage XHTML body


def _render_message(message: str, publisher: PublisherEntry) -> str:
    return message.format(
        source_url=publisher.source_url,
        publisher_name=publisher.name,
    )


def _hit_publisher(
    reason: ManagedReason,
    publisher: PublisherEntry,
) -> ManagedClassification:
    msg = _render_message(publisher.message, publisher) if publisher.message else None
    return ManagedClassification(
        is_managed=True,
        reason=reason,
        publisher_name=publisher.name,
        source_url=publisher.source_url or None,
        message=msg,
    )


def _hit_read_only() -> ManagedClassification:
    return ManagedClassification(
        is_managed=True,
        reason=ManagedReason.READ_ONLY,
        publisher_name=None,
        source_url=None,
        message="This page is read-only for the current Confluence user.",
    )


def _not_managed() -> ManagedClassification:
    return ManagedClassification(is_managed=False)


def _user_can_update(
    page_id: str,
    current_account_id: str,
    client: Any,  # ConfluenceClient — avoid circular import
) -> bool:
    """Return True if the current user is allowed to update *page_id*.

    Calls ``GET /wiki/rest/api/content/{id}/restriction``.  If the "update"
    restriction type has an empty ``restrictions`` block, the page is
    unrestricted (everyone can update) → returns True.

    If the list is non-empty, returns True only if *current_account_id* is in
    the user list or is a member of one of the groups.

    On any API error, returns True (fail-open for the restriction check; other
    cascade layers are stronger).
    """
    try:
        data = client.get_page_restrictions(page_id)
    except Exception:
        return True  # can't tell — assume allowed

    # Shape: {"update": {"restrictions": {"user": {"results": [...]}, "group": {...}}}}
    restrictions = dict_field(dict_field(data, "update"), "restrictions")
    user_results = iter_dicts(dict_field(restrictions, "user"), "results")
    group_results = iter_dicts(dict_field(restrictions, "group"), "results")

    if not user_results and not group_results:
        return True  # unrestricted

    # Groups: we don't enumerate group membership via the API (too expensive).
    # If there are group restrictions but no user restriction for the current
    # account, conservatively treat as restricted.
    return any(entry.get("accountId") == current_account_id for entry in user_results)


def _publisher_cascade(page: PageInfo, config: ManagedConfig) -> ManagedClassification | None:
    """Run layers 1-4 of the cascade (publisher-driven). Return the first hit or None.

    The four layers are a priority-ordered tuple of ``(reason, lookup)`` pairs so
    the order is data, not a copy-pasted if-chain, and adding a new publisher
    source is a one-line tuple entry. Lookups are callables so the cascade
    short-circuits — body-marker regex scan does not run if an earlier layer hit.
    """
    layers: tuple[tuple[ManagedReason, Callable[[], PublisherEntry | None]], ...] = (
        (ManagedReason.MANAGED_SPACE, lambda: config.publisher_for_space(page.space_key)),
        (ManagedReason.MANAGED_SUBTREE, lambda: config.publisher_for_subtree(page.ancestor_ids)),
        (
            ManagedReason.PUBLISHER_ACCOUNT_MATCH,
            lambda: (
                config.publisher_for_account(page.version_author_id)
                if page.version_author_id
                else None
            ),
        ),
        (ManagedReason.BODY_MARKER, lambda: config.publisher_for_body(page.body_storage)),
    )
    for reason, lookup in layers:
        pub = lookup()
        if pub is not None:
            return _hit_publisher(reason, pub)
    return None


def _resolve_account_id(client: Any, current_account_id: str | None) -> str:
    """Return the caller-provided account ID, or fetch it from the client (fail-empty)."""
    if current_account_id is not None:
        return current_account_id
    try:
        user_data = client.get_current_user()
        aid_raw: Any = user_data.get("accountId", "")  # pyright: ignore[reportAny]
        return str(aid_raw) if isinstance(aid_raw, str) else ""
    except Exception:
        return ""


def classify_page(
    page: PageInfo,
    config: ManagedConfig,
    client: Any,  # ConfluenceClient — avoid circular import
    *,
    current_account_id: str | None = None,
    check_restrictions: bool = True,
) -> ManagedClassification:
    """Classify a Confluence page against the managed-elsewhere detection cascade.

    Evaluates layers in priority order and returns on the first match:

    1. managed_spaces    → MANAGED_SPACE
    2. managed_subtrees  → MANAGED_SUBTREE
    3. account_ids       → PUBLISHER_ACCOUNT_MATCH
    4. body_marker_patterns → BODY_MARKER
    5. page_restrictions → READ_ONLY  (only when *check_restrictions* is True)

    Args:
        page:               Minimal page data required for classification.
        config:             Merged ManagedConfig (from :func:`load_managed_config`).
        client:             Authenticated ConfluenceClient.
        current_account_id: The currently-authenticated account ID.  Required for
                            the page-restrictions check.  Fetched lazily when needed.
        check_restrictions: If False, layer 5 is skipped (saves an API call).

    Returns:
        :class:`ManagedClassification`
    """
    hit = _publisher_cascade(page, config)
    if hit is not None:
        return hit

    if check_restrictions:
        account_id = _resolve_account_id(client, current_account_id)
        if account_id and not _user_can_update(page.page_id, account_id, client):
            return _hit_read_only()

    return _not_managed()
