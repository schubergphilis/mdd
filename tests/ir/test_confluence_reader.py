"""Tests for mdd.confluence.ir.reader — parse_confluence_storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir.fallback import IRContext
from mdd.ir.nodes import (
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emoticon,
    Heading,
    HorizontalRule,
    Layout,
    OrderedList,
    Paragraph,
    Placeholder,
    RawBlock,
    RawInline,
    Strikethrough,
    Strong,
    Table,
    Text,
)

_SNAPSHOTS = Path(__file__).resolve().parents[1] / "corpus" / "confluence" / "_snapshots"


def _storage(page_id: str) -> str:
    return (_SNAPSHOTS / page_id / "storage.xhtml").read_text()


# ---------------------------------------------------------------------------
# Element shapes
# ---------------------------------------------------------------------------


class TestParagraph:
    def test_basic(self) -> None:
        doc = parse_confluence_storage("<p>Hello world</p>")
        assert len(doc.children) == 1
        assert isinstance(doc.children[0], Paragraph)
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert any(isinstance(t, Text) and "Hello world" in t.content for t in p.inlines)

    def test_empty_paragraph_preserved_in_preserving_mode(self) -> None:
        # Spike fix 1: empty <p> must not be dropped in preserving mode.
        # In normalising mode, drop_empty_paragraphs removes them (intended behaviour).
        doc = parse_confluence_storage("<p>text</p><p />", mode="preserving")
        assert len(doc.children) == 2
        assert isinstance(doc.children[1], Paragraph)
        assert doc.children[1].inlines == []

    def test_empty_paragraph_dropped_in_normalising_mode(self) -> None:
        # Normalising mode drops empty paragraphs via the normalisation pipeline.
        doc = parse_confluence_storage("<p>text</p><p />")
        assert len(doc.children) == 1

    def test_whitespace_only_paragraph_preserved(self) -> None:
        doc = parse_confluence_storage("<p> </p>", mode="preserving")
        assert len(doc.children) == 1
        assert isinstance(doc.children[0], Paragraph)


class TestHeading:
    def test_h1(self) -> None:
        doc = parse_confluence_storage("<h1>Title</h1>")
        h = doc.children[0]
        assert isinstance(h, Heading)
        assert h.level == 1

    def test_h3(self) -> None:
        doc = parse_confluence_storage("<h3>Section</h3>")
        h = doc.children[0]
        assert isinstance(h, Heading)
        assert h.level == 3

    def test_heading_level_range(self) -> None:
        for level in range(1, 7):
            doc = parse_confluence_storage(f"<h{level}>x</h{level}>")
            h = doc.children[0]
            assert isinstance(h, Heading)
            assert h.level == level


class TestList:
    def test_bullet_list(self) -> None:
        doc = parse_confluence_storage("<ul><li>a</li><li>b</li></ul>")
        bl = doc.children[0]
        assert isinstance(bl, BulletList)
        assert len(bl.items) == 2

    def test_ordered_list_start_preserved(self) -> None:
        doc = parse_confluence_storage('<ol start="3"><li>x</li></ol>')
        ol = doc.children[0]
        assert isinstance(ol, OrderedList)
        assert ol.start == 3

    def test_ordered_list_default_start(self) -> None:
        doc = parse_confluence_storage("<ol><li>x</li></ol>")
        ol = doc.children[0]
        assert isinstance(ol, OrderedList)
        assert ol.start == 1


class TestTable:
    def test_simple_table(self) -> None:
        storage = (
            "<table>"
            "<thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td>2</td></tr></tbody>"
            "</table>"
        )
        doc = parse_confluence_storage(storage)
        tbl = doc.children[0]
        assert isinstance(tbl, Table)
        assert tbl.has_header
        assert len(tbl.rows) == 2

    def test_plain_table_fixture(self) -> None:
        storage = _storage("66045")
        doc = parse_confluence_storage(storage)
        tables = [b for b in doc.children if isinstance(b, Table)]
        assert tables


class TestBlockquote:
    def test_basic(self) -> None:
        doc = parse_confluence_storage("<blockquote><p>quoted</p></blockquote>")
        bq = doc.children[0]
        assert isinstance(bq, BlockQuote)
        assert len(bq.children) >= 1


class TestCodeBlock:
    def test_code_macro(self) -> None:
        storage = (
            '<ac:structured-macro ac:name="code" ac:schema-version="1"'
            ' ac:macro-id="abc-123">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            "<ac:plain-text-body><![CDATA[print('hi')]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        doc = parse_confluence_storage(storage)
        cb = doc.children[0]
        assert isinstance(cb, CodeBlock)
        assert cb.language == "python"
        assert "print" in cb.content

    def test_code_fixture(self) -> None:
        storage = _storage("65941")
        doc = parse_confluence_storage(storage)
        cbs = [b for b in doc.children if isinstance(b, CodeBlock)]
        assert cbs


class TestCallout:
    def test_tip_callout(self) -> None:
        storage = _storage("131332")
        doc = parse_confluence_storage(storage)
        callouts = [b for b in doc.children if isinstance(b, Callout)]
        assert callouts
        c = callouts[0]
        assert c.kind == "tip"
        assert len(c.body) > 0

    def test_panel_callout_with_params(self) -> None:
        storage = _storage("131360")
        doc = parse_confluence_storage(storage)
        callouts = [b for b in doc.children if isinstance(b, Callout)]
        assert callouts


class TestLink:
    def test_ac_link_page(self) -> None:
        storage = (
            "<p>"
            '<ac:link><ri:page ri:content-title="My Page" ri:space-key="MDD" />'
            "<ac:link-body>My Page</ac:link-body></ac:link>"
            "</p>"
        )
        doc = parse_confluence_storage(storage)
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        link = p.inlines[0]
        assert isinstance(link, ConfluenceLink)
        assert link.target_kind == "page"
        assert link.target == "My Page"
        assert link.space_key == "MDD"

    def test_ac_link_url(self) -> None:
        storage = '<p><ac:link><ri:url ri:value="https://example.com" /></ac:link></p>'
        doc = parse_confluence_storage(storage)
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        link = p.inlines[0]
        assert isinstance(link, ConfluenceLink)
        assert link.target_kind == "url"
        assert link.target == "https://example.com"

    def test_attachment_link_fixture(self) -> None:
        storage = _storage("131404")
        doc = parse_confluence_storage(storage)
        assert doc.children


class TestImage:
    def test_ac_image_url(self) -> None:
        storage = '<p><ac:image><ri:url ri:value="https://example.com/img.png" /></ac:image></p>'
        doc = parse_confluence_storage(storage)
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        img = p.inlines[0]
        assert isinstance(img, ConfluenceImage)
        assert img.source_kind == "url"
        assert img.source == "https://example.com/img.png"

    def test_image_url_fixture(self) -> None:
        storage = _storage("131253")
        doc = parse_confluence_storage(storage)
        assert doc.children

    def test_ac_image_layout_and_size_attrs_round_trip(self) -> None:
        """The Confluence editor decorates ``<ac:image>`` with ``ac:layout``,
        ``ac:original-height``, ``ac:original-width``, ``ac:custom-width`` —
        these must survive the IR so the storage writer can re-emit them.
        Without this the image renders at the wrong default size. issue #85.
        """
        storage = (
            '<p><ac:image ac:align="left" ac:layout="align-start" '
            'ac:original-height="1472" ac:original-width="2084" '
            'ac:custom-width="true" ac:width="320" ac:alt="Diagram">'
            '<ri:attachment ri:filename="diagram.png" />'
            "</ac:image></p>"
        )
        doc = parse_confluence_storage(storage)
        img = doc.children[0].inlines[0]  # type: ignore[union-attr]
        assert isinstance(img, ConfluenceImage)
        for key in ("ac:layout", "ac:original-height", "ac:original-width", "ac:custom-width"):
            assert img.attributes.get(key), f"missing attributes[{key!r}] on parsed image"

    def test_block_level_image_in_layout_cell_skips_p_wrapper(self) -> None:
        """``<ac:layout-cell><ac:image ../></ac:layout-cell>`` (image as direct
        block child, no ``<p>`` wrapper) must round-trip without the writer
        injecting a synthetic ``<p>``. The IR needs the same ``_block`` hint
        on ``ConfluenceImage`` that ``ConfluenceLink`` already has. issue #85.
        """
        storage = (
            '<ac:layout><ac:layout-section ac:type="single">'
            "<ac:layout-cell>"
            '<ac:image ac:width="320" ac:alt="d"><ri:attachment ri:filename="d.png" /></ac:image>'
            "</ac:layout-cell>"
            "</ac:layout-section></ac:layout>"
        )
        rt = render_confluence_storage(parse_confluence_storage(storage, mode="preserving"))
        assert "<p>" not in rt, (
            f"block-level image should not be wrapped in <p> on round-trip, got:\n{rt}"
        )
        assert rt == storage, f"byte-perfect mismatch:\nexpected: {storage}\nactual:   {rt}"

    def test_ri_attachment_version_at_save_round_trip(self) -> None:
        """``<ri:attachment ri:version-at-save="N" />`` pins the attachment
        revision that was current when the page was authored. Lossy round-trip
        produces a page that refers to an unspecified version. issue #85.
        """
        storage = (
            '<p><ac:image ac:alt="d">'
            '<ri:attachment ri:filename="d.png" ri:version-at-save="3" />'
            "</ac:image></p>"
        )
        doc = parse_confluence_storage(storage)
        img = doc.children[0].inlines[0]  # type: ignore[union-attr]
        assert isinstance(img, ConfluenceImage)
        assert img.attachment_version == "3"


class TestLayout:
    def test_layout_fixture(self) -> None:
        storage = _storage("131384")
        doc = parse_confluence_storage(storage)
        layouts = [b for b in doc.children if isinstance(b, Layout)]
        assert layouts
        lay = layouts[0]
        assert len(lay.sections) > 0
        assert len(lay.sections[0].cells) > 0


class TestHorizontalRule:
    def test_hr(self) -> None:
        doc = parse_confluence_storage("<hr />")
        assert isinstance(doc.children[0], HorizontalRule)

    def test_hr_fixture(self) -> None:
        storage = _storage("164022")
        doc = parse_confluence_storage(storage)
        hrs = [b for b in doc.children if isinstance(b, HorizontalRule)]
        assert hrs


class TestInlineShapes:
    def test_strong(self) -> None:
        doc = parse_confluence_storage("<p><strong>bold</strong></p>")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        s = p.inlines[0]
        assert isinstance(s, Strong)

    def test_strikethrough(self) -> None:
        doc = parse_confluence_storage("<p><s>struck</s></p>")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        s = p.inlines[0]
        assert isinstance(s, Strikethrough)

    def test_placeholder(self) -> None:
        doc = parse_confluence_storage("<p><ac:placeholder>enter text</ac:placeholder></p>")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        pl = p.inlines[0]
        assert isinstance(pl, Placeholder)
        assert pl.content == "enter text"

    def test_emoticon(self) -> None:
        doc = parse_confluence_storage('<p><ac:emoticon ac:name="smile"/></p>')
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        em = p.inlines[0]
        assert isinstance(em, Emoticon)
        assert em.name == "smile"


class TestConfluenceMacro:
    def test_expand_macro(self) -> None:
        storage = _storage("164089")
        doc = parse_confluence_storage(storage)
        macros = [b for b in doc.children if isinstance(b, ConfluenceMacro)]
        assert macros
        m = macros[0]
        assert m.name == "expand"

    def test_macro_attrs_captured(self) -> None:
        # Spike fix 3: data-layout and other passthrough attrs captured.
        storage = _storage("164089")
        doc = parse_confluence_storage(storage)
        macros = [b for b in doc.children if isinstance(b, ConfluenceMacro)]
        assert macros
        m = macros[0]
        assert "data-layout" in m.attributes or m.rich_body


class TestFallback:
    def test_unknown_element_becomes_raw_block(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:foo-unknown-element>content</ac:foo-unknown-element>",
            ctx=ctx,
        )
        assert ctx.fallbacks
        raw_blocks = [b for b in doc.children if isinstance(b, RawBlock)]
        assert raw_blocks

    def test_fallbacks_on_document(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:totally-unknown>x</ac:totally-unknown>",
            ctx=ctx,
        )
        assert len(doc.fallbacks) >= 1
        assert doc.fallbacks[0].kind == "block"
        assert doc.fallbacks[0].source_format == "confluence-storage"

    def test_inline_fallback(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<p><ac:unknown-inline-tag>x</ac:unknown-inline-tag></p>",
            ctx=ctx,
        )
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        raw = [t for t in p.inlines if isinstance(t, RawInline)]
        assert raw


# ---------------------------------------------------------------------------
# Document properties
# ---------------------------------------------------------------------------


class TestDocumentProperties:
    def test_source_format(self) -> None:
        doc = parse_confluence_storage("<p>x</p>")
        assert doc.source_format == "confluence-storage"

    def test_node_ids_assigned(self) -> None:
        doc = parse_confluence_storage("<p>a</p><p>b</p>")
        for block in doc.children:
            assert hasattr(block, "node_id")
            assert block.node_id  # type: ignore[union-attr]

    def test_page_title(self) -> None:
        doc = parse_confluence_storage("<p>x</p>", page_title="My Page")
        assert doc.page_title == "My Page"


# ---------------------------------------------------------------------------
# Fixture smoke tests
# ---------------------------------------------------------------------------


_FIXTURE_IDS = [
    "98308",  # plain paragraph
    "98328",  # blockquote
    "65915",  # code block no language
    "131253",  # image URL
    "131272",  # external link
    "131305",  # table
    "131332",  # tip callout
    "131360",  # panel with ordered list
    "131384",  # layout
    "131404",  # attachment link
    "164003",  # multiple paragraphs
    "164022",  # horizontal rule
    "164060",  # page links
    "163977",  # nested lists
]


@pytest.mark.parametrize("page_id", _FIXTURE_IDS)
def test_fixture_parses_without_error(page_id: str) -> None:
    storage = _storage(page_id)
    doc = parse_confluence_storage(storage)
    assert len(doc.children) > 0
    assert doc.source_format == "confluence-storage"
