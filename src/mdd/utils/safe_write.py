"""Filesystem write helpers that refuse to write through symlinks.

Every mirror-side write in ``mdd`` goes through one of these helpers so that a
symlink planted at the destination, at its ``.tmp`` sibling, or at a directory
between the mirror root and the destination is refused instead of followed.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class SymlinkRefusedError(OSError):
    """Raised when a write would go through a symbolic link."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"refusing to write through symlink: {path}")
        self.path = path


class OutsideRootError(OSError, ValueError):
    """Raised when a path that must sit below a root does not.

    It is an :class:`OSError` so that callers which report per-file write
    failures report this one too, and a :class:`ValueError` because that is
    what :meth:`pathlib.PurePath.relative_to` raises for the same condition.
    """

    def __init__(self, path: Path, root: Path) -> None:
        super().__init__(f"refusing to write outside {root}: {path}")
        self.path = path
        self.root = root


def refuse_symlink(path: Path) -> None:
    """Raise :class:`SymlinkRefusedError` if *path* is a symlink.

    Dangling symlinks count: the check uses ``lstat`` semantics and does not
    care whether the link target exists.
    """
    if path.is_symlink():
        raise SymlinkRefusedError(path)


def refuse_symlink_below(path: Path, root: Path | None) -> None:
    """Refuse *path* if it, or any directory between *root* and it, is a symlink.

    *root* itself is not checked, so an operator may point the mirror root at a
    symlinked directory; that holds when *path* is *root* too. With
    ``root=None`` only *path* itself is checked.

    Raises:
        SymlinkRefusedError: A symlink was found below *root*.
        OutsideRootError: *path* is not lexically below *root*.
    """
    if root is not None and path == root:
        return
    refuse_symlink(path)
    if root is None:
        return
    try:
        rel = path.relative_to(root)
    except ValueError:
        raise OutsideRootError(path, root) from None
    current = root
    for part in rel.parts[:-1]:
        current = current / part
        refuse_symlink(current)


def mkdir_no_symlink(path: Path, *, root: Path | None = None) -> None:
    """Create *path* and its parents, refusing symlinks at or below *root*.

    A pre-existing real directory is accepted. A symlink to a directory is
    refused even though ``Path.mkdir(exist_ok=True)`` would accept it.
    """
    refuse_symlink_below(path, root)
    path.mkdir(parents=True, exist_ok=True)


def _open_exclusive(path: Path, mode: int = 0o666) -> int:
    """Create *path* as a new regular file and return its descriptor.

    Fails with :class:`FileExistsError` when anything, including a dangling
    symlink, already sits at *path*.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, mode)


def _write_fd(fd: int, data: bytes) -> None:
    """Write *data* to *fd* fully, fsync it and close the descriptor."""
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Create *path* as a new file holding *data*.

    Refuses to write through a symlink and refuses to overwrite anything that
    already exists at *path* (:class:`FileExistsError`). When *mode* is given
    the permission bits are set on the open descriptor before closing.
    """
    fd = _open_exclusive(path)
    try:
        if mode is not None:
            os.fchmod(fd, mode)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    try:
        _write_fd(fd, data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_new_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """Create *path* as a new UTF-8 file holding *text*; see :func:`write_new_bytes`."""
    write_new_bytes(path, text.encode("utf-8"), mode=mode)


def _clear_stale_tmp(tmp: Path) -> None:
    """Remove a leftover regular ``.tmp`` file; refuse if it is a symlink."""
    refuse_symlink(tmp)
    if tmp.exists():
        tmp.unlink()


def atomic_write_bytes(dest: Path, data: bytes, *, root: Path | None = None) -> None:
    """Write *data* to *dest* atomically via a ``<dest>.tmp`` sibling.

    Refuses to write through a symlink at *dest*, at the ``.tmp`` sibling, or
    at any directory between *root* and *dest*. The temp file is created
    exclusively so a link planted between the check and the open still fails.
    The temp file is removed on any failure.
    """
    refuse_symlink_below(dest, root)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    _clear_stale_tmp(tmp)
    fd = _open_exclusive(tmp)
    try:
        _write_fd(fd, data)
        refuse_symlink(dest)
        os.replace(tmp, dest)  # noqa: PTH105
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(dest: Path, text: str, *, root: Path | None = None) -> None:
    """Write *text* as UTF-8 to *dest* atomically; see :func:`atomic_write_bytes`."""
    atomic_write_bytes(dest, text.encode("utf-8"), root=root)
