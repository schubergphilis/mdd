"""Tiny cross-module helpers for the sync package."""

from __future__ import annotations

from typing import Any


def extract_storage_body(page_data: dict[str, Any]) -> str:
    """Extract ``body.storage.value`` from a v1 ``GET /content/<id>`` response."""
    body_raw: Any = page_data.get("body")  # pyright: ignore[reportAny]
    if not isinstance(body_raw, dict):
        return ""
    body_dict: dict[str, Any] = body_raw  # pyright: ignore[reportUnknownVariableType]
    storage_raw: Any = body_dict.get("storage")  # pyright: ignore[reportAny]
    if not isinstance(storage_raw, dict):
        return ""
    storage_dict: dict[str, Any] = storage_raw  # pyright: ignore[reportUnknownVariableType]
    val: Any = storage_dict.get("value")  # pyright: ignore[reportAny]
    return str(val) if isinstance(val, str) else ""
