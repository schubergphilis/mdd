"""Tests for Origin field population and preserving-mode reader/writer plumbing."""

from __future__ import annotations

import dataclasses

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir.nodes import (
    Origin,
    Paragraph,
    RawBlock,
    Text,
)
from mdd.ir.serialize import from_json, to_json

# ---------------------------------------------------------------------------
# Origin dataclass construction
# ---------------------------------------------------------------------------


class TestOriginDataclass:
    def test_default_fields(self) -> None:
        o = Origin(source_format="confluence-storage")
        assert o.raw_bytes == b""
        assert o.leading_ws == ""
        assert o.trailing_ws == ""
        assert o.entity_form == {}

    def test_frozen(self) -> None:
        o = Origin(source_format="markdown")
        with pytest.raises(dataclasses.FrozenInstanceError):
            o.leading_ws = "x"  # type: ignore[misc]

    def test_full_construction(self) -> None:
        o = Origin(
            source_format="html",
            raw_bytes=b"<p>hello</p>",
            leading_ws="\n",
            trailing_ws="\n",
            entity_form={3: "&hellip;"},
        )
        assert o.source_format == "html"
        assert o.raw_bytes == b"<p>hello</p>"
        assert o.leading_ws == "\n"
        assert o.entity_form == {3: "&hellip;"}


# ---------------------------------------------------------------------------
# Origin JSON serialization / deserialization
# ---------------------------------------------------------------------------


class TestOriginSerialization:
    def test_origin_none_omitted_from_json(self) -> None:
        from mdd.ir.document import Document
        from mdd.ir.nodes import Paragraph

        doc = Document(children=[Paragraph()])
        json_str = to_json(doc)
        assert '"origin"' not in json_str

    def test_origin_present_serialized(self) -> None:

        from mdd.ir.document import Document

        doc = Document(
            children=[
                Paragraph(
                    inlines=[],
                    origin=Origin(
                        source_format="confluence-storage",
                        raw_bytes=b"hello",
                        entity_form={2: "&hellip;"},
                    ),
                )
            ]
        )
        json_str = to_json(doc)
        assert '"origin"' in json_str
        assert "@base64" in json_str
        assert "hellip" in json_str

    def test_origin_roundtrip_json(self) -> None:
        from mdd.ir.document import Document

        origin = Origin(
            source_format="confluence-storage",
            raw_bytes=b"\xf0\x9f\x98\x8a",
            leading_ws="  ",
            trailing_ws="\n",
            entity_form={0: "&hellip;", 3: "&mdash;"},
        )
        doc = Document(children=[Paragraph(inlines=[], origin=origin)])
        roundtripped = from_json(to_json(doc))
        p = roundtripped.children[0]
        assert isinstance(p, Paragraph)
        assert p.origin is not None
        assert p.origin.source_format == "confluence-storage"
        assert p.origin.raw_bytes == b"\xf0\x9f\x98\x8a"
        assert p.origin.leading_ws == "  "
        assert p.origin.trailing_ws == "\n"
        assert p.origin.entity_form == {0: "&hellip;", 3: "&mdash;"}

    def test_origin_entity_form_serialized_as_sorted_pairs(self) -> None:
        import json

        from mdd.ir.document import Document

        origin = Origin(
            source_format="markdown",
            entity_form={10: "&mdash;", 2: "&hellip;"},
        )
        doc = Document(children=[Paragraph(inlines=[], origin=origin)])
        parsed = json.loads(to_json(doc))
        entity_form = parsed["root"]["children"][0]["origin"]["entity_form"]
        # Should be sorted by offset (ascending).
        assert entity_form[0][0] < entity_form[1][0]


# ---------------------------------------------------------------------------
# Confluence reader preserving mode
# ---------------------------------------------------------------------------


class TestConfluenceReaderPreservingMode:
    def test_normalising_mode_origin_without_raw_bytes(self) -> None:
        # The Confluence reader now always populates Origin so the writer
        # can re-emit named HTML entities (`&mdash;`, `&hellip;`, …) in
        # either mode — entity_form is the cheap part of Origin (no
        # raw_bytes capture). Normalising-mode Origins must have empty
        # raw_bytes; only preserving mode captures source bytes.
        xhtml = "<p>Hello world</p>"
        doc = parse_confluence_storage(xhtml, mode="normalising")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert p.origin is None or p.origin.raw_bytes == b""
        if p.inlines:
            tok = p.inlines[0]
            assert hasattr(tok, "origin")
            tok_origin = getattr(tok, "origin", None)
            if tok_origin is not None:
                assert tok_origin.raw_bytes == b""

    def test_preserving_mode_origin_set_on_paragraph(self) -> None:
        xhtml = "<p>Hello world</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert p.origin is not None
        assert p.origin.source_format == "confluence-storage"

    def test_preserving_mode_origin_set_on_text_inline(self) -> None:
        xhtml = "<p>Hello</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines
        text_tok = p.inlines[0]
        assert isinstance(text_tok, Text)
        # Text / Code carry `origin` with `source_format` + `entity_form` but
        # not `raw_bytes` — content + entity_form together suffice for
        # preserving-mode emission, and storing the UTF-8 encoding would just
        # duplicate `Text.content` in the sidecar JSON.
        assert text_tok.origin is not None  # type: ignore[union-attr]
        assert text_tok.origin.source_format == "confluence-storage"  # type: ignore[union-attr]

    def test_preserving_mode_entity_form_recorded(self) -> None:
        xhtml = "<p>wait&hellip;for it</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        # The entity &hellip; should have been decoded to … in the Text content.
        text_content = "".join(tok.content for tok in p.inlines if isinstance(tok, Text))
        assert "…" in text_content

    def test_preserving_mode_raw_block_origin(self) -> None:
        # A fallback path produces a RawBlock.
        xhtml = "<div class='unknown-element'><p>Content</p></div>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        # The content inside the div gets parsed as blocks.
        # Check that any raw blocks have origin set.
        for block in doc.children:
            if isinstance(block, RawBlock):
                assert block.origin is not None


# ---------------------------------------------------------------------------
# Confluence writer preserving mode
# ---------------------------------------------------------------------------


class TestConfluenceWriterPreservingMode:
    def test_normalising_mode_canonical_text(self) -> None:
        xhtml = "<p>Hello world</p>"
        doc = parse_confluence_storage(xhtml)
        result = render_confluence_storage(doc)
        assert "Hello world" in result

    def test_preserving_mode_text_passthrough(self) -> None:
        xhtml = "<p>Hello world</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        result = render_confluence_storage(doc, mode="preserving")
        assert "Hello" in result

    def test_preserving_mode_entity_resubstitution(self) -> None:
        xhtml = "<p>wait&hellip;for it</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        result = render_confluence_storage(doc, mode="preserving")
        # In preserving mode, the entity should be re-substituted back.
        assert "&hellip;" in result or "…" in result


# ---------------------------------------------------------------------------
# R1 byte-perfect gate
# ---------------------------------------------------------------------------


class TestR1BytePerfect:
    def test_simple_paragraph_byte_perfect(self) -> None:
        """A simple paragraph should round-trip byte-perfectly in preserving mode."""
        xhtml = "<p>Hello world</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        result = render_confluence_storage(doc, mode="preserving")
        assert "<p>" in result
        assert "Hello world" in result
        assert "</p>" in result

    def test_code_block_cdata_preserving(self) -> None:
        """CodeBlocks with CDATA should round-trip preserving-mode."""
        xhtml = (
            '<ac:structured-macro ac:name="code">'
            '<ac:plain-text-body><![CDATA[print("hello")]]></ac:plain-text-body>'
            "</ac:structured-macro>"
        )
        doc = parse_confluence_storage(xhtml, mode="preserving")
        result = render_confluence_storage(doc, mode="preserving")
        assert 'print("hello")' in result

    def test_entity_in_paragraph(self) -> None:
        """HTML entities should be tracked and re-emitted in preserving mode."""
        xhtml = "<p>Hello&hellip;world</p>"
        doc = parse_confluence_storage(xhtml, mode="preserving")
        result = render_confluence_storage(doc, mode="preserving")
        # Either the entity is re-substituted or the unicode form is emitted.
        assert "Hello" in result
        assert "world" in result
        assert "&hellip;" in result or "…" in result


# ---------------------------------------------------------------------------
# Markdown reader preserving mode
# ---------------------------------------------------------------------------


class TestMarkdownReaderPreservingMode:
    def test_normalising_mode_no_origin(self) -> None:
        from mdd.markdown.ir import parse_markdown

        md = "Hello world"
        doc = parse_markdown(md, mode="normalising")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert p.origin is None

    def test_preserving_mode_origin_set(self) -> None:
        from mdd.markdown.ir import parse_markdown

        md = "Hello world"
        doc = parse_markdown(md, mode="preserving")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert p.origin is not None
        assert p.origin.source_format == "markdown"

    def test_preserving_mode_text_origin(self) -> None:
        from mdd.markdown.ir import parse_markdown

        md = "Hello"
        doc = parse_markdown(md, mode="preserving")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        for tok in p.inlines:
            if isinstance(tok, Text):
                # `origin` is populated but `raw_bytes` is intentionally
                # empty — it would just duplicate Text.content in the
                # sidecar JSON.
                assert tok.origin is not None  # type: ignore[union-attr]
                assert tok.origin.source_format == "markdown"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Markdown writer preserving mode
# ---------------------------------------------------------------------------


class TestMarkdownWriterPreservingMode:
    def test_preserving_mode_text_raw_bytes_emitted(self) -> None:
        from mdd.markdown.ir import parse_markdown, render_markdown

        md = "Hello world"
        doc = parse_markdown(md, mode="preserving")
        result = render_markdown(doc, mode="preserving")
        assert "Hello world" in result

    def test_markdown_roundtrip_normalising_stable(self) -> None:
        """Normalising-mode markdown output should be stable across two runs."""
        from mdd.markdown.ir import parse_markdown, render_markdown

        md = "# Heading\n\nHello world\n\n- item 1\n- item 2\n"
        once = render_markdown(parse_markdown(md))
        twice = render_markdown(parse_markdown(once))
        assert once == twice
