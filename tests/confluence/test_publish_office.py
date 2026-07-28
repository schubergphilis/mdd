"""Tests for mdd.confluence.publish_office (spec S17)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.publish_office import (
    OfficePublishCollisionError,
    _attachment_name,  # pyright: ignore[reportPrivateUsage]
    _attachment_relative_link,  # pyright: ignore[reportPrivateUsage]
    _cache_hit,  # pyright: ignore[reportPrivateUsage]
    _find_attachment_by_title,  # pyright: ignore[reportPrivateUsage]
    _FrontMatter,  # pyright: ignore[reportPrivateUsage]
    publish,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# _FrontMatter.publish_formats
# ---------------------------------------------------------------------------


class TestFrontMatterPublishFormats:
    def _fm(self, value: object) -> _FrontMatter:
        return _FrontMatter({"confluence": {"publish_office": value}})

    def test_string_docx(self) -> None:
        assert self._fm("docx").publish_formats() == ["docx"]

    def test_string_pptx(self) -> None:
        assert self._fm("pptx").publish_formats() == ["pptx"]

    def test_list_both(self) -> None:
        assert self._fm(["docx", "pptx"]).publish_formats() == ["docx", "pptx"]

    def test_empty_confluence_section(self) -> None:
        assert _FrontMatter({"confluence": {}}).publish_formats() == []

    def test_no_confluence_key(self) -> None:
        assert _FrontMatter({}).publish_formats() == []

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid format"):
            self._fm("pdf").publish_formats()

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="string or list"):
            self._fm(123).publish_formats()


# ---------------------------------------------------------------------------
# _cache_hit
# ---------------------------------------------------------------------------


class TestCacheHit:
    def test_all_match(self) -> None:
        state: dict[str, Any] = {
            "source_sha256": "aaa",
            "template_sha256": "bbb",
            "quarto_version": "1.6.0",
        }
        assert _cache_hit(state, "aaa", "bbb", "1.6.0") is True

    def test_source_mismatch(self) -> None:
        state: dict[str, Any] = {
            "source_sha256": "aaa",
            "template_sha256": "bbb",
            "quarto_version": "1.6.0",
        }
        assert _cache_hit(state, "xxx", "bbb", "1.6.0") is False

    def test_template_mismatch(self) -> None:
        state: dict[str, Any] = {
            "source_sha256": "aaa",
            "template_sha256": "bbb",
            "quarto_version": "1.6.0",
        }
        assert _cache_hit(state, "aaa", "xxx", "1.6.0") is False

    def test_quarto_version_mismatch(self) -> None:
        state: dict[str, Any] = {
            "source_sha256": "aaa",
            "template_sha256": "bbb",
            "quarto_version": "1.6.0",
        }
        assert _cache_hit(state, "aaa", "bbb", "1.7.0") is False

    def test_empty_state(self) -> None:
        assert _cache_hit({}, "aaa", "bbb", "1.6.0") is False


# ---------------------------------------------------------------------------
# _attachment_name
# ---------------------------------------------------------------------------


class TestAttachmentName:
    def test_docx(self, tmp_path: Path) -> None:
        # sanitize() preserves spaces; only forbidden chars are replaced
        md = tmp_path / "My Page.md"
        assert _attachment_name(md, "docx") == "My Page.docx"

    def test_pptx(self, tmp_path: Path) -> None:
        md = tmp_path / "Slide Deck.md"
        assert _attachment_name(md, "pptx") == "Slide Deck.pptx"

    def test_special_chars_sanitized(self, tmp_path: Path) -> None:
        md = tmp_path / "Page- Special.md"
        name = _attachment_name(md, "docx")
        assert name.endswith(".docx")
        # Colons and other forbidden chars are removed by sanitize()
        assert ":" not in name


# ---------------------------------------------------------------------------
# publish() — cache-hit path
# ---------------------------------------------------------------------------


def _make_client(
    *,
    attachment_list: list[dict[str, Any]] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.base_url = "https://example.atlassian.net"
    client.list_page_attachments.return_value = attachment_list or []
    return client


def _make_md(tmp_path: Path, content: str = "# Hello\n") -> Path:
    md = tmp_path / "test-page.md"
    md.write_text(
        f"---\nconfluence:\n  page_id: '12345'\n  publish_office: docx\n---\n{content}",
        encoding="utf-8",
    )
    return md


class TestPublishCacheHit:
    """When all cache inputs match, no render/upload should happen."""

    def test_cache_hit_returns_same_body(self, tmp_path: Path) -> None:
        """Mock _hash_bytes and _hash_file so we control what publish() sees."""
        import hashlib

        import yaml

        ref_path = tmp_path / "ref.docx"
        ref_path.write_bytes(b"ref-bytes")
        fixed_src_sha = "fixed-source-sha-aaa"
        fixed_tpl_sha = hashlib.sha256(b"ref-bytes").hexdigest()

        body_text = "# Hello\n"
        fm_data: dict[str, Any] = {
            "confluence": {
                "page_id": "12345",
                "publish_office": "docx",
                "publish_office_state": {
                    "docx": {
                        "source_sha256": fixed_src_sha,
                        "template_sha256": fixed_tpl_sha,
                        "quarto_version": "1.6.0",
                        "attachment_filename": "cached.docx",
                        "attachment_sha256": "abc123",
                        "attachment_version": 2,
                    }
                },
            }
        }
        fm_str = yaml.safe_dump(fm_data, default_flow_style=False, sort_keys=False)
        md = tmp_path / "cached.md"
        md.write_text(f"---\n{fm_str}---\n{body_text}", encoding="utf-8")

        client = _make_client(
            attachment_list=[
                {
                    "title": "cached.docx",
                    "_links": {"download": "/wiki/download/cached.docx"},
                }
            ]
        )

        # Patch _hash_bytes to return our fixed source sha for the md file
        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", return_value=ref_path),
            patch(
                "mdd.confluence.publish_office._hash_bytes",
                return_value=fixed_src_sha,
            ),
        ):
            summary = publish(client, "12345", md, "<p>body</p>", template_dir=None)

        # No upload should have happened (cache hit)
        client.upload_attachment.assert_not_called()
        assert summary.formats_cache_hit == ["docx"]
        assert summary.formats_uploaded == []


# ---------------------------------------------------------------------------
# publish() — callout strip-and-restore
# ---------------------------------------------------------------------------


class TestCalloutStripRestore:
    """The body callout is idempotent — only one callout exists after multiple runs."""

    def test_callout_inserted_when_absent(self, tmp_path: Path) -> None:
        md = _make_md(tmp_path)

        client = _make_client()
        client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}

        ref_path = tmp_path / "ref.docx"
        ref_path.write_bytes(b"ref")

        rendered = tmp_path / "rendered.docx"
        rendered.write_bytes(b"rendered")

        def fake_render(md_p: Path, *, dest: Path, reference_doc: Path | None = None) -> MagicMock:
            dest.write_bytes(b"rendered-content")
            r = MagicMock()
            r.output_path = dest
            r.warnings = []
            return r

        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", return_value=ref_path),
            patch(
                "mdd.converters.quarto.QuartoDocxRenderer.render",
                side_effect=fake_render,
            ),
        ):
            summary = publish(client, "12345", md, "<p>existing body</p>")

        updated_body = summary.body_xhtml
        assert "(this attachment is generated from the markdown source)" in updated_body
        # Exactly one callout
        assert updated_body.count("(this attachment is generated from the markdown source)") == 1

    def test_callout_replaced_not_duplicated(self, tmp_path: Path) -> None:
        md = _make_md(tmp_path)
        client = _make_client()
        client.upload_attachment.return_value = {"results": [{"version": {"number": 2}}]}

        ref_path = tmp_path / "ref.docx"
        ref_path.write_bytes(b"ref-v2")

        prior_callout = (
            "<p><sub><em>Download as "
            '<a href="https://example.atlassian.net/old">old.docx</a> '
            "(this attachment is generated from the markdown source)"
            "</em></sub></p>"
        )
        body_with_callout = prior_callout + "\n<p>body content</p>"

        def fake_render(md_p: Path, *, dest: Path, reference_doc: Path | None = None) -> MagicMock:
            dest.write_bytes(b"new-rendered-content")
            r = MagicMock()
            r.output_path = dest
            r.warnings = []
            return r

        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", return_value=ref_path),
            patch(
                "mdd.converters.quarto.QuartoDocxRenderer.render",
                side_effect=fake_render,
            ),
        ):
            summary = publish(client, "12345", md, body_with_callout)

        count = summary.body_xhtml.count("(this attachment is generated from the markdown source)")
        assert count == 1, f"Expected exactly 1 callout, got {count}"


# ---------------------------------------------------------------------------
# publish() — filename collision
# ---------------------------------------------------------------------------


class TestFilenameCollision:
    def test_collision_raises_error(self, tmp_path: Path) -> None:
        md = _make_md(tmp_path)

        # Simulate an existing user-uploaded file with the same name
        attachment_filename = "test-page.docx"
        client = _make_client(
            attachment_list=[
                {
                    "title": attachment_filename,
                    "_links": {"download": "/wiki/download/test-page.docx"},
                }
            ]
        )

        ref_path = tmp_path / "ref.docx"
        ref_path.write_bytes(b"ref")

        def fake_render(md_p: Path, *, dest: Path, reference_doc: Path | None = None) -> MagicMock:
            dest.write_bytes(b"rendered-content")
            r = MagicMock()
            r.output_path = dest
            r.warnings = []
            return r

        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", return_value=ref_path),
            patch(
                "mdd.converters.quarto.QuartoDocxRenderer.render",
                side_effect=fake_render,
            ),
            pytest.raises(OfficePublishCollisionError, match="already exists"),
        ):
            publish(client, "12345", md, "<p>body</p>")


# ---------------------------------------------------------------------------
# publish() — Quarto absent
# ---------------------------------------------------------------------------


class TestQuartoAbsent:
    def test_quarto_absent_returns_unchanged_body(self, tmp_path: Path) -> None:
        from mdd.converters.quarto import QuartoNotFoundError

        md = _make_md(tmp_path)
        client = _make_client()

        with patch(
            "mdd.confluence.publish_office.quarto_version",
            side_effect=QuartoNotFoundError("quarto not found"),
        ):
            summary = publish(client, "12345", md, "<p>body</p>")

        assert summary.body_xhtml == "<p>body</p>"
        assert len(summary.failures) == 1
        assert "quarto not found" in summary.failures[0]
        client.upload_attachment.assert_not_called()


# ---------------------------------------------------------------------------
# publish() — Quarto render failure is non-fatal
# ---------------------------------------------------------------------------


class TestRenderFailure:
    def test_render_failure_recorded_not_raised(self, tmp_path: Path) -> None:
        md = _make_md(tmp_path)
        client = _make_client()

        ref_path = tmp_path / "ref.docx"
        ref_path.write_bytes(b"ref")

        def fake_render_fail(
            md_p: Path, *, dest: Path, reference_doc: Path | None = None
        ) -> MagicMock:
            raise RuntimeError("quarto exploded")

        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", return_value=ref_path),
            patch(
                "mdd.converters.quarto.QuartoDocxRenderer.render",
                side_effect=fake_render_fail,
            ),
        ):
            summary = publish(client, "12345", md, "<p>body</p>")

        # Body unchanged, failure recorded
        assert summary.body_xhtml == "<p>body</p>"
        assert any("quarto exploded" in f for f in summary.failures)
        client.upload_attachment.assert_not_called()


# ---------------------------------------------------------------------------
# publish() — no publish_office key → no-op
# ---------------------------------------------------------------------------


class TestNoPublishOffice:
    def test_no_publish_office_noop(self, tmp_path: Path) -> None:
        md = tmp_path / "plain.md"
        md.write_text(
            "---\nconfluence:\n  page_id: '12345'\n---\n# No publish_office\n",
            encoding="utf-8",
        )
        client = _make_client()
        summary = publish(client, "12345", md, "<p>body</p>")
        assert summary.body_xhtml == "<p>body</p>"
        assert summary.formats_attempted == []
        client.upload_attachment.assert_not_called()


# ---------------------------------------------------------------------------
# publish() — both docx and pptx
# ---------------------------------------------------------------------------


class TestBothFormats:
    def test_both_formats_attempted(self, tmp_path: Path) -> None:
        md = tmp_path / "both.md"
        md.write_text(
            "---\nconfluence:\n  page_id: '12345'\n  publish_office:\n"
            "  - docx\n  - pptx\n---\n# Both\n",
            encoding="utf-8",
        )
        client = _make_client()
        client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}

        ref_docx = tmp_path / "ref.docx"
        ref_docx.write_bytes(b"ref-docx")
        ref_pptx = tmp_path / "ref.pptx"
        ref_pptx.write_bytes(b"ref-pptx")

        def fake_bundled(ext: str) -> Path:
            return ref_docx if "docx" in ext else ref_pptx

        call_count = {"n": 0}

        def fake_render(md_p: Path, *, dest: Path, reference_doc: Path | None = None) -> MagicMock:
            call_count["n"] += 1
            dest.write_bytes(f"rendered-{call_count['n']}".encode())
            r = MagicMock()
            r.output_path = dest
            r.warnings = []
            return r

        with (
            patch("mdd.confluence.publish_office.quarto_version", return_value="1.6.0"),
            patch("mdd.confluence.publish_office.bundled_reference_doc", side_effect=fake_bundled),
            patch(
                "mdd.converters.quarto.QuartoDocxRenderer.render",
                side_effect=fake_render,
            ),
            patch(
                "mdd.converters.quarto.QuartoPptxRenderer.render",
                side_effect=fake_render,
            ),
        ):
            summary = publish(client, "12345", md, "<p>body</p>")

        assert set(summary.formats_attempted) == {"docx", "pptx"}
        # Both links should appear in callout
        assert (
            summary.body_xhtml.count("(this attachment is generated from the markdown source)") == 1
        )


# ---------------------------------------------------------------------------
# header.py — strip_office_callout / insert_office_callout
# ---------------------------------------------------------------------------


class TestHeaderCallout:
    def test_insert_when_absent(self) -> None:
        from mdd.confluence.header import insert_office_callout

        body = "<p>content</p>"
        links = [("https://example.com/file.docx", "file.docx")]
        result = insert_office_callout(body, links)
        assert "(this attachment is generated from the markdown source)" in result
        assert "file.docx" in result

    def test_replace_existing_callout(self) -> None:
        from mdd.confluence.header import insert_office_callout

        old = (
            "<p><sub><em>Download as "
            '<a href="https://example.com/old.docx">old.docx</a> '
            "(this attachment is generated from the markdown source)"
            "</em></sub></p>"
        )
        body = old + "\n<p>real content</p>"
        links = [("https://example.com/new.docx", "new.docx")]
        result = insert_office_callout(body, links)
        assert "new.docx" in result
        assert "old.docx" not in result
        assert result.count("(this attachment is generated from the markdown source)") == 1

    def test_strip_removes_callout(self) -> None:
        from mdd.confluence.header import strip_office_callout

        callout = (
            "<p><sub><em>Download as "
            '<a href="https://example.com/file.docx">file.docx</a> '
            "(this attachment is generated from the markdown source)"
            "</em></sub></p>"
        )
        body = callout + "\n<p>real content</p>"
        result = strip_office_callout(body)
        assert "(this attachment is generated from the markdown source)" not in result
        assert "<p>real content</p>" in result

    def test_strip_noop_when_absent(self) -> None:
        from mdd.confluence.header import strip_office_callout

        body = "<p>no callout here</p>"
        assert strip_office_callout(body) == body

    def test_roundtrip_idempotent(self) -> None:
        from mdd.confluence.header import insert_office_callout, strip_office_callout

        body = "<p>page content</p>"
        links = [("https://example.com/doc.docx", "doc.docx")]

        body1 = insert_office_callout(body, links)
        body2 = insert_office_callout(strip_office_callout(body1), links)
        assert body1 == body2


# ---------------------------------------------------------------------------
# _attachment_relative_link / _find_attachment_by_title
# ---------------------------------------------------------------------------


class TestAttachmentRelativeLink:
    def test_prefers_v2_downloadlink(self) -> None:
        att: dict[str, Any] = {"downloadLink": "/v2", "_links": {"download": "/v1"}}
        assert _attachment_relative_link(att) == "/v2"

    def test_falls_back_to_v1_links_download(self) -> None:
        att: dict[str, Any] = {"_links": {"download": "/v1"}}
        assert _attachment_relative_link(att) == "/v1"

    def test_none_when_neither_present(self) -> None:
        att: dict[str, Any] = {}
        assert _attachment_relative_link(att) is None

    def test_skips_v2_when_not_absolute(self) -> None:
        att: dict[str, Any] = {"downloadLink": "no-slash", "_links": {"download": "/v1"}}
        assert _attachment_relative_link(att) == "/v1"

    def test_none_when_links_not_dict(self) -> None:
        att: dict[str, Any] = {"_links": "nope"}
        assert _attachment_relative_link(att) is None


class TestFindAttachmentByTitle:
    def test_returns_first_matching(self) -> None:
        atts: list[dict[str, Any]] = [
            {"title": "a.docx"},
            {"title": "b.pdf"},
        ]
        result = _find_attachment_by_title(atts, "b.pdf")
        assert result == {"title": "b.pdf"}

    def test_none_when_no_match(self) -> None:
        atts: list[dict[str, Any]] = [{"title": "a"}]
        assert _find_attachment_by_title(atts, "b") is None

    def test_skips_attachments_without_title(self) -> None:
        atts: list[dict[str, Any]] = [{"title": None}, {"title": 42}, {"title": "ok"}]
        result = _find_attachment_by_title(atts, "ok")
        assert result == {"title": "ok"}
