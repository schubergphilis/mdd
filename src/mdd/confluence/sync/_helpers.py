"""Tiny cross-module helpers for the sync package."""

from __future__ import annotations

import os
from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def pin_mtime_to_exported_at(path: Path, frontmatter: dict[str, Any]) -> None:
    """Set ``path``'s mtime to ``confluence.exported_at`` from ``frontmatter``.

    The local-edit heuristic in :mod:`mdd.confluence.sync.local_edits` treats
    ``mtime > exported_at`` as evidence of a user edit. After a write that
    isn't a user edit (sync metadata refresh, archive flip, …) we restore
    that invariant by pinning mtime back to the recorded ``exported_at``.

    Silently no-ops if ``exported_at`` is missing or unparseable — better
    a spurious push than a crashed sync.
    """
    conf_raw: Any = frontmatter.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return
    conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
    raw: Any = conf.get("exported_at")  # pyright: ignore[reportAny]
    if not isinstance(raw, str) or not raw:
        return
    with suppress(ValueError, OSError):
        ts = datetime.fromisoformat(raw).timestamp()
        os.utime(path, (ts, ts))


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
