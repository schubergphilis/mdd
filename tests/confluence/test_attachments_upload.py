"""Tests for upload logic in mdd.confluence.attachments"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mdd.confluence.attachments import (
    AttachmentCollisionError,
    AttachmentManifestEntry,
    sync_attachments_for_update,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_client(upload_response: dict[str, Any] | None = None) -> MagicMock:
    client = MagicMock()
    if upload_response is None:
        upload_response = {"results": [{"version": {"number": 1}}]}
    client.upload_attachment.return_value = upload_response
    return client


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestSyncAttachmentsForUpdate:
    def test_new_file_triggers_upload(self, tmp_path: Path) -> None:
        img = tmp_path / "image.png"
        _write_file(img, b"PNG data")

        client = _make_client()
        body_md = "![diagram](image.png)"
        manifest: list[AttachmentManifestEntry] = []

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, manifest)

        client.upload_attachment.assert_called_once_with("123", img)
        assert len(result) == 1
        assert result[0].filename == "image.png"
        assert result[0].sha256 == hashlib.sha256(b"PNG data").hexdigest()

    def test_hash_matches_manifest_skips_upload(self, tmp_path: Path) -> None:
        data = b"unchanged image data"
        img = tmp_path / "image.png"
        _write_file(img, data)

        sha = hashlib.sha256(data).hexdigest()
        existing_entry = AttachmentManifestEntry(filename="image.png", sha256=sha, version=1)

        client = _make_client()
        body_md = "![diagram](image.png)"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [existing_entry])

        client.upload_attachment.assert_not_called()
        assert len(result) == 1
        assert result[0].sha256 == sha

    def test_hash_mismatch_uploads_new_version(self, tmp_path: Path) -> None:
        img = tmp_path / "image.png"
        new_data = b"updated image data"
        _write_file(img, new_data)

        old_sha = hashlib.sha256(b"old data").hexdigest()
        existing_entry = AttachmentManifestEntry(filename="image.png", sha256=old_sha, version=1)

        client = _make_client({"results": [{"version": {"number": 2}}]})
        body_md = "![diagram](image.png)"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [existing_entry])

        client.upload_attachment.assert_called_once_with("123", img)
        assert result[0].sha256 == hashlib.sha256(new_data).hexdigest()
        assert result[0].version == 2

    def test_basename_collision_raises_error(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        img_a = dir_a / "image.png"
        img_b = dir_b / "image.png"
        _write_file(img_a, b"content A")
        _write_file(img_b, b"content B")

        client = _make_client()
        # Both images have the same basename but different content
        body_md = "![a](dir_a/image.png)\n![b](dir_b/image.png)"

        with pytest.raises(AttachmentCollisionError):
            sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        # No upload should have happened
        client.upload_attachment.assert_not_called()

    def test_no_local_refs_returns_manifest_unchanged(self, tmp_path: Path) -> None:
        existing = AttachmentManifestEntry(filename="old.png", sha256="abc", version=1)
        client = _make_client()
        body_md = "No images here, just text."

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [existing])

        client.upload_attachment.assert_not_called()
        assert len(result) == 1
        assert result[0].filename == "old.png"

    def test_external_url_images_are_not_uploaded(self, tmp_path: Path) -> None:
        client = _make_client()
        body_md = "![logo](https://example.com/logo.png)"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_not_called()
        assert result == []

    def test_missing_file_emits_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A missing local attachment must produce a logger warning."""
        client = _make_client()
        body_md = "![ghost](nonexistent.png)"

        with caplog.at_level("WARNING", logger="mdd.confluence.attachments.update"):
            result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_not_called()
        assert result == []

        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "nonexistent.png" in msgs
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_same_file_referenced_twice_uploaded_once(self, tmp_path: Path) -> None:
        img = tmp_path / "image.png"
        _write_file(img, b"data")

        client = _make_client()
        body_md = "![a](image.png)\n![b](image.png)"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        # Only one upload since same file
        client.upload_attachment.assert_called_once()
        assert len(result) == 1

    def test_traversal_path_ref_is_skipped(self, tmp_path: Path) -> None:
        """An upload-side traversal reference must not read outside working_dir."""
        # Create a file outside tmp_path to simulate a potential traversal target
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secret.txt"
        outside_file.write_bytes(b"secret content")

        client = _make_client()
        # Reference escapes working_dir via ../outside/secret.txt
        body_md = "![secret](../outside/secret.txt)"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        # The traversal reference must be silently skipped — no upload
        client.upload_attachment.assert_not_called()
        assert result == []

        # Clean up
        outside_file.unlink(missing_ok=True)
        outside_dir.rmdir()

    def test_image_ref_inside_inline_code_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An ``![alt](src)`` pattern inside backticks is author prose, not a real ref."""
        client = _make_client()
        body_md = (
            "Documentation page explaining the syntax. Authors write "
            "`![alt](url)` to embed images; the parser resolves the URL "
            "at read time."
        )

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_not_called()
        assert result == []
        captured = capsys.readouterr()
        assert "url" not in captured.err

    def test_image_ref_inside_fenced_code_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An ``![alt](src)`` pattern inside a fenced code block is sample code, not a ref."""
        client = _make_client()
        body_md = (
            "Example below shows the inline image syntax:\n\n"
            "```markdown\n"
            "![diagram](architecture.png)\n"
            "```\n\n"
            "End of example."
        )

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_not_called()
        assert result == []
        captured = capsys.readouterr()
        assert "architecture.png" not in captured.err

    def test_image_ref_outside_code_still_detected(self, tmp_path: Path) -> None:
        """A real image reference outside any code context must still be scanned."""
        img = tmp_path / "real.png"
        _write_file(img, b"real data")

        client = _make_client()
        body_md = (
            "Example: write `![alt](placeholder)` to embed an image.\n\n"
            "Here is a real one: ![hero](real.png)\n"
        )

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)
        assert len(result) == 1
        assert result[0].filename == "real.png"

    def test_reference_style_image_resolves_via_label(self, tmp_path: Path) -> None:
        """``![alt][label]`` resolves through the ``[label]: url`` definition."""
        img = tmp_path / "architecture.png"
        _write_file(img, b"diagram bytes")

        client = _make_client()
        body_md = (
            "See the system overview: ![architecture diagram][arch].\n\n[arch]: architecture.png\n"
        )

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)
        assert len(result) == 1
        assert result[0].filename == "architecture.png"

    def test_shortcut_reference_image_resolves_via_label(self, tmp_path: Path) -> None:
        """``![label]`` shortcut form resolves through the ``[label]: url`` definition."""
        img = tmp_path / "diagram.svg"
        _write_file(img, b"<svg/>")

        client = _make_client()
        body_md = "Inline image: ![diagram].\n\n[diagram]: diagram.svg\n"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)
        assert len(result) == 1
        assert result[0].filename == "diagram.svg"

    def test_confluence_attachment_link_triggers_upload(self, tmp_path: Path) -> None:
        """``[label](confluence-attachment:file.pdf)`` queues the sibling
        file for upload alongside ``![…](file.png)`` image references."""
        pdf = tmp_path / "report.pdf"
        _write_file(pdf, b"%PDF-1.4 stub")

        client = _make_client()
        body_md = "See [the report](confluence-attachment:report.pdf) for details.\n"

        result, _ = sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", pdf)
        assert len(result) == 1
        assert result[0].filename == "report.pdf"

    def test_confluence_attachment_link_with_extras_strips_them(self, tmp_path: Path) -> None:
        """Semicolon-delimited extras on the URI are not part of the filename."""
        pdf = tmp_path / "spec.pdf"
        _write_file(pdf, b"%PDF")

        client = _make_client()
        body_md = "Spec: [v3](confluence-attachment:spec.pdf;version-at-save=3)\n"

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", pdf)

    def test_confluence_attachment_image_strips_scheme(self, tmp_path: Path) -> None:
        """``![alt](confluence-attachment:file.png)`` image refs queue for upload."""
        img = tmp_path / "diagram.png"
        _write_file(img, b"\x89PNG")

        client = _make_client()
        body_md = "![diagram](confluence-attachment:diagram.png)\n"

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)

    def test_confluence_attachment_image_with_title_slot(self, tmp_path: Path) -> None:
        """The markdown title slot (``"width=320 align=left"``) is not part of the
        filename. Without this fix the scanner captures the whole paren content as
        a single ``src`` and warns about a non-existent file."""
        img = tmp_path / "screenshot.png"
        _write_file(img, b"\x89PNG")

        client = _make_client()
        body_md = '![screenshot](confluence-attachment:screenshot.png "align=left width=320")\n'

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)

    def test_confluence_attachment_image_with_extras_and_title(self, tmp_path: Path) -> None:
        """Both ``;extras`` on the URI and ``"title"`` slot must be stripped."""
        img = tmp_path / "screenshot.png"
        _write_file(img, b"\x89PNG")

        client = _make_client()
        body_md = (
            "![s](confluence-attachment:screenshot.png;width=320;align=left "
            '"align=left width=320")\n'
        )

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)

    def test_confluence_attachment_image_url_decodes_filename(self, tmp_path: Path) -> None:
        """``%20`` etc. must be decoded so the filename matches the file on disk."""
        img = tmp_path / "Screen Recording 2026-02-12 at 16.36.30.mov"
        _write_file(img, b"MOV")

        client = _make_client()
        body_md = (
            "![rec](confluence-attachment:Screen%20Recording%202026-02-12%20at%2016.36.30.mov)\n"
        )

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_called_once_with("123", img)

    def test_confluence_attachment_image_resolves_in_attachments_dir(self, tmp_path: Path) -> None:
        """``mdd confluence export-page`` writes attachments to
        ``<page>-attachments/`` next to the markdown file. The update path must
        look there as well, not only in the markdown's parent directory."""
        attachments_dir = tmp_path / "MyPage-attachments"
        img = attachments_dir / "diagram.png"
        _write_file(img, b"\x89PNG")

        client = _make_client()
        body_md = "![diagram](confluence-attachment:diagram.png)\n"

        sync_attachments_for_update(
            client, "123", body_md, tmp_path, [], attachments_dir=attachments_dir
        )

        client.upload_attachment.assert_called_once_with("123", img)

    def test_reference_style_with_missing_definition_warns_not_label(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A reference-style image with no matching definition is not flagged
        with the literal label as a filename (the old buggy behaviour)."""
        client = _make_client()
        body_md = "![alt][missing-label]\n"

        sync_attachments_for_update(client, "123", body_md, tmp_path, [])

        client.upload_attachment.assert_not_called()
        captured = capsys.readouterr()
        assert "missing-label" not in captured.err
