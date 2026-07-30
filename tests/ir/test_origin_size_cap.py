"""Tests for the ``Origin.raw_bytes`` size cap.

The cap is 256 KiB (:data:`mdd.ir.nodes.ORIGIN_RAW_BYTES_CAP`).
When a reader would record more than the cap, the dataclass drops the bytes
and flips ``raw_bytes_truncated`` to ``True``; writers then fall back to
canonical rendering for that node instead of replaying a partial slice.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mdd.confluence.ir.writer import render_confluence_storage
from mdd.ir.document import Document
from mdd.ir.nodes import (
    ORIGIN_RAW_BYTES_CAP,
    Origin,
    Paragraph,
    RawBlock,
    RawInline,
    Text,
)
from mdd.ir.serialize import from_json, to_json
from mdd.markdown.ir.reader import parse_markdown
from mdd.markdown.ir.writer import render_markdown


class TestOriginCap:
    def test_cap_value_is_256_kib(self) -> None:
        assert ORIGIN_RAW_BYTES_CAP == 256 * 1024

    def test_under_cap_keeps_raw_bytes(self) -> None:
        payload = b"x" * (ORIGIN_RAW_BYTES_CAP - 1)
        o = Origin(source_format="markdown", raw_bytes=payload)
        assert o.raw_bytes == payload
        assert o.raw_bytes_truncated is False

    def test_at_cap_keeps_raw_bytes(self) -> None:
        payload = b"x" * ORIGIN_RAW_BYTES_CAP
        o = Origin(source_format="markdown", raw_bytes=payload)
        assert o.raw_bytes == payload
        assert o.raw_bytes_truncated is False

    def test_over_cap_truncates_with_flag(self) -> None:
        payload = b"x" * (ORIGIN_RAW_BYTES_CAP + 1)
        o = Origin(source_format="confluence-storage", raw_bytes=payload)
        assert o.raw_bytes == b""
        assert o.raw_bytes_truncated is True

    def test_far_over_cap_truncates(self) -> None:
        payload = b"y" * (4 * ORIGIN_RAW_BYTES_CAP)
        o = Origin(source_format="html", raw_bytes=payload)
        assert o.raw_bytes == b""
        assert o.raw_bytes_truncated is True

    def test_truncation_preserves_other_fields(self) -> None:
        payload = b"z" * (ORIGIN_RAW_BYTES_CAP + 16)
        o = Origin(
            source_format="confluence-storage",
            raw_bytes=payload,
            leading_ws="  ",
            trailing_ws="\n",
            entity_form={1: "&hellip;"},
        )
        assert o.raw_bytes == b""
        assert o.raw_bytes_truncated is True
        assert o.leading_ws == "  "
        assert o.trailing_ws == "\n"
        assert o.entity_form == {1: "&hellip;"}


class TestOriginCapSerialization:
    def test_truncated_flag_survives_json_roundtrip(self) -> None:
        payload = b"x" * (ORIGIN_RAW_BYTES_CAP + 1)
        doc = Document(
            children=[
                Paragraph(
                    inlines=[Text("hello", origin=Origin(source_format="markdown"))],
                    origin=Origin(source_format="markdown", raw_bytes=payload),
                )
            ]
        )
        # Confirm the in-memory IR is truncated.
        para = doc.children[0]
        assert isinstance(para, Paragraph)
        assert para.origin is not None
        assert para.origin.raw_bytes_truncated is True

        json_str = to_json(doc)
        assert '"raw_bytes_truncated": true' in json_str

        round_tripped = from_json(json_str)
        para2 = round_tripped.children[0]
        assert isinstance(para2, Paragraph)
        assert para2.origin is not None
        assert para2.origin.raw_bytes_truncated is True
        assert para2.origin.raw_bytes == b""

    def test_untruncated_origin_omits_flag(self) -> None:
        o = Origin(source_format="markdown", raw_bytes=b"hello")
        doc = Document(children=[Paragraph(origin=o)])
        json_str = to_json(doc)
        assert "raw_bytes_truncated" not in json_str


class TestWriterFallback:
    """Confirm preserving-mode writers skip the byte-replay shortcut on truncated origins."""

    def test_confluence_writer_skips_truncated_raw_block(self) -> None:
        # RawBlock with an origin whose raw_bytes would have been replayed.
        # When truncated, the writer must fall back to its canonical render.
        big = b"x" * (ORIGIN_RAW_BYTES_CAP + 1)
        block = RawBlock(
            content="<p>hello</p>",
            format="confluence-storage",
            origin=Origin(source_format="confluence-storage", raw_bytes=big),
        )
        doc = Document(children=[block])
        out = render_confluence_storage(doc, mode="preserving")
        # Falls back to content (the canonical render for confluence-storage RawBlock).
        assert "<p>hello</p>" in out
        # And it definitely does not emit the (now empty) raw_bytes.
        assert "x" * 100 not in out

    def test_markdown_writer_skips_truncated_text(self) -> None:
        big = b"y" * (ORIGIN_RAW_BYTES_CAP + 1)
        text = Text(content="hello", origin=Origin(source_format="markdown", raw_bytes=big))
        para = Paragraph(inlines=[text], origin=Origin(source_format="markdown"))
        doc = Document(children=[para])
        out = render_markdown(doc, mode="preserving")
        assert "hello" in out
        assert "y" * 100 not in out

    def test_markdown_writer_skips_truncated_raw_inline(self) -> None:
        big = b"z" * (ORIGIN_RAW_BYTES_CAP + 1)
        raw = RawInline(
            content="<span>x</span>",
            format="html",
            origin=Origin(source_format="html", raw_bytes=big),
        )
        para = Paragraph(inlines=[raw], origin=Origin(source_format="markdown"))
        doc = Document(children=[para])
        out = render_markdown(doc, mode="preserving")
        assert "<span>x</span>" in out
        assert "z" * 100 not in out


class TestReaderLargePayload:
    """A real reader pass over a multi-hundred-KB blob honours the cap.

    Neither current reader populates ``raw_bytes`` from Text content directly
    (both rely on ``content`` + ``entity_form``), so we exercise the path by
    simulating a future preserving-mode capture: parse the markdown, then
    attach an oversized ``raw_bytes`` to the resulting Text via ``replace``
    and assert the dataclass enforces the cap.
    """

    @pytest.mark.parametrize("size_kb", [300, 512, 1024])
    def test_oversized_text_origin_truncates(self, size_kb: int) -> None:
        big_payload = ("a" * (size_kb * 1024)).encode("utf-8")
        # Sanity: this exceeds the cap.
        assert len(big_payload) > ORIGIN_RAW_BYTES_CAP

        md = "paragraph with some text\n"
        doc = parse_markdown(md, mode="preserving")
        para = doc.children[0]
        assert isinstance(para, Paragraph)
        text = para.inlines[0]
        assert isinstance(text, Text)
        assert text.origin is not None

        # Simulate a future preserving-mode reader stashing the source slice.
        big_origin = replace(text.origin, raw_bytes=big_payload)
        assert big_origin.raw_bytes_truncated is True
        assert big_origin.raw_bytes == b""

    def test_writer_falls_back_on_real_large_node(self) -> None:
        # End-to-end: build a document whose RawBlock carries an oversized
        # raw_bytes; ensure the preserving-mode Confluence writer ignores it
        # and uses the canonical content path instead.
        big = b"<p>" + b"x" * (ORIGIN_RAW_BYTES_CAP + 10) + b"</p>"
        rb = RawBlock(
            content="<p>fallback</p>",
            format="confluence-storage",
            origin=Origin(source_format="confluence-storage", raw_bytes=big),
        )
        out = render_confluence_storage(Document(children=[rb]), mode="preserving")
        assert "<p>fallback</p>" in out
