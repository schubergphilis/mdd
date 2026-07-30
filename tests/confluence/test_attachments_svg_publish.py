"""Tests for SVG->PNG rasterization on Confluence publish.

``sync_attachments_for_update`` (the update-page/create-page attachment
upload path) historically uploaded every locally-referenced file
byte-for-byte, including ``.svg`` — but Confluence Cloud never renders SVG
attachments inline, so a page authored with a local SVG diagram published as
a broken/undisplayed image. These tests exercise the fix: an SVG referenced
as a markdown *image* is rasterized to PNG (via a mocked ``SvgToPngConverter``),
the PNG is uploaded as an extra attachment, and the rendered body is rewritten
to a ``confluence-attachment:`` URI for the PNG.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from mdd.confluence.attachments import AttachmentManifestEntry, sync_attachments_for_update
from mdd.converters.protocol import ConvertResult

if TYPE_CHECKING:
    from pathlib import Path

_SVG_CONVERTER = "mdd.confluence.attachments.svg_publish.SvgToPngConverter"


def _make_client(upload_response: dict[str, Any] | None = None) -> MagicMock:
    client = MagicMock()
    if upload_response is None:
        upload_response = {"results": [{"version": {"number": 1}}]}
    client.upload_attachment.return_value = upload_response
    return client


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_fake_converter(png_path: Path, png_data: bytes) -> MagicMock:
    """A MagicMock standing in for SvgToPngConverter(), producing *png_path* on disk."""
    _write_file(png_path, png_data)
    converter = MagicMock()
    converter.convert.return_value = ConvertResult(
        output_path=png_path, attachments_dir=None, metadata={}, warnings=[]
    )
    return converter


class TestSvgImageRasterization:
    def test_plain_markdown_image_svg_is_rasterized_and_uploaded(self, tmp_path: Path) -> None:
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")
        png = tmp_path / "diagram.svg.png"
        png_data = b"\x89PNG fake bytes"

        client = _make_client()
        body_md = "![diagram](diagram.svg)"
        fake_converter = _make_fake_converter(png, png_data)

        with patch(_SVG_CONVERTER, return_value=fake_converter):
            manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        fake_converter.convert.assert_called_once_with(svg)
        # Both the raw SVG (unchanged existing behaviour) and the rasterized
        # PNG get uploaded.
        assert client.upload_attachment.call_count == 2
        uploaded_paths = {call.args[1] for call in client.upload_attachment.call_args_list}
        assert uploaded_paths == {svg, png}

        by_name = {e.filename: e for e in manifest}
        assert set(by_name) == {"diagram.svg", "diagram.svg.png"}
        assert by_name["diagram.svg.png"].sha256 == hashlib.sha256(png_data).hexdigest()

        assert rewritten_body == "![diagram](confluence-attachment:diagram.svg.png)"

    def test_confluence_attachment_svg_image_is_rasterized(self, tmp_path: Path) -> None:
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")
        png = tmp_path / "diagram.svg.png"
        fake_converter = _make_fake_converter(png, b"png bytes")

        client = _make_client()
        body_md = "![diagram](confluence-attachment:diagram.svg)"

        with patch(_SVG_CONVERTER, return_value=fake_converter):
            _manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        assert rewritten_body == "![diagram](confluence-attachment:diagram.svg.png)"

    def test_extras_and_title_preserved_on_rewrite(self, tmp_path: Path) -> None:
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")
        png = tmp_path / "diagram.svg.png"
        fake_converter = _make_fake_converter(png, b"png bytes")

        client = _make_client()
        body_md = '![diagram](confluence-attachment:diagram.svg;version-at-save=3 "align=left")'

        with patch(_SVG_CONVERTER, return_value=fake_converter):
            _manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        assert rewritten_body == (
            '![diagram](confluence-attachment:diagram.svg.png;version-at-save=3 "align=left")'
        )

    def test_svg_link_is_not_rasterized(self, tmp_path: Path) -> None:
        """A plain (non-image) attachment link is a deliberate download
        reference to the source file — it must not be rewritten to the PNG."""
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")

        client = _make_client()
        body_md = "See [the diagram source](confluence-attachment:diagram.svg) for details.\n"

        with patch(_SVG_CONVERTER) as converter_cls:
            manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        converter_cls.assert_not_called()
        assert rewritten_body == body_md
        assert len(manifest) == 1
        assert manifest[0].filename == "diagram.svg"
        client.upload_attachment.assert_called_once_with("123", svg)

    def test_non_svg_images_are_unaffected(self, tmp_path: Path) -> None:
        img = tmp_path / "photo.png"
        _write_file(img, b"png bytes")

        client = _make_client()
        body_md = "![photo](photo.png)"

        with patch(_SVG_CONVERTER) as converter_cls:
            manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        converter_cls.assert_not_called()
        assert rewritten_body == body_md
        assert len(manifest) == 1

    def test_rasterization_failure_leaves_raw_svg_ref(self, tmp_path: Path, caplog: Any) -> None:
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")

        client = _make_client()
        body_md = "![diagram](diagram.svg)"

        fake_converter = MagicMock()
        fake_converter.convert.side_effect = RuntimeError("rsvg-convert exploded")

        with (
            patch(_SVG_CONVERTER, return_value=fake_converter),
            caplog.at_level("WARNING", logger="mdd.confluence.attachments.svg_publish"),
        ):
            manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, []
            )

        # Raw SVG still uploaded via the normal (pre-existing) path.
        client.upload_attachment.assert_called_once_with("123", svg)
        assert rewritten_body == body_md
        assert len(manifest) == 1
        assert manifest[0].filename == "diagram.svg"
        assert any("rsvg-convert exploded" in r.getMessage() for r in caplog.records)

    def test_png_hash_matches_manifest_skips_reupload(self, tmp_path: Path) -> None:
        svg = tmp_path / "diagram.svg"
        _write_file(svg, b"<svg/>")
        png = tmp_path / "diagram.svg.png"
        png_data = b"stable png bytes"
        fake_converter = _make_fake_converter(png, png_data)

        existing_svg = AttachmentManifestEntry(
            filename="diagram.svg", sha256=hashlib.sha256(b"<svg/>").hexdigest(), version=1
        )
        existing_png = AttachmentManifestEntry(
            filename="diagram.svg.png", sha256=hashlib.sha256(png_data).hexdigest(), version=1
        )

        client = _make_client()
        body_md = "![diagram](diagram.svg)"

        with patch(_SVG_CONVERTER, return_value=fake_converter):
            manifest, rewritten_body = sync_attachments_for_update(
                client, "123", body_md, tmp_path, [existing_svg, existing_png]
            )

        # Both hashes match the cache: no upload at all.
        client.upload_attachment.assert_not_called()
        assert len(manifest) == 2
        assert rewritten_body == "![diagram](confluence-attachment:diagram.svg.png)"
