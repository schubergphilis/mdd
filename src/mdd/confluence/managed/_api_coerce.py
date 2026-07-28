"""API-response coercion helpers (private to mdd.confluence.managed).

These helpers narrow ``Any``-typed values pulled from Confluence
API response dicts.  They are NOT for user-edited YAML (which goes
through the typed :mod:`mdd.utils.frontmatter` layer per spec S40);
they exist because the v2 API surface is large and only partially
modelled, and the few fields the managed-page classifier reads
(``id``, ``parentId``, ``ancestors[]``, ``version.authorId``,
``update.restrictions.user.results[]``) are easier to access via
these helpers than to fully model.

When the broader v2-response modelling effort lands (S40 §Out of
scope) this module disappears.
"""

from __future__ import annotations

from typing import Any, cast


def iter_dicts(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return the list at ``data[key]`` filtered to dict items, or [] if absent/wrong-shaped."""
    raw: Any = data.get(key) or []  # pyright: ignore[reportAny]
    if not isinstance(raw, list):
        return []
    return [cast("dict[str, Any]", item) for item in raw if isinstance(item, dict)]  # pyright: ignore[reportUnknownVariableType]


def dict_field(d: dict[str, Any], key: str) -> dict[str, Any]:
    """Return ``d[key]`` if it is a dict, else ``{}``."""
    raw: Any = d.get(key)  # pyright: ignore[reportAny]
    if isinstance(raw, dict):
        return cast("dict[str, Any]", raw)  # pyright: ignore[reportUnknownVariableType]
    return {}


def str_field(d: dict[str, Any], key: str) -> str:
    """Coerce ``d[key]`` to a non-None string. Missing or non-string -> ""."""
    raw: Any = d.get(key, "")  # pyright: ignore[reportAny]
    if not raw:
        return ""
    return str(raw)
