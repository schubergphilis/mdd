"""Which space a Confluence page is in, as Confluence reports it.

The v2 page payload (``GET /wiki/api/v2/pages/{id}``) carries ``spaceId``
and ``_links.webui`` but no ``spaceKey``. The helpers here read the key
from the payload when they can and otherwise look the space up by id.
Frontmatter is never consulted: these answer "where is the page on
Confluence", which is what a confirmation prompt or a scope check needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from mdd.confluence.client.errors import ConfluenceError
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.confluence.client import ConfluenceClient

log = get_logger(__name__)

UNKNOWN_SPACE = "unknown"


def _str_field(data: dict[str, Any], key: str) -> str:
    value: Any = data.get(key)  # pyright: ignore[reportAny]
    return value if isinstance(value, str) else ""


def _webui_path(page_data: dict[str, Any]) -> str:
    links: Any = page_data.get("_links")  # pyright: ignore[reportAny]
    if not isinstance(links, dict):
        return ""
    links_dict: dict[str, Any] = links  # pyright: ignore[reportUnknownVariableType]
    return _str_field(links_dict, "webui")


def space_key_from_payload(page_data: dict[str, Any]) -> str:
    """Return the page's space key from the payload alone, or ``""``.

    Uses ``spaceKey`` when present, else the ``<KEY>`` segment of a
    ``_links.webui`` path shaped ``/spaces/<KEY>/...`` or
    ``/wiki/spaces/<KEY>/...`` (percent-decoded, so a personal space
    linked as ``%7Euser`` reads as ``~user``). Makes no API call.
    """
    space_key = _str_field(page_data, "spaceKey")
    if space_key:
        return space_key
    parts = [p for p in _webui_path(page_data).split("/") if p]
    try:
        idx = parts.index("spaces")
    except ValueError:
        return ""
    if idx + 1 < len(parts):
        return unquote(parts[idx + 1])
    return ""


def remote_space_key(client: ConfluenceClient, page_data: dict[str, Any]) -> str:
    """Return the page's space key, looking the space up by ``spaceId`` if needed.

    Returns ``""`` when the payload names neither a key nor a space id.

    Raises:
        ConfluenceError: The space id is not a valid identifier, or the
            space lookup failed.
    """
    space_key = space_key_from_payload(page_data)
    if space_key:
        return space_key
    space_id = _str_field(page_data, "spaceId")
    if not space_id:
        return ""
    space = client.get_space_by_id(space_id)
    return _str_field(space, "key")


@dataclass(frozen=True)
class RemotePage:
    """A page as Confluence reports it: id, title and space."""

    page_id: str
    title: str
    space_id: str
    space_key: str
    """``""`` when the space could not be resolved."""

    @property
    def space_label(self) -> str:
        """The space key, or ``unknown`` when it could not be resolved."""
        return self.space_key or UNKNOWN_SPACE


def describe_remote_page(client: ConfluenceClient, page_data: dict[str, Any]) -> RemotePage:
    """Build a :class:`RemotePage` from a v2 page payload.

    A failed space lookup is logged and leaves the key empty, so the
    caller shows ``unknown`` rather than guessing from local data.
    """
    page_id = _str_field(page_data, "id")
    try:
        space_key = remote_space_key(client, page_data)
    except ConfluenceError as exc:
        log.warning("could not look up the space of page %s: %s", page_id, exc)
        space_key = ""
    return RemotePage(
        page_id=page_id,
        title=_str_field(page_data, "title"),
        space_id=_str_field(page_data, "spaceId"),
        space_key=space_key,
    )


def _spaces_differ(remote: RemotePage, *, local_space_key: str, local_space_id: str) -> bool:
    """True when the remote and local space are known to be different spaces.

    A space id identifies a space for good, while its key can be changed,
    so when both sides carry an id the ids decide. Keys are compared,
    case-insensitively, only when an id is missing on either side.
    """
    local_id = local_space_id.strip()
    if local_id and remote.space_id:
        return local_id != remote.space_id
    local_key = local_space_key.strip()
    return bool(
        local_key and remote.space_key and local_key.casefold() != remote.space_key.casefold()
    )


def space_mismatch(remote: RemotePage, *, local_space_key: str, local_space_id: str) -> str:
    """Describe how the page's remote space differs from the local one, or ``""``.

    Values that are missing on either side are not compared; see
    :func:`_spaces_differ` for which fields decide.
    """
    if not _spaces_differ(remote, local_space_key=local_space_key, local_space_id=local_space_id):
        return ""
    local = local_space_key or UNKNOWN_SPACE
    if local_space_id:
        local += f" (id {local_space_id})"
    actual = remote.space_label
    if remote.space_id:
        actual += f" (id {remote.space_id})"
    return (
        f"page {remote.page_id} is in space {actual} on Confluence, but the "
        f"frontmatter says space {local}. Refusing to change a page outside "
        "the space the file belongs to; check confluence.page_id."
    )
