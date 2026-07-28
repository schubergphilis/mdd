"""Shared helper for extracting an attachment ``version`` from a Confluence API
response dict.

Confluence's REST API returns version metadata in two shapes:

- ``{"version": {"number": 7, ...}}`` (the common case — both v1 and v2).
- ``{"version": 7}`` (a few older v1 list endpoints).

Both ``download.py``, ``update.py``, and ``sync_all.py`` parse the same shape;
this helper is the single source of truth so the parsing rule cannot drift
between code paths.
"""

from __future__ import annotations

from typing import Any


def extract_version(att: dict[str, Any]) -> int | str:
    """Return ``att["version"]`` coerced to ``int | str``, defaulting to ``1``.

    Accepts the two shapes Confluence emits (nested ``{"number": N}`` or a bare
    int). Anything else falls back to ``1`` — version numbers must never be
    ``None`` because the manifest dataclass forbids it.
    """
    version_raw: Any = att.get("version")  # pyright: ignore[reportAny]
    if isinstance(version_raw, dict):
        version_data: dict[str, Any] = dict(version_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        vn: Any = version_data.get("number")  # pyright: ignore[reportAny]
        return int(vn) if isinstance(vn, int) else 1
    if isinstance(version_raw, int):
        return version_raw
    return 1


def extract_upload_version(result: dict[str, Any]) -> int | str:
    """Pull the new version number out of an ``upload_attachment`` response.

    The v1 upload endpoint returns ``{"results": [{"version": ...}]}`` where
    ``version`` follows the same shape :func:`extract_version` already
    handles. Defaults to ``1`` when the response cannot be parsed.
    """
    results_raw: Any = result.get("results")  # pyright: ignore[reportAny]
    if not isinstance(results_raw, list) or not results_raw:
        return 1
    first_raw: Any = results_raw[0]  # pyright: ignore[reportAny, reportUnknownVariableType]
    if not isinstance(first_raw, dict):
        return 1
    first: dict[str, Any] = dict(first_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    return extract_version(first)
