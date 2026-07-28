"""whoami — print current Confluence user and compare against external publishers (spec S26)."""

from __future__ import annotations

from typing import Any

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.managed import ManagedConfig, PublisherEntry, load_managed_config
from mdd.utils.logging import get_logger

log = get_logger(__name__)


def _get_str(data: dict[str, Any], key: str) -> str:
    """Return ``data[key]`` if it is a string, otherwise the empty string."""
    raw: Any = data.get(key, "")  # pyright: ignore[reportAny]
    return raw if isinstance(raw, str) else ""


def _format_publisher_lines(
    publishers: list[PublisherEntry],
    account_id: str,
) -> list[str]:
    """Render publisher entries as printable lines, marking matches against ``account_id``."""
    lines: list[str] = []
    for pub in publishers:
        if not pub.account_ids:
            lines.append(f"  {pub.name:<30s} (no account IDs configured)")
            continue
        for aid in pub.account_ids:
            match_label = "match!" if aid == account_id else "(no match)"
            lines.append(f"  {pub.name:<30s} accountId {aid}    {match_label}")
    return lines


def cmd_whoami(
    client: ConfluenceClient,
    config: ManagedConfig | None = None,
) -> int:
    """Print the current user and compare against configured external publishers.

    Args:
        client: Authenticated ConfluenceClient.
        config: Pre-loaded ManagedConfig.  When None, loaded via
                :func:`~mdd.confluence.managed.load_managed_config`.

    Returns:
        0 on success, 1 on API error.
    """
    try:
        me: dict[str, Any] = client.get_current_user()
    except ConfluenceError as exc:
        log.error("Confluence API: %s", exc)
        return 1

    account_id = _get_str(me, "accountId")
    display_name = _get_str(me, "displayName")

    log.info("You are authenticated as:")
    log.info("  accountId:   %s", account_id)
    log.info("  displayName: %s", display_name)

    if config is None:
        config = load_managed_config()

    if not config.external_publishers:
        log.info("No external publishers configured.")
        return 0

    log.info("Configured external publishers:")
    for line in _format_publisher_lines(config.external_publishers, account_id):
        log.info("%s", line)

    return 0
