"""Pick a local destination path for a remote attachment name."""

from __future__ import annotations

from pathlib import Path

from mdd.utils.logging import get_logger

log = get_logger(__name__)

# Basenames git reads as repository control files. An attachment carrying one
# of these names would change what git stages or how it treats the files next
# to it, so it never lands in the working tree. Compared case-insensitively.
GIT_CONTROL_NAMES: frozenset[str] = frozenset(
    {".git", ".gitignore", ".gitattributes", ".gitmodules", ".mailmap"}
)


def safe_destination(filename: str, attachments_dir: Path) -> Path | None:
    """Return the destination for *filename* under *attachments_dir*, or ``None``.

    The remote name is reduced to its basename. ``None`` is returned when that
    basename is degenerate (empty, ``.`` or ``..``), is a git control-file name
    (a warning is logged), or would still resolve outside *attachments_dir*.
    """
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return None
    if safe_name.lower() in GIT_CONTROL_NAMES:
        log.warning("skip attachment %r: git control-file names are never written", filename)
        return None
    dest = attachments_dir / safe_name
    if not dest.resolve().is_relative_to(attachments_dir.resolve()):
        return None
    return dest
