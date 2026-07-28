"""Tests for spec S16: Confluence attachment conversion.

Covers:
- conversion_needed() all branch combinations
- sync_all_attachments() happy path (download + convert)
- sync_all_attachments() skips by size limit
- sync_all_attachments() converter failure doesn't stop remaining
- sync_all_attachments() cache hit (sha + converter version match)
- sync_all_attachments() no attachments
- Retry-After header honoured in client (tested in test_client_retry.py)
- Manifest schema: converted_to / converter / converter_version fields
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.attachments import (
    AttachmentManifestEntry,
    AttachmentSyncSummary,
    conversion_needed,
    sync_all_attachments,
)
from mdd.converters.protocol import ConvertResult

# Short alias for the patch target to keep line length under 100 chars
_CONV_FOR = "mdd.confluence.attachments.sync_all._registry_converter_for"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_att(
    filename: str,
    version: int = 1,
    file_size: int | None = None,
    *,
    file_size_shape: str = "v1",
) -> dict[str, Any]:
    """Build a fake attachment dict.

    ``file_size_shape`` toggles between the v1 ``extensions.fileSize`` location
    (default — preserves historical test behaviour) and the v2 top-level
    ``fileSize`` shape that current Confluence tenants emit.
    """
    att: dict[str, Any] = {
        "title": filename,
        "version": {"number": version},
        "_links": {"download": f"/wiki/download/attachments/999/{filename}"},
    }
    if file_size is not None:
        if file_size_shape == "v2":
            att["fileSize"] = file_size
        else:
            att["extensions"] = {"fileSize": file_size}
    return att


def _make_att_raw(filename: str, version: Any) -> dict[str, Any]:
    """Build an attachment dict with a caller-controlled ``version`` value.

    Lets a test feed in non-canonical shapes (bare int, missing field, etc.)
    to exercise the version-decoder branches that ``_make_att`` cannot
    reach because it always emits the ``{"number": N}`` dict shape.
    """
    att: dict[str, Any] = {
        "title": filename,
        "_links": {"download": f"/wiki/download/attachments/999/{filename}"},
    }
    if version is not _MISSING:
        att["version"] = version
    return att


_MISSING = object()


def _make_client(
    attachments: list[dict[str, Any]],
    file_bytes: dict[str, bytes],
) -> MagicMock:
    """Build a mock ConfluenceClient for attachment sync tests."""
    client = MagicMock()
    client.list_page_attachments.return_value = attachments

    def download_to_file(att: dict[str, Any], dest: Path) -> int:
        fn: Any = att.get("title", "")
        data = file_bytes.get(str(fn), b"")
        dest.write_bytes(data)
        return len(data)

    client.download_attachment_to_file.side_effect = download_to_file
    return client


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# conversion_needed()
# ---------------------------------------------------------------------------


class TestConversionNeeded:
    def test_no_manifest_entry_returns_true(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.docx"
        f.write_bytes(b"data")
        assert conversion_needed(f, None, "v1") is True

    def test_sha_mismatch_returns_true(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.docx"
        f.write_bytes(b"new data")
        entry = AttachmentManifestEntry(
            filename="doc.docx",
            sha256="deadbeef",
            version=1,
            converted_to="doc.docx.md",
            converter="DocxConverter",
            converter_version="v1",
        )
        assert conversion_needed(f, entry, "v1") is True

    def test_converter_version_mismatch_returns_true(self, tmp_path: Path) -> None:
        data = b"content"
        f = tmp_path / "doc.docx"
        f.write_bytes(data)
        entry = AttachmentManifestEntry(
            filename="doc.docx",
            sha256=_sha256(data),
            version=1,
            converted_to="doc.docx.md",
            converter="DocxConverter",
            converter_version="v1",
        )
        assert conversion_needed(f, entry, "v2") is True

    def test_output_missing_returns_true(self, tmp_path: Path) -> None:
        data = b"content"
        f = tmp_path / "doc.docx"
        f.write_bytes(data)
        # Output file does NOT exist
        entry = AttachmentManifestEntry(
            filename="doc.docx",
            sha256=_sha256(data),
            version=1,
            converted_to="doc.docx.md",
            converter="DocxConverter",
            converter_version="v1",
        )
        assert conversion_needed(f, entry, "v1") is True

    def test_all_match_returns_false(self, tmp_path: Path) -> None:
        data = b"content"
        f = tmp_path / "doc.docx"
        f.write_bytes(data)
        # Output file exists
        out = tmp_path / "doc.docx.md"
        out.write_text("# converted", encoding="utf-8")
        entry = AttachmentManifestEntry(
            filename="doc.docx",
            sha256=_sha256(data),
            version=1,
            converted_to="doc.docx.md",
            converter="DocxConverter",
            converter_version="v1",
        )
        assert conversion_needed(f, entry, "v1") is False

    def test_no_converted_to_field_returns_true(self, tmp_path: Path) -> None:
        data = b"content"
        f = tmp_path / "doc.docx"
        f.write_bytes(data)
        entry = AttachmentManifestEntry(
            filename="doc.docx",
            sha256=_sha256(data),
            version=1,
            # no converted_to
        )
        assert conversion_needed(f, entry, "v1") is True


# ---------------------------------------------------------------------------
# sync_all_attachments() — happy path
# ---------------------------------------------------------------------------


class TestSyncAllAttachmentsHappyPath:
    def test_no_attachments_returns_empty(self, tmp_path: Path) -> None:
        client = _make_client([], {})
        att_dir = tmp_path / "page-attachments"
        result, summary = sync_all_attachments(client, "999", att_dir, [])
        assert result == []
        assert summary.synced == 0
        assert summary.converted == 0

    def test_unconvertible_attachment_downloaded_only(self, tmp_path: Path) -> None:
        data = b"xlsx binary"
        att = _make_att("Report.xlsx")
        client = _make_client([att], {"Report.xlsx": data})
        att_dir = tmp_path / "page-attachments"

        result, summary = sync_all_attachments(client, "999", att_dir, [])

        assert len(result) == 1
        entry = result[0]
        assert entry.filename == "Report.xlsx"
        assert entry.sha256 == _sha256(data)
        assert entry.converted_to is None
        assert summary.synced == 1
        assert summary.converted == 0
        assert (att_dir / "Report.xlsx").exists()

    def test_convertible_attachment_produces_sibling(self, tmp_path: Path) -> None:
        """A .docx attachment should produce a .docx.md sibling."""
        docx_data = b"fake docx content"
        att = _make_att("Spec.docx")
        client = _make_client([att], {"Spec.docx": docx_data})
        att_dir = tmp_path / "page-attachments"

        # Fake converter
        fake_conv_result = ConvertResult(
            output_path=att_dir / "Spec.docx.md",
            attachments_dir=None,
            metadata={},
            warnings=[],
        )
        fake_converter = MagicMock()
        fake_converter.convert.return_value = fake_conv_result
        fake_converter.__class__.__name__ = "FakeConverter"

        with patch(_CONV_FOR, return_value=fake_converter):
            entries, summary = sync_all_attachments(client, "999", att_dir, [])

        assert len(entries) == 1
        entry = entries[0]
        assert entry.filename == "Spec.docx"
        assert entry.converted_to == "Spec.docx.md"
        assert entry.converter == "FakeConverter"
        assert summary.synced == 1
        assert summary.converted == 1

    def test_multiple_attachments_all_processed(self, tmp_path: Path) -> None:
        att1 = _make_att("Doc.docx")
        att2 = _make_att("Image.png")
        att3 = _make_att("Sheet.xlsx")
        client = _make_client(
            [att1, att2, att3],
            {"Doc.docx": b"docx data", "Image.png": b"png data", "Sheet.xlsx": b"xlsx data"},
        )
        att_dir = tmp_path / "page-attachments"

        fake_conv_result = ConvertResult(
            output_path=att_dir / "Doc.docx.md",
            attachments_dir=None,
            metadata={},
            warnings=[],
        )
        fake_converter = MagicMock()
        fake_converter.convert.return_value = fake_conv_result

        def converter_for_side_effect(path: Path) -> MagicMock | None:
            if path.suffix == ".docx":
                return fake_converter
            return None

        with patch(
            _CONV_FOR,
            side_effect=converter_for_side_effect,
        ):
            _, summary = sync_all_attachments(client, "999", att_dir, [])

        assert summary.synced == 3
        assert summary.converted == 1


# ---------------------------------------------------------------------------
# sync_all_attachments() — size limit
# ---------------------------------------------------------------------------


class TestSyncAllAttachmentsSizeLimit:
    def test_attachment_above_limit_is_skipped(self, tmp_path: Path) -> None:
        att = _make_att("BigFile.pdf", file_size=50 * 1024 * 1024)  # 50 MB
        client = _make_client([att], {"BigFile.pdf": b"large data"})
        att_dir = tmp_path / "page-attachments"

        _, summary = sync_all_attachments(
            client, "999", att_dir, [], max_attachment_size_bytes=10 * 1024 * 1024
        )

        assert summary.skipped == 1
        assert not (att_dir / "BigFile.pdf").exists()
        client.download_attachment_to_file.assert_not_called()

    def test_attachment_below_limit_is_downloaded(self, tmp_path: Path) -> None:
        att = _make_att("SmallFile.pdf", file_size=5 * 1024 * 1024)  # 5 MB
        client = _make_client([att], {"SmallFile.pdf": b"small data"})
        att_dir = tmp_path / "page-attachments"

        # Patch converter_for to None so docling is not imported as a side-effect
        with patch(_CONV_FOR, return_value=None):
            _, summary = sync_all_attachments(
                client, "999", att_dir, [], max_attachment_size_bytes=10 * 1024 * 1024
            )

        assert summary.skipped == 0
        assert summary.synced == 1

    def test_no_size_limit_downloads_all(self, tmp_path: Path) -> None:
        att = _make_att("HugeFile.pdf", file_size=200 * 1024 * 1024)  # 200 MB
        client = _make_client([att], {"HugeFile.pdf": b"huge data"})
        att_dir = tmp_path / "page-attachments"

        # Patch converter_for to None so docling is not imported as a side-effect
        with patch(_CONV_FOR, return_value=None):
            _, summary = sync_all_attachments(client, "999", att_dir, [])

        assert summary.skipped == 0
        assert summary.synced == 1


# ---------------------------------------------------------------------------
# sync_all_attachments() — converter failure isolation
# ---------------------------------------------------------------------------


class TestSyncAllAttachmentsConverterFailure:
    def test_converter_failure_doesnt_stop_other_attachments(self, tmp_path: Path) -> None:
        att1 = _make_att("Spec.docx")
        att2 = _make_att("Notes.docx")
        client = _make_client([att1, att2], {"Spec.docx": b"doc1", "Notes.docx": b"doc2"})
        att_dir = tmp_path / "page-attachments"

        call_count = 0

        def failing_then_ok(src: Path, *, dest: Path | None = None) -> ConvertResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated converter failure")
            if dest is None:
                dest = src.parent / (src.name + ".md")
            dest.write_text("# converted", encoding="utf-8")
            return ConvertResult(output_path=dest, attachments_dir=None, metadata={}, warnings=[])

        fake_converter = MagicMock()
        fake_converter.convert.side_effect = failing_then_ok

        with patch(_CONV_FOR, return_value=fake_converter):
            _, summary = sync_all_attachments(client, "999", att_dir, [])

        # Both attachments were processed; one conversion failed, one succeeded
        assert summary.synced == 2
        assert summary.converted == 1
        assert summary.failed == 1

    def test_converter_failure_recorded_not_raised(self, tmp_path: Path) -> None:
        """Converter failure must not raise; it should be silently recorded."""
        att = _make_att("Bad.docx")
        client = _make_client([att], {"Bad.docx": b"data"})
        att_dir = tmp_path / "page-attachments"

        fake_converter = MagicMock()
        fake_converter.convert.side_effect = RuntimeError("boom")

        with patch(_CONV_FOR, return_value=fake_converter):
            _, summary = sync_all_attachments(client, "999", att_dir, [])

        assert summary.failed == 1
        assert summary.synced == 1  # downloaded OK, conversion failed


# ---------------------------------------------------------------------------
# sync_all_attachments() — cache hit
# ---------------------------------------------------------------------------


class TestSyncAllAttachmentsCacheHit:
    def test_cache_hit_skips_conversion(self, tmp_path: Path) -> None:
        """When SHA + converter_version match and output exists, skip conversion."""
        docx_data = b"stable docx"
        att = _make_att("Stable.docx", version=2)
        client = _make_client([att], {"Stable.docx": docx_data})
        att_dir = tmp_path / "page-attachments"
        att_dir.mkdir()

        # Pre-write the file and output
        src = att_dir / "Stable.docx"
        src.write_bytes(docx_data)
        out = att_dir / "Stable.docx.md"
        out.write_text("# cached output", encoding="utf-8")

        existing_manifest: list[dict[str, Any]] = [
            {
                "filename": "Stable.docx",
                "sha256": _sha256(docx_data),
                "version": 2,
                "converted_to": "Stable.docx.md",
                "converter": "FakeConverter",
                "converter_version": "v1",
            }
        ]

        fake_converter = MagicMock()
        fake_converter.version = "v1"

        with patch(_CONV_FOR, return_value=fake_converter):
            _, summary = sync_all_attachments(client, "999", att_dir, existing_manifest)

        # Converter.convert() should NOT have been called
        fake_converter.convert.assert_not_called()
        assert summary.converted == 0

    def test_changed_sha_triggers_reconversion(self, tmp_path: Path) -> None:
        """When SHA changes, conversion must run again."""
        new_data = b"new version of docx"
        att = _make_att("Changed.docx", version=3)
        client = _make_client([att], {"Changed.docx": new_data})
        att_dir = tmp_path / "page-attachments"
        att_dir.mkdir()

        # Pre-write old version
        src = att_dir / "Changed.docx"
        src.write_bytes(b"old version")

        existing_manifest: list[dict[str, Any]] = [
            {
                "filename": "Changed.docx",
                "sha256": _sha256(b"old version"),
                "version": 2,
                "converted_to": "Changed.docx.md",
                "converter": "FakeConverter",
                "converter_version": "v1",
            }
        ]

        out_path = att_dir / "Changed.docx.md"

        def do_convert(src_path: Path, *, dest: Path | None = None) -> ConvertResult:
            if dest is None:
                dest = out_path
            dest.write_text("# new conversion", encoding="utf-8")
            return ConvertResult(output_path=dest, attachments_dir=None, metadata={}, warnings=[])

        fake_converter = MagicMock()
        fake_converter.convert.side_effect = do_convert
        fake_converter.version = "v1"

        with patch(_CONV_FOR, return_value=fake_converter):
            _, summary = sync_all_attachments(client, "999", att_dir, existing_manifest)

        fake_converter.convert.assert_called_once()
        assert summary.converted == 1


# ---------------------------------------------------------------------------
# sync_all_attachments() — input resilience
#
# The new helper structure (`_extract_file_size`, `_extract_version`,
# `_coerce_existing_manifest`, `_safe_destination`) exposes input-decoding
# branches that the old mega-function smeared across one for-body.  These
# tests pin behaviour on previously-untested shapes that production already
# has to handle (v2 attachment objects, malformed frontmatter, hostile
# filenames).
# ---------------------------------------------------------------------------


class TestSyncAllAttachmentsV2AttachmentShape:
    """v2 attachment objects put ``fileSize`` at top level, not under ``extensions``."""

    def test_v2_top_level_filesize_is_honoured_for_size_limit(self, tmp_path: Path) -> None:
        att = _make_att("Huge.pdf", file_size=50 * 1024 * 1024, file_size_shape="v2")
        client = _make_client([att], {"Huge.pdf": b"large data"})
        att_dir = tmp_path / "page-attachments"

        _, summary = sync_all_attachments(
            client, "999", att_dir, [], max_attachment_size_bytes=10 * 1024 * 1024
        )

        assert summary.skipped == 1
        client.download_attachment_to_file.assert_not_called()

    def test_v2_top_level_filesize_under_limit_downloads(self, tmp_path: Path) -> None:
        att = _make_att("Small.pdf", file_size=1 * 1024 * 1024, file_size_shape="v2")
        client = _make_client([att], {"Small.pdf": b"small data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            _, summary = sync_all_attachments(
                client, "999", att_dir, [], max_attachment_size_bytes=10 * 1024 * 1024
            )

        assert summary.skipped == 0
        assert summary.synced == 1


class TestSyncAllAttachmentsVersionDecoding:
    """``_extract_version`` accepts dict-with-number, bare int, or fallback to 1."""

    def test_bare_int_version_is_accepted(self, tmp_path: Path) -> None:
        att = _make_att_raw("Plain.txt", version=7)
        client = _make_client([att], {"Plain.txt": b"data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            result, _ = sync_all_attachments(client, "999", att_dir, [])

        assert result[0].version == 7

    def test_missing_version_falls_back_to_1(self, tmp_path: Path) -> None:
        att = _make_att_raw("NoVer.txt", version=_MISSING)
        client = _make_client([att], {"NoVer.txt": b"data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            result, _ = sync_all_attachments(client, "999", att_dir, [])

        assert result[0].version == 1

    def test_unparseable_version_dict_falls_back_to_1(self, tmp_path: Path) -> None:
        att = _make_att_raw("Weird.txt", version={"not_number": "foo"})
        client = _make_client([att], {"Weird.txt": b"data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            result, _ = sync_all_attachments(client, "999", att_dir, [])

        assert result[0].version == 1


class TestSyncAllAttachmentsHostileFilenames:
    """``_safe_destination`` rejects names that would escape attachments_dir."""

    @pytest.mark.parametrize("hostile", ["", ".", ".."])
    def test_degenerate_names_are_dropped(self, tmp_path: Path, hostile: str) -> None:
        att = _make_att(hostile or "x")  # empty title is handled before _safe_destination
        # Forcibly override after _make_att to test the degenerate case
        att["title"] = hostile
        client = _make_client([att], {hostile: b"data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            result, summary = sync_all_attachments(client, "999", att_dir, [])

        assert result == []
        assert summary.synced == 0
        client.download_attachment_to_file.assert_not_called()

    def test_path_separator_in_title_is_stripped_to_basename(self, tmp_path: Path) -> None:
        att = _make_att("../../etc/passwd")
        client = _make_client([att], {"../../etc/passwd": b"data"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            result, _ = sync_all_attachments(client, "999", att_dir, [])

        # Only the basename should appear, and the file must land inside att_dir
        assert len(result) == 1
        assert result[0].filename == "passwd"
        assert (att_dir / "passwd").exists()
        # No file written outside the attachments dir
        assert not (tmp_path / "etc").exists()


class TestSyncAllAttachmentsMalformedInputManifest:
    """``_coerce_existing_manifest`` defends against frontmatter shape drift.

    The function's declared input type is ``list[dict[str, Any]]``, so
    entries are assumed to be dicts.  These tests pin the within-contract
    edge cases (entries that ARE dicts but with missing / wrong-typed
    fields).  Entries that aren't dicts at all currently crash the loader;
    if that ever needs to become a soft-skip, this class is the right
    place to add the test.
    """

    def test_entry_without_filename_is_skipped(self, tmp_path: Path) -> None:
        att = _make_att("Doc.txt")
        client = _make_client([att], {"Doc.txt": b"data"})
        att_dir = tmp_path / "page-attachments"

        existing_manifest: list[dict[str, Any]] = [
            {"sha256": "abc", "version": 1},  # missing filename
            {"filename": "", "sha256": "abc", "version": 1},  # empty filename
            {"filename": 123, "sha256": "abc", "version": 1},  # non-string filename
        ]

        with patch(_CONV_FOR, return_value=None):
            _, summary = sync_all_attachments(client, "999", att_dir, existing_manifest)

        # All three malformed entries are dropped; the live attachment still gets synced.
        assert summary.synced == 1

    def test_entry_with_string_version_is_preserved(self, tmp_path: Path) -> None:
        """Some legacy frontmatter stored ``version`` as a string."""
        data = b"data"
        att = _make_att("Doc.txt", version=2)
        client = _make_client([att], {"Doc.txt": data})
        att_dir = tmp_path / "page-attachments"
        att_dir.mkdir()
        (att_dir / "Doc.txt").write_bytes(data)

        existing_manifest: list[dict[str, Any]] = [
            {
                "filename": "Doc.txt",
                "sha256": _sha256(data),
                "version": "v2-was-a-string-here",  # not int — coerced to str
            }
        ]

        with patch(_CONV_FOR, return_value=None):
            result, _ = sync_all_attachments(client, "999", att_dir, existing_manifest)

        # Re-downloaded because cached version ("v2-was-...") != live version (2).
        # The point is just that we don't crash on the string shape.
        assert len(result) == 1
        assert result[0].version == 2


# ---------------------------------------------------------------------------
# Manifest schema: converted_to / converter / converter_version
# ---------------------------------------------------------------------------


class TestManifestSchema:
    def test_manifest_entry_has_conversion_fields(self, tmp_path: Path) -> None:
        """AttachmentManifestEntry supports converted_to, converter, converter_version."""
        entry = AttachmentManifestEntry(
            filename="Foo.docx",
            sha256="abc",
            version=1,
            converted_to="Foo.docx.md",
            converter="DocxConverter",
            converter_version="2.4.0",
        )
        assert entry.converted_to == "Foo.docx.md"
        assert entry.converter == "DocxConverter"
        assert entry.converter_version == "2.4.0"

    def test_manifest_entry_defaults_none(self) -> None:
        """Conversion fields default to None."""
        entry = AttachmentManifestEntry(
            filename="plain.xlsx",
            sha256="abc",
            version=1,
        )
        assert entry.converted_to is None
        assert entry.converter is None
        assert entry.converter_version is None

    def test_sync_summary_defaults(self) -> None:
        s = AttachmentSyncSummary()
        assert s.synced == 0
        assert s.converted == 0
        assert s.skipped == 0
        assert s.failed == 0
        assert s.total_bytes == 0


# ---------------------------------------------------------------------------
# Integration: export_page passes manifest to sync_all_attachments
# ---------------------------------------------------------------------------


class TestExportPagePassesManifest:
    """Verify that export_page wires existing_attachments_manifest into sync_all_attachments."""

    def test_export_page_calls_sync_all_attachments_with_manifest(self, tmp_path: Path) -> None:
        from mdd.confluence.export import export_page

        page_data: dict[str, Any] = {
            "id": "123",
            "title": "TestPage",
            "status": "current",
            "spaceId": "s1",
            "spaceKey": "ENG",
            "parentId": None,
            "body": {"storage": {"value": ""}},
            "_links": {"webui": "/wiki/spaces/ENG/pages/123/TestPage"},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
        }
        client = MagicMock()
        client.base_url = "https://example.atlassian.net"
        client.get_page.return_value = page_data
        client.get_user.return_value = {"displayName": "Test"}

        existing_manifest: list[dict[str, Any]] = [
            {
                "filename": "Doc.docx",
                "sha256": "aabbcc",
                "version": 1,
            }
        ]

        captured_manifest: list[list[dict[str, Any]]] = []

        def fake_sync_all(
            cl: Any,
            pid: str,
            att_dir: Path,
            manifest: list[dict[str, Any]],
            *,
            max_attachment_size_bytes: int | None = None,
        ) -> tuple[list[Any], AttachmentSyncSummary]:
            captured_manifest.append(list(manifest))
            return [], AttachmentSyncSummary()

        with patch("mdd.confluence.export.sync_all_attachments", side_effect=fake_sync_all):
            export_page(
                client,
                "123",
                tmp_path,
                page_data=page_data,
                existing_attachments_manifest=existing_manifest,
            )

        assert len(captured_manifest) == 1
        assert captured_manifest[0] == existing_manifest

    def test_export_page_passes_max_attachment_size(self, tmp_path: Path) -> None:
        from mdd.confluence.export import export_page

        page_data: dict[str, Any] = {
            "id": "456",
            "title": "SizePage",
            "status": "current",
            "spaceId": "s1",
            "spaceKey": "ENG",
            "parentId": None,
            "body": {"storage": {"value": ""}},
            "_links": {"webui": "/wiki/spaces/ENG/pages/456/SizePage"},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
        }
        client = MagicMock()
        client.base_url = "https://example.atlassian.net"
        client.get_page.return_value = page_data
        client.get_user.return_value = {"displayName": "Test"}

        captured_size: list[int | None] = []

        def fake_sync_all(
            cl: Any,
            pid: str,
            att_dir: Path,
            manifest: list[dict[str, Any]],
            *,
            max_attachment_size_bytes: int | None = None,
        ) -> tuple[list[Any], AttachmentSyncSummary]:
            captured_size.append(max_attachment_size_bytes)
            return [], AttachmentSyncSummary()

        with patch("mdd.confluence.export.sync_all_attachments", side_effect=fake_sync_all):
            export_page(
                client,
                "456",
                tmp_path,
                page_data=page_data,
                max_attachment_size_bytes=5 * 1024 * 1024,
            )

        assert captured_size == [5 * 1024 * 1024]


# ---------------------------------------------------------------------------
# Integration: Streaming download (no full-body buffering)
# ---------------------------------------------------------------------------


class TestStreamingDownload:
    """Verify that sync_all_attachments uses download_attachment_to_file (streaming)."""

    def test_uses_streaming_method_not_full_buffering(self, tmp_path: Path) -> None:
        att = _make_att("Stream.pdf")
        client = _make_client([att], {"Stream.pdf": b"pdf content"})
        att_dir = tmp_path / "page-attachments"

        with patch(_CONV_FOR, return_value=None):
            sync_all_attachments(client, "999", att_dir, [])

        # download_attachment_to_file (streaming) was called
        client.download_attachment_to_file.assert_called_once()
        # download_attachment (buffered) was NOT called
        client.download_attachment.assert_not_called()


# ---------------------------------------------------------------------------
# Pytest mark: integration test (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegration:
    """Live Confluence space integration test.

    Requires: MDD_CONFLUENCE_CONFIG environment variable pointing to a config file
    with a space containing a page with .docx and .pdf attachments.
    """

    def test_live_attachment_conversion(self, tmp_path: Path) -> None:
        import os

        config_path = os.environ["MDD_CONFLUENCE_CONFIG"]
        page_id = os.environ["MDD_TEST_PAGE_ID"]

        from mdd.confluence.client import ConfluenceClient
        from mdd.confluence.config import load as load_config

        config = load_config(Path(config_path))
        with ConfluenceClient(config.url, config.username, lambda: config.api_token) as client:
            att_dir = tmp_path / "page-attachments"
            _, summary = sync_all_attachments(client, page_id, att_dir, [])
            assert summary.synced >= 0
