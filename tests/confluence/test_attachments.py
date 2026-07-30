"""Tests for mdd.confluence.attachments"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from mdd.confluence.attachments import download_for_page
from mdd.confluence.ir import AttachmentRef

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_attachment(filename: str, version: int = 1) -> dict[str, Any]:
    return {
        "id": f"att{abs(hash(filename)) % 10**10}",
        "pageId": "123",
        "title": filename,
        "version": {"number": version},
    }


def _make_client(
    attachments: list[dict[str, Any]],
    file_bytes: dict[str, bytes],
) -> MagicMock:
    client = MagicMock()
    client.list_page_attachments.return_value = attachments

    def download(att: dict[str, Any]) -> bytes:
        filename: Any = att.get("title", "")
        return file_bytes.get(str(filename), b"")

    client.download_attachment.side_effect = download
    return client


class TestDownloadForPage:
    def test_downloads_referenced_attachment(self, tmp_path: Path) -> None:
        data = b"PNG data here"
        att = _make_attachment("image.png")
        client = _make_client([att], {"image.png": data})
        refs = [AttachmentRef(filename="image.png")]

        manifest = download_for_page(client, "123", refs, tmp_path, "My-Page")

        assert len(manifest) == 1
        entry = manifest[0]
        assert entry.filename == "image.png"
        assert entry.sha256 == hashlib.sha256(data).hexdigest()
        assert entry.version == 1

        dest = tmp_path / "My-Page-attachments" / "image.png"
        assert dest.exists()
        assert dest.read_bytes() == data

    def test_skips_missing_attachment(self, tmp_path: Path) -> None:
        # Ref to "missing.png" but page has no such attachment
        att = _make_attachment("other.png")
        client = _make_client([att], {})
        refs = [AttachmentRef(filename="missing.png")]

        manifest = download_for_page(client, "123", refs, tmp_path, "Page")

        assert manifest == []

    def test_no_refs_returns_empty(self, tmp_path: Path) -> None:
        client = _make_client([], {})
        manifest = download_for_page(client, "123", [], tmp_path, "Page")
        assert manifest == []
        client.list_page_attachments.assert_not_called()

    def test_hash_computed_correctly(self, tmp_path: Path) -> None:
        data = b"some binary content"
        expected_hash = hashlib.sha256(data).hexdigest()
        att = _make_attachment("doc.pdf")
        client = _make_client([att], {"doc.pdf": data})
        refs = [AttachmentRef(filename="doc.pdf")]

        manifest = download_for_page(client, "123", refs, tmp_path, "Doc")

        assert manifest[0].sha256 == expected_hash

    def test_attachment_directory_named_correctly(self, tmp_path: Path) -> None:
        data = b"x"
        att = _make_attachment("x.txt")
        client = _make_client([att], {"x.txt": data})
        refs = [AttachmentRef(filename="x.txt")]

        download_for_page(client, "123", refs, tmp_path, "My Page")

        dest_dir = tmp_path / "My Page-attachments"
        assert dest_dir.is_dir()

    def test_version_extracted_from_metadata(self, tmp_path: Path) -> None:
        data = b"data"
        att = _make_attachment("img.jpg", version=3)
        client = _make_client([att], {"img.jpg": data})
        refs = [AttachmentRef(filename="img.jpg")]

        manifest = download_for_page(client, "123", refs, tmp_path, "Page")

        assert manifest[0].version == 3

    def test_traversal_filename_is_contained(self, tmp_path: Path) -> None:
        """A filename like '../../evil.txt' must not write outside attachments_dir.

        The basename is sanitised to 'evil.txt' and written safely inside the dir.
        The file must NOT appear at tmp_path.parent / 'evil.txt'.
        """
        data = b"sensitive"
        att = _make_attachment("../../evil.txt")
        client = _make_client([att], {"../../evil.txt": data})
        refs = [AttachmentRef(filename="../../evil.txt")]

        manifest = download_for_page(client, "123", refs, tmp_path, "Page")

        # File must not have escaped the attachments directory
        outside = tmp_path.parent / "evil.txt"
        assert not outside.exists()

        # The manifest entry (if present) must point inside attachments_dir
        attachments_dir = tmp_path / "Page-attachments"
        for entry in manifest:
            dest = attachments_dir / entry.filename
            assert dest.resolve().is_relative_to(attachments_dir.resolve())

    def test_absolute_path_filename_is_contained(self, tmp_path: Path) -> None:
        """A filename that is an absolute path must not write outside attachments_dir."""
        # Path("/etc/passwd").name == "passwd" — the safe_name extraction still works,
        # so the write lands inside attachments_dir rather than at /etc/passwd.
        data = b"data"
        att = _make_attachment("/etc/passwd")
        client = _make_client([att], {"/etc/passwd": data})
        refs = [AttachmentRef(filename="/etc/passwd")]

        manifest = download_for_page(client, "123", refs, tmp_path, "Page")

        # Any manifest entry must point to a file inside attachments_dir.
        attachments_dir = tmp_path / "Page-attachments"
        for entry in manifest:
            dest = attachments_dir / entry.filename
            assert dest.resolve().is_relative_to(attachments_dir.resolve())

    def test_per_attachment_failure_does_not_abort_page(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A single attachment failure must not abort the page export.

        ``download_for_page`` must catch per-attachment exceptions, log via
        :mod:`mdd.utils.logging`, and continue so the caller can still write
        the markdown body and download the other attachments.
        """
        good_data = b"good bytes"
        bad_atts = [_make_attachment("bad.png"), _make_attachment("good.png")]
        client = MagicMock()
        client.list_page_attachments.return_value = bad_atts

        def download(att: dict[str, Any]) -> bytes:
            filename: Any = att.get("title", "")
            if filename == "bad.png":
                raise RuntimeError("HTTP 500 from server")
            return good_data

        client.download_attachment.side_effect = download
        refs = [
            AttachmentRef(filename="bad.png"),
            AttachmentRef(filename="good.png"),
        ]

        with caplog.at_level("ERROR", logger="mdd.confluence.attachments.download"):
            # Must not raise.
            manifest = download_for_page(client, "123", refs, tmp_path, "Page")

        # The good attachment is still downloaded and recorded.
        assert len(manifest) == 1
        assert manifest[0].filename == "good.png"
        assert manifest[0].sha256 == hashlib.sha256(good_data).hexdigest()

        good_dest = tmp_path / "Page-attachments" / "good.png"
        assert good_dest.exists()
        assert good_dest.read_bytes() == good_data

        # The bad attachment is NOT on disk.
        bad_dest = tmp_path / "Page-attachments" / "bad.png"
        assert not bad_dest.exists()

        # And the failure was logged with the expected shape.
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "download bad.png" in msgs
        assert "page 123" in msgs
        assert "HTTP 500 from server" in msgs
