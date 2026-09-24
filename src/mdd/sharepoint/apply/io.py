"""Atomic file writes and office-file backup helpers."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from mdd.utils import safe_write


def atomic_write_bytes(dest: Path, data: bytes, *, root: Path | None = None) -> None:
    """Write *data* to *dest* atomically via a ``.tmp`` sibling.

    Creates missing parent directories. Refuses to write through a symlink
    at *dest*, at the ``.tmp`` sibling, or at any directory between *root*
    and *dest*.
    """
    safe_write.mkdir_no_symlink(dest.parent, root=root)
    safe_write.atomic_write_bytes(dest, data, root=root)


def atomic_write_text(dest: Path, text: str, *, root: Path | None = None) -> None:
    """Write *text* to *dest* atomically via a ``.tmp`` sibling.

    Creates missing parent directories. Refuses to write through a symlink
    at *dest*, at the ``.tmp`` sibling, or at any directory between *root*
    and *dest*.
    """
    safe_write.mkdir_no_symlink(dest.parent, root=root)
    safe_write.atomic_write_text(dest, text, root=root)


def backup_office_file(office_path: Path, output_root: Path) -> None:
    """Copy *office_path* into ``.mdd-backups/`` before it is overwritten.

    The backup path is::

        <output_root>/.mdd-backups/<rel-path>/<timestamp>-<basename>

    where ``<rel-path>`` is the path of the office file relative to *output_root*,
    and ``<timestamp>`` is the current UTC time as ``YYYYMMDDTHHMMSS``.

    Refuses to copy when ``.mdd-backups`` or any directory below it inside
    *output_root* is a symlink, or when the backup file name is one.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    try:
        rel = office_path.relative_to(output_root)
    except ValueError:
        rel = Path(office_path.name)
    backup_dir = output_root / ".mdd-backups" / rel.parent
    safe_write.mkdir_no_symlink(backup_dir, root=output_root)
    backup_name = f"{ts}-{office_path.name}"
    dest = backup_dir / backup_name
    safe_write.refuse_symlink(dest)
    shutil.copy2(office_path, dest)
