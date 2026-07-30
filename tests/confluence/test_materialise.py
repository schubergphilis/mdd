"""Tests for mdd.confluence.materialise — per-page pull / promote helpers."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.confluence.materialise import (
    INDEX_BASENAME,
    promote_flat_to_dir,
    pull_single_page,
)

if TYPE_CHECKING:
    from pathlib import Path


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=str(repo), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=str(repo), check=True, capture_output=True
    )


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True
    )


class TestPullSinglePage:
    def test_renames_export_output_to_index(self, tmp_path: Path) -> None:
        """After ``export_page`` writes ``<title>.md``, we rename onto ``_index.md``."""
        target_dir = tmp_path / "Parent"

        def _fake_export(_client: object, _page_id: str, out_dir: Path, **_kw: object) -> Path:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / "Parent.md"
            path.write_text("---\nconfluence:\n  page_id: P\n---\nbody\n")
            return path

        with patch("mdd.confluence.materialise.export_page", side_effect=_fake_export):
            result = pull_single_page(client=object(), page_id="P", target_dir=target_dir)  # type: ignore[arg-type]

        assert result.page_id == "P"
        assert result.written_path == target_dir / INDEX_BASENAME
        assert (target_dir / INDEX_BASENAME).exists()
        # Original sanitized filename is gone.
        assert not (target_dir / "Parent.md").exists()

    def test_no_rename_when_export_already_wrote_index(self, tmp_path: Path) -> None:
        """If the export pipeline already produced ``_index.md`` we leave it alone."""
        target_dir = tmp_path / "Parent"

        def _fake_export(_client: object, _page_id: str, out_dir: Path, **_kw: object) -> Path:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / INDEX_BASENAME
            path.write_text("---\n---\nbody\n")
            return path

        with patch("mdd.confluence.materialise.export_page", side_effect=_fake_export):
            result = pull_single_page(client=object(), page_id="P", target_dir=target_dir)  # type: ignore[arg-type]

        assert result.written_path == target_dir / INDEX_BASENAME

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "a" / "b" / "c"

        def _fake_export(_client: object, _page_id: str, out_dir: Path, **_kw: object) -> Path:
            path = out_dir / "X.md"
            path.write_text("---\n---\nx\n")
            return path

        with patch("mdd.confluence.materialise.export_page", side_effect=_fake_export):
            pull_single_page(client=object(), page_id="P", target_dir=target_dir)  # type: ignore[arg-type]

        assert target_dir.is_dir()
        assert (target_dir / INDEX_BASENAME).exists()


class TestPromoteFlatToDir:
    def test_moves_flat_md_to_index(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        flat = tmp_path / "Parent.md"
        flat.write_text("---\n---\nbody\n")
        _commit_all(tmp_path)

        expected_dir = tmp_path / "Parent"
        new_path = promote_flat_to_dir(flat, expected_dir, tmp_path)
        assert new_path == expected_dir / INDEX_BASENAME
        assert new_path.exists()
        assert not flat.exists()

    def test_moves_attachments_dir_alongside(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        flat = tmp_path / "Parent.md"
        flat.write_text("---\n---\nbody\n")
        att = tmp_path / "Parent-attachments"
        att.mkdir()
        (att / "file.txt").write_text("contents\n")
        _commit_all(tmp_path)

        expected_dir = tmp_path / "Parent"
        promote_flat_to_dir(flat, expected_dir, tmp_path)

        # New attachments dir lives alongside the new _index.md.
        new_att = expected_dir / "Parent-attachments"
        assert new_att.is_dir()
        assert (new_att / "file.txt").exists()
        assert not att.exists()

    def test_no_attachments_dir_is_fine(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        flat = tmp_path / "Parent.md"
        flat.write_text("---\n---\nbody\n")
        _commit_all(tmp_path)

        expected_dir = tmp_path / "Parent"
        new_path = promote_flat_to_dir(flat, expected_dir, tmp_path)
        assert new_path.exists()
