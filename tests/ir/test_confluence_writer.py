"""Tests for mdd.confluence.ir.writer — render_confluence_storage."""

from __future__ import annotations

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir.document import Document
from mdd.ir.nodes import (
    BulletList,
    Callout,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emoticon,
    Emph,
    Heading,
    HorizontalRule,
    Layout,
    LayoutCell,
    LayoutSection,
    ListItem,
    OrderedList,
    Paragraph,
    Placeholder,
    RawBlock,
    RawInline,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
)


def _roundtrip(storage: str) -> str:
    """Parse then render — one parse+render cycle."""
    doc = parse_confluence_storage(storage)
    return render_confluence_storage(doc)


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------


class TestHeadingWriter:
    def test_h1(self) -> None:
        out = render_confluence_storage(
            Document(children=[Heading(level=1, inlines=[Text("Hello")])])
        )
        assert out == "<h1>Hello</h1>"

    def test_h3(self) -> None:
        out = render_confluence_storage(
            Document(children=[Heading(level=3, inlines=[Text("Sec")])])
        )
        assert "<h3>" in out
        assert "</h3>" in out


class TestParagraphWriter:
    def test_basic(self) -> None:
        out = render_confluence_storage(Document(children=[Paragraph(inlines=[Text("hi")])]))
        assert out == "<p>hi</p>"

    def test_empty_paragraph(self) -> None:
        # Empty paragraphs self-close to match the storage shape Confluence
        # emits and that the corpus snapshots carry (e.g. trailing macro
        # spacer paragraphs in fixture 131332).
        out = render_confluence_storage(Document(children=[Paragraph(inlines=[])]))
        assert out == "<p />"


class TestListWriter:
    def test_bullet_list(self) -> None:
        items = [
            ListItem(children=[Paragraph(inlines=[Text("a")])]),
            ListItem(children=[Paragraph(inlines=[Text("b")])]),
        ]
        doc = Document(children=[BulletList(items=items)])
        out = render_confluence_storage(doc)
        assert "<ul>" in out
        assert "<li>a</li>" in out

    def test_ordered_list_always_emits_start(self) -> None:
        # Spike fix 2: start="1" must always be emitted.
        items = [ListItem(children=[Paragraph(inlines=[Text("x")])])]
        doc = Document(children=[OrderedList(items=items, start=1)])
        out = render_confluence_storage(doc)
        assert 'start="1"' in out

    def test_ordered_list_non_default_start(self) -> None:
        items = [ListItem(children=[Paragraph(inlines=[Text("x")])])]
        doc = Document(children=[OrderedList(items=items, start=5)])
        out = render_confluence_storage(doc)
        assert 'start="5"' in out


class TestHorizontalRuleWriter:
    def test_hr(self) -> None:
        out = render_confluence_storage(Document(children=[HorizontalRule()]))
        assert "<hr" in out


class TestCodeBlockWriter:
    def test_plain_codeblock_no_identity(self) -> None:
        cb = CodeBlock(content="print('hi')", language="python")
        out = render_confluence_storage(Document(children=[cb]))
        assert "<pre" in out
        assert "python" in out

    def test_codeblock_with_macro_identity(self) -> None:
        cb = CodeBlock(
            content="x = 1",
            language="python",
            attributes={"ac:name": "code", "ac:schema-version": "1", "ac:macro-id": "abc-123"},
        )
        out = render_confluence_storage(Document(children=[cb]))
        assert 'ac:name="code"' in out
        assert "<![CDATA[" in out
        assert "x = 1" in out


class TestTableWriter:
    def test_simple_table(self) -> None:
        rows = [
            TableRow(cells=[TableCell(children=[Paragraph(inlines=[Text("A")])], header=True)]),
            TableRow(cells=[TableCell(children=[Paragraph(inlines=[Text("1")])])]),
        ]
        doc = Document(children=[Table(rows=rows, has_header=True)])
        out = render_confluence_storage(doc)
        assert "<table>" in out
        assert "<thead>" in out
        assert "<tbody>" in out
        assert "<th>" in out


class TestCalloutWriter:
    def test_tip_callout(self) -> None:
        c = Callout(
            kind="tip",
            body=[Paragraph(inlines=[Text("tip text")])],
            attributes={"ac:macro-id": "m1"},
        )
        out = render_confluence_storage(Document(children=[c]))
        assert 'ac:name="tip"' in out
        assert "<ac:rich-text-body>" in out
        assert "tip text" in out

    def test_callout_with_title(self) -> None:
        c = Callout(
            kind="note",
            body=[Paragraph(inlines=[Text("body")])],
            title="My Note",
        )
        out = render_confluence_storage(Document(children=[c]))
        assert "My Note" in out
        assert 'ac:name="title"' in out


class TestConfluenceMacroWriter:
    def test_macro_with_rich_body(self) -> None:
        m = ConfluenceMacro(
            name="expand",
            params={"title": "Click"},
            body=[Paragraph(inlines=[Text("content")])],
            rich_body=True,
        )
        out = render_confluence_storage(Document(children=[m]))
        assert 'ac:name="expand"' in out
        assert "<ac:rich-text-body>" in out
        assert "content" in out

    def test_macro_without_rich_body_no_empty_body_tag(self) -> None:
        # Spike fix 3: no <ac:rich-text-body> emitted when rich_body=False.
        m = ConfluenceMacro(name="status", params={"title": "On track"}, rich_body=False)
        out = render_confluence_storage(Document(children=[m]))
        assert "<ac:rich-text-body>" not in out

    def test_macro_passthrough_attrs(self) -> None:
        # Passthrough attrs (e.g. data-layout) are carried in `attributes`.
        m = ConfluenceMacro(
            name="expand",
            attributes={"ac:name": "expand", "data-layout": "default"},
            rich_body=True,
            body=[],
        )
        out = render_confluence_storage(Document(children=[m]))
        assert "data-layout" in out


class TestLayoutWriter:
    def test_layout_roundtrip(self) -> None:
        lay = Layout(
            sections=[
                LayoutSection(
                    layout_type="two_equal",
                    cells=[
                        LayoutCell(children=[Paragraph(inlines=[Text("left")])]),
                        LayoutCell(children=[Paragraph(inlines=[Text("right")])]),
                    ],
                )
            ]
        )
        out = render_confluence_storage(Document(children=[lay]))
        assert "<ac:layout>" in out
        assert "<ac:layout-section" in out
        assert "<ac:layout-cell>" in out
        assert "left" in out
        assert "right" in out


class TestRawBlockWriter:
    def test_confluence_storage_format_verbatim(self) -> None:
        raw = RawBlock(content="<foo>bar</foo>", format="confluence-storage")
        out = render_confluence_storage(Document(children=[raw]))
        assert out == "<foo>bar</foo>"

    def test_xhtml_format_verbatim(self) -> None:
        raw = RawBlock(content="<foo>bar</foo>", format="xhtml")
        out = render_confluence_storage(Document(children=[raw]))
        assert out == "<foo>bar</foo>"

    def test_markdown_format_wrapped(self) -> None:
        raw = RawBlock(content="# heading", format="markdown")
        out = render_confluence_storage(Document(children=[raw]))
        assert "<!-- raw:markdown -->" in out
        assert "<pre>" in out
        assert "# heading" in out


# ---------------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------------


class TestInlineWriter:
    def test_strong(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Strong(tokens=[Text("bold")])])])
        out = render_confluence_storage(doc)
        assert "<strong>bold</strong>" in out

    def test_emph(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Emph(tokens=[Text("it")])])])
        out = render_confluence_storage(doc)
        assert "<em>it</em>" in out

    def test_strikethrough(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Strikethrough(tokens=[Text("x")])])])
        out = render_confluence_storage(doc)
        assert "<s>x</s>" in out

    def test_emoticon(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Emoticon(name="smile")])])
        out = render_confluence_storage(doc)
        assert '<ac:emoticon ac:name="smile" />' in out

    def test_placeholder(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Placeholder(content="enter value")])])
        out = render_confluence_storage(doc)
        assert "<ac:placeholder>" in out
        assert "enter value" in out

    def test_raw_inline_verbatim(self) -> None:
        ri = RawInline(content="<ac:foo/>", format="confluence-storage")
        doc = Document(children=[Paragraph(inlines=[ri])])
        out = render_confluence_storage(doc)
        assert "<ac:foo/>" in out


class TestConfluenceLinkWriter:
    def test_page_link(self) -> None:
        link = ConfluenceLink(
            target_kind="page",
            target="My Page",
            space_key="MDD",
            body_tokens=[Text("My Page")],
        )
        doc = Document(children=[Paragraph(inlines=[link])])
        out = render_confluence_storage(doc)
        assert "<ac:link>" in out
        assert "<ri:page" in out
        assert 'ri:content-title="My Page"' in out
        assert 'ri:space-key="MDD"' in out

    def test_url_link(self) -> None:
        link = ConfluenceLink(
            target_kind="url",
            target="https://example.com",
        )
        doc = Document(children=[Paragraph(inlines=[link])])
        out = render_confluence_storage(doc)
        assert '<ri:url ri:value="https://example.com"' in out

    def test_block_level_link_not_wrapped(self) -> None:
        # A standalone link with block_level=True must not be re-wrapped
        # in <p> by the writer.
        link = ConfluenceLink(
            target_kind="page",
            target="Some Page",
            block_level=True,
        )
        doc = Document(children=[Paragraph(inlines=[link])])
        out = render_confluence_storage(doc)
        assert not out.startswith("<p>")
        assert "<ac:link>" in out

    def test_block_level_hint_not_emitted_as_extras(self) -> None:
        # ``block_level`` is now a typed field on the dataclass, not an
        # underscore-prefixed extras entry. The writer must still treat the
        # link bare and never emit a stray ``_block`` attribute.
        link = ConfluenceLink(
            target_kind="page",
            target="Some Page",
            block_level=True,
        )
        doc = Document(children=[Paragraph(inlines=[link])])
        out = render_confluence_storage(doc)
        assert "_block" not in out


class TestConfluenceImageWriter:
    def test_url_image(self) -> None:
        img = ConfluenceImage(source_kind="url", source="https://example.com/img.png")
        doc = Document(children=[Paragraph(inlines=[img])])
        out = render_confluence_storage(doc)
        assert "<ac:image" in out
        assert '<ri:url ri:value="https://example.com/img.png"' in out


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_heading_roundtrip(self) -> None:
        storage = "<h1>Hello world</h1>"
        assert _roundtrip(storage) == storage

    def test_paragraph_roundtrip(self) -> None:
        storage = "<p>Simple paragraph.</p>"
        assert _roundtrip(storage) == storage

    def test_ordered_list_start_always_emitted(self) -> None:
        # Spike fix 2: ol with start="1" must survive round-trip.
        storage = '<ol start="1"><li>item</li>\n</ol>'
        out = _roundtrip(storage)
        assert 'start="1"' in out

    def test_hand_built_ir_roundtrip(self) -> None:
        """Build a Document, render, re-parse, render again — must match."""
        doc = Document(
            children=[
                Heading(level=2, inlines=[Text("Section")]),
                Paragraph(inlines=[Text("Body text.")]),
                OrderedList(
                    items=[
                        ListItem(children=[Paragraph(inlines=[Text("one")])]),
                        ListItem(children=[Paragraph(inlines=[Text("two")])]),
                    ],
                    start=1,
                ),
                CodeBlock(content="x = 1", language="python"),
            ]
        )
        first = render_confluence_storage(doc)
        second = render_confluence_storage(parse_confluence_storage(first))
        assert first == second

    def test_callout_roundtrip(self) -> None:
        storage = (
            '<ac:structured-macro ac:name="tip" ac:schema-version="1"'
            ' ac:macro-id="test-id">'
            "<ac:rich-text-body><p>tip text</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        out1 = _roundtrip(storage)
        out2 = _roundtrip(out1)
        assert out1 == out2
