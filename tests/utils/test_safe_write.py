"""Tests for mdd.utils.safe_write."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.utils.safe_write import (
    OutsideRootError,
    SymlinkRefusedError,
    atomic_write_bytes,
    atomic_write_text,
    mkdir_no_symlink,
    refuse_symlink,
    refuse_symlink_below,
    write_new_bytes,
    write_new_text,
)

if TYPE_CHECKING:
    from pathlib import Path


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


# ---------------------------------------------------------------------------
# refuse_symlink / refuse_symlink_below
# ---------------------------------------------------------------------------


class TestRefuseSymlink:
    def test_regular_file_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x")
        refuse_symlink(f)

    def test_missing_path_passes(self, tmp_path: Path) -> None:
        refuse_symlink(tmp_path / "missing")

    def test_symlink_to_file_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / "link"
        _symlink(link, target)
        with pytest.raises(SymlinkRefusedError) as exc_info:
            refuse_symlink(link)
        assert exc_info.value.path == link
        assert "link" in str(exc_info.value)

    def test_dangling_symlink_refused(self, tmp_path: Path) -> None:
        link = tmp_path / "dangling"
        _symlink(link, tmp_path / "nowhere")
        with pytest.raises(SymlinkRefusedError):
            refuse_symlink(link)

    def test_is_an_oserror(self, tmp_path: Path) -> None:
        link = tmp_path / "link"
        _symlink(link, tmp_path / "nowhere")
        with pytest.raises(OSError, match="refusing to write through symlink"):
            refuse_symlink(link)


class TestRefuseSymlinkBelow:
    def test_root_none_checks_only_leaf(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        linkdir = tmp_path / "linkdir"
        _symlink(linkdir, real)
        # The parent is a symlink but root=None only inspects the leaf.
        refuse_symlink_below(linkdir / "file.txt", None)

    def test_symlinked_intermediate_refused(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        linkdir = tmp_path / "linkdir"
        _symlink(linkdir, real)
        with pytest.raises(SymlinkRefusedError) as exc_info:
            refuse_symlink_below(linkdir / "sub" / "file.txt", tmp_path)
        assert exc_info.value.path == linkdir

    def test_root_itself_not_checked(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        root_link = tmp_path / "root_link"
        _symlink(root_link, real)
        refuse_symlink_below(root_link / "a" / "b.txt", root_link)

    def test_path_equal_to_symlinked_root_passes(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        root_link = tmp_path / "root_link"
        _symlink(root_link, real)
        refuse_symlink_below(root_link, root_link)
        mkdir_no_symlink(root_link, root=root_link)

    def test_real_chain_passes(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "b").mkdir(parents=True)
        refuse_symlink_below(tmp_path / "a" / "b" / "c.txt", tmp_path)

    def test_path_outside_root_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="refusing to write outside"):
            refuse_symlink_below(tmp_path.parent / "elsewhere.txt", tmp_path)

    def test_path_outside_root_is_an_os_error(self, tmp_path: Path) -> None:
        with pytest.raises(OSError, match="refusing to write outside") as info:
            refuse_symlink_below(tmp_path.parent / "elsewhere.txt", tmp_path)
        assert isinstance(info.value, OutsideRootError)
        assert info.value.root == tmp_path


# ---------------------------------------------------------------------------
# mkdir_no_symlink
# ---------------------------------------------------------------------------


class TestMkdirNoSymlink:
    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        d = tmp_path / "a" / "b" / "c"
        mkdir_no_symlink(d, root=tmp_path)
        assert d.is_dir()

    def test_existing_real_directory_accepted(self, tmp_path: Path) -> None:
        d = tmp_path / "a"
        d.mkdir()
        mkdir_no_symlink(d)
        assert d.is_dir()

    def test_symlink_to_directory_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        link = tmp_path / "mirror" / "X-attachments"
        link.parent.mkdir()
        _symlink(link, outside)
        with pytest.raises(SymlinkRefusedError):
            mkdir_no_symlink(link)
        with pytest.raises(SymlinkRefusedError):
            mkdir_no_symlink(link / "deeper", root=tmp_path / "mirror")

    def test_dangling_symlink_refused_not_created_through(self, tmp_path: Path) -> None:
        link = tmp_path / "linkdir"
        _symlink(link, tmp_path / "outside")
        with pytest.raises(SymlinkRefusedError):
            mkdir_no_symlink(link)
        assert not (tmp_path / "outside").exists()


# ---------------------------------------------------------------------------
# write_new_bytes / write_new_text
# ---------------------------------------------------------------------------


class TestWriteNew:
    def test_creates_file(self, tmp_path: Path) -> None:
        f = tmp_path / "new.txt"
        write_new_text(f, "hello")
        assert f.read_text(encoding="utf-8") == "hello"

    def test_mode_applied(self, tmp_path: Path) -> None:
        f = tmp_path / "run.sh"
        write_new_text(f, "#!/bin/sh\n", mode=0o755)
        assert stat.S_IMODE(f.stat().st_mode) == 0o755

    def test_existing_file_refused(self, tmp_path: Path) -> None:
        f = tmp_path / "exists.txt"
        f.write_text("old")
        with pytest.raises(FileExistsError):
            write_new_bytes(f, b"new")
        assert f.read_text() == "old"

    def test_symlink_refused_target_untouched(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim"
        victim.write_text("keep me")
        link = tmp_path / "link"
        _symlink(link, victim)
        with pytest.raises(FileExistsError):
            write_new_text(link, "clobber", mode=0o755)
        assert victim.read_text() == "keep me"
        assert stat.S_IMODE(victim.stat().st_mode) != 0o755

    def test_dangling_symlink_refused_target_not_created(self, tmp_path: Path) -> None:
        target = tmp_path / "outside" / "target"
        target.parent.mkdir()
        link = tmp_path / "link"
        _symlink(link, target)
        with pytest.raises(FileExistsError):
            write_new_text(link, "x")
        assert not target.exists()

    def test_write_failure_removes_partial_file(self, tmp_path: Path) -> None:
        f = tmp_path / "new.txt"
        with (
            patch("mdd.utils.safe_write.os.fsync", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            write_new_text(f, "x")
        assert not f.exists()

    def test_chmod_failure_removes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "new.txt"
        with (
            patch("mdd.utils.safe_write.os.fchmod", side_effect=OSError("no chmod")),
            pytest.raises(OSError, match="no chmod"),
        ):
            write_new_text(f, "x", mode=0o755)
        assert not f.exists()


# ---------------------------------------------------------------------------
# atomic_write_bytes / atomic_write_text
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_writes_bytes_and_removes_tmp(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"
        atomic_write_bytes(dest, b"hello")
        assert dest.read_bytes() == b"hello"
        assert not (tmp_path / "out.bin.tmp").exists()

    def test_writes_text_utf8(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        atomic_write_text(dest, "héllo")
        assert dest.read_text(encoding="utf-8") == "héllo"

    def test_overwrites_existing_regular_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        dest.write_text("old")
        atomic_write_text(dest, "new")
        assert dest.read_text() == "new"

    def test_stale_tmp_regular_file_is_replaced(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        (tmp_path / "out.md.tmp").write_text("leftover")
        atomic_write_text(dest, "new")
        assert dest.read_text() == "new"
        assert not (tmp_path / "out.md.tmp").exists()

    def test_permissions_follow_umask_not_0600(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        old = os.umask(0o022)
        try:
            atomic_write_text(dest, "x")
        finally:
            os.umask(old)
        assert stat.S_IMODE(dest.stat().st_mode) == 0o644

    def test_dangling_tmp_symlink_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        dest = tmp_path / "Foo.md"
        _symlink(tmp_path / "Foo.md.tmp", outside / "target")
        with pytest.raises(SymlinkRefusedError):
            atomic_write_text(dest, "payload")
        assert not (outside / "target").exists()
        assert not dest.exists()
        # The planted link is left alone, not replaced.
        assert (tmp_path / "Foo.md.tmp").is_symlink()

    def test_tmp_symlink_to_file_refused_target_untouched(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim"
        victim.write_text("keep me")
        dest = tmp_path / "Foo.md"
        _symlink(tmp_path / "Foo.md.tmp", victim)
        with pytest.raises(SymlinkRefusedError):
            atomic_write_text(dest, "payload")
        assert victim.read_text() == "keep me"

    def test_dest_symlink_refused(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim"
        victim.write_text("keep me")
        dest = tmp_path / "Foo.md"
        _symlink(dest, victim)
        with pytest.raises(SymlinkRefusedError):
            atomic_write_text(dest, "payload")
        assert victim.read_text() == "keep me"
        assert dest.is_symlink()
        assert not (tmp_path / "Foo.md.tmp").exists()

    def test_symlinked_parent_below_root_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "mirror"
        root.mkdir()
        _symlink(root / "Docs", outside)
        with pytest.raises(SymlinkRefusedError):
            atomic_write_text(root / "Docs" / "Page.md", "payload", root=root)
        assert list(outside.iterdir()) == []

    def test_race_symlink_planted_at_tmp_fails_exclusive_open(self, tmp_path: Path) -> None:
        """A link appearing after the pre-check still cannot be written through."""
        victim = tmp_path / "victim"
        victim.write_text("keep me")
        dest = tmp_path / "Foo.md"
        tmp = tmp_path / "Foo.md.tmp"

        def plant(_tmp: Path) -> None:
            _symlink(tmp, victim)

        with (
            patch("mdd.utils.safe_write._clear_stale_tmp", side_effect=plant),
            pytest.raises(FileExistsError),
        ):
            atomic_write_text(dest, "payload")
        assert victim.read_text() == "keep me"

    def test_write_failure_removes_tmp(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        with (
            patch("mdd.utils.safe_write.os.fsync", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            atomic_write_text(dest, "x")
        assert not (tmp_path / "out.md.tmp").exists()
        assert not dest.exists()

    def test_replace_failure_removes_tmp(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.md"
        with (
            patch("mdd.utils.safe_write.os.replace", side_effect=OSError("cross-device")),
            pytest.raises(OSError, match="cross-device"),
        ):
            atomic_write_text(dest, "x")
        assert not (tmp_path / "out.md.tmp").exists()
