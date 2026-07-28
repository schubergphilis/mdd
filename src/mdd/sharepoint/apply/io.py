"""Atomic file writes and office-file backup helpers."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write *data* to *dest* atomically via a ``.tmp`` sibling."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)  # noqa: PTH105


def atomic_write_text(dest: Path, text: str) -> None:
    """Write *text* to *dest* atomically via a ``.tmp`` sibling."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dest)  # noqa: PTH105


def backup_office_file(office_path: Path, output_root: Path) -> None:
    """Copy *office_path* into ``.mdd-backups/`` before it is overwritten.

    The backup path is::

        <output_root>/.mdd-backups/<rel-path>/<timestamp>-<basename>

    where ``<rel-path>`` is the path of the office file relative to *output_root*,
    and ``<timestamp>`` is the current UTC time as ``YYYYMMDDTHHMMSS``.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    try:
        rel = office_path.relative_to(output_root)
    except ValueError:
        rel = Path(office_path.name)
    backup_dir = output_root / ".mdd-backups" / rel.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = f"{ts}-{office_path.name}"
    shutil.copy2(office_path, backup_dir / backup_name)
