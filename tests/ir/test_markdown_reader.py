"""Tests for mdd.markdown.ir.reader — parse_markdown()."""

from __future__ import annotations

from mdd.ir.document import Document
from mdd.ir.fallback import IRContext
from mdd.ir.nodes import (
    BlockQuote,
    BulletList,
    Callout,
    Code,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emph,
    Heading,
    HorizontalRule,
    Image,
    InlineMacro,
    Layout,
    LayoutCell,
    LayoutSection,
    LineBreak,
    Link,
    ListItem,
    OrderedList,
    Paragraph,
    RawBlock,
    RawInline,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    Text,
)
from mdd.markdown.ir import parse_markdown, render_markdown

# ---------------------------------------------------------------------------
# CommonMark blocks
# ---------------------------------------------------------------------------


def test_parse_heading_levels() -> None:
    doc = parse_markdown("# H1\n\n## H2\n\n### H3")
    assert len(doc.children) == 3
    h1, h2, h3 = doc.children
    assert isinstance(h1, Heading)
    assert h1.level == 1
    assert isinstance(h2, Heading)
    assert h2.level == 2
    assert isinstance(h3, Heading)
    assert h3.level == 3
    assert isinstance(h1.inlines[0], Text)
    assert h1.inlines[0].content == "H1"


def test_parse_paragraph() -> None:
    doc = parse_markdown("Hello world")
    assert len(doc.children) == 1
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Text)
    assert p.inlines[0].content == "Hello world"


def test_parse_horizontal_rule() -> None:
    doc = parse_markdown("---")
    assert len(doc.children) == 1
    assert isinstance(doc.children[0], HorizontalRule)


def test_parse_blockquote() -> None:
    doc = parse_markdown("> quoted text")
    assert len(doc.children) == 1
    bq = doc.children[0]
    assert isinstance(bq, BlockQuote)
    assert len(bq.children) == 1
    assert isinstance(bq.children[0], Paragraph)


def test_parse_code_block_fenced() -> None:
    md = "```python\nprint('hello')\n```"
    doc = parse_markdown(md)
    assert len(doc.children) == 1
    cb = doc.children[0]
    assert isinstance(cb, CodeBlock)
    assert cb.language == "python"
    assert "print" in cb.content


def test_parse_code_block_indented() -> None:
    doc = parse_markdown("    code here")
    assert len(doc.children) == 1
    assert isinstance(doc.children[0], CodeBlock)


def test_parse_bullet_list() -> None:
    doc = parse_markdown("- item a\n- item b")
    assert len(doc.children) == 1
    bl = doc.children[0]
    assert isinstance(bl, BulletList)
    assert len(bl.items) == 2
    assert isinstance(bl.items[0], ListItem)


def test_parse_ordered_list() -> None:
    doc = parse_markdown("1. first\n2. second")
    assert len(doc.children) == 1
    ol = doc.children[0]
    assert isinstance(ol, OrderedList)
    assert len(ol.items) == 2
    assert ol.start == 1


def test_parse_ordered_list_start() -> None:
    doc = parse_markdown("3. third\n4. fourth")
    ol = doc.children[0]
    assert isinstance(ol, OrderedList)
    assert ol.start == 3


def test_parse_nested_list() -> None:
    md = "- outer\n  - inner"
    doc = parse_markdown(md)
    bl = doc.children[0]
    assert isinstance(bl, BulletList)
    outer_item = bl.items[0]
    inner_children = outer_item.children
    assert any(isinstance(c, BulletList) for c in inner_children)


# ---------------------------------------------------------------------------
# CommonMark inlines
# ---------------------------------------------------------------------------


def test_parse_strong() -> None:
    doc = parse_markdown("**bold text**")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Strong)
    assert isinstance(p.inlines[0].tokens[0], Text)
    assert p.inlines[0].tokens[0].content == "bold text"


def test_parse_emph() -> None:
    doc = parse_markdown("*italic text*")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Emph)


def test_parse_code_inline() -> None:
    doc = parse_markdown("`inline code`")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Code)
    assert p.inlines[0].content == "inline code"


def test_parse_link() -> None:
    doc = parse_markdown("[click here](https://example.com)")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    link = p.inlines[0]
    assert isinstance(link, Link)
    assert link.href == "https://example.com"
    assert isinstance(link.tokens[0], Text)
    assert link.tokens[0].content == "click here"


def test_parse_image() -> None:
    doc = parse_markdown("![alt text](https://example.com/img.png)")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    img = p.inlines[0]
    assert isinstance(img, Image)
    assert img.src == "https://example.com/img.png"


def test_parse_hardbreak() -> None:
    doc = parse_markdown("line one  \nline two")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert any(isinstance(t, LineBreak) for t in p.inlines)


def test_parse_softbreak_preserving_mode() -> None:
    doc = parse_markdown("line one\nline two", mode="preserving")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert any(isinstance(t, SoftBreak) for t in p.inlines)


def test_parse_softbreak_normalising_mode() -> None:
    # In normalising mode the collapse_soft_breaks pass converts SoftBreak → Text(" ")
    doc = parse_markdown("line one\nline two")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert not any(isinstance(t, SoftBreak) for t in p.inlines)
    texts = [t.content for t in p.inlines if isinstance(t, Text)]
    assert " " in "".join(texts)


def test_parse_html_block_fallback() -> None:
    ctx = IRContext()
    doc = parse_markdown("<div>raw html</div>\n", ctx=ctx)
    assert any(isinstance(b, RawBlock) and b.format == "html" for b in doc.children)
    assert len(ctx.fallbacks) >= 1


def test_parse_inline_html_fallback() -> None:
    ctx = IRContext()
    doc = parse_markdown("text <em>inline</em> end", ctx=ctx)
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert any(isinstance(t, RawInline) and t.format == "html" for t in p.inlines)
    assert len(ctx.fallbacks) >= 1


# ---------------------------------------------------------------------------
# GFM constructs
# ---------------------------------------------------------------------------


def test_parse_gfm_table() -> None:
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    doc = parse_markdown(md)
    assert len(doc.children) == 1
    tbl = doc.children[0]
    assert isinstance(tbl, Table)
    assert tbl.has_header is True
    assert len(tbl.rows) == 2


def test_parse_gfm_strikethrough() -> None:
    doc = parse_markdown("~~struck~~")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    s = p.inlines[0]
    assert isinstance(s, Strikethrough)
    assert isinstance(s.tokens[0], Text)
    assert s.tokens[0].content == "struck"


def test_parse_gfm_task_list_done() -> None:
    doc = parse_markdown("- [x] done")
    bl = doc.children[0]
    assert isinstance(bl, BulletList)
    item = bl.items[0]
    assert item.attributes.get("task") == "done"


def test_parse_gfm_task_list_open() -> None:
    doc = parse_markdown("- [ ] open")
    bl = doc.children[0]
    assert isinstance(bl, BulletList)
    item = bl.items[0]
    assert item.attributes.get("task") == "open"


def test_parse_gfm_autolink() -> None:
    # CommonMark angle-bracket autolinks always produce Link nodes.
    doc = parse_markdown("<https://example.com>")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert any(isinstance(t, Link) for t in p.inlines)


# ---------------------------------------------------------------------------
# Confluence extensions
# ---------------------------------------------------------------------------


def test_parse_callout_tip() -> None:
    md = ":::callout-tip\nHello\n:::"
    doc = parse_markdown(md)
    assert len(doc.children) == 1
    c = doc.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "tip"
    assert len(c.body) >= 1


def test_parse_callout_info() -> None:
    doc = parse_markdown(":::callout-info\nContent\n:::")
    c = doc.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "info"


def test_parse_callout_warning() -> None:
    doc = parse_markdown(":::callout-warning\nAlert\n:::")
    c = doc.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "warning"


def test_parse_callout_note() -> None:
    doc = parse_markdown(":::callout-note\nNote\n:::")
    c = doc.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "note"


def test_parse_callout_panel() -> None:
    doc = parse_markdown(":::callout-panel\nPanel\n:::")
    c = doc.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "panel"


def test_parse_confluence_macro_fence() -> None:
    md = ':::confluence-macro {name="toc"}\n\n:::'
    doc = parse_markdown(md)
    assert len(doc.children) == 1
    cm = doc.children[0]
    assert isinstance(cm, ConfluenceMacro)
    assert cm.name == "toc"


def test_parse_confluence_xml_fence() -> None:
    ctx = IRContext()
    md = "```confluence-xml\n<p>raw</p>\n```"
    doc = parse_markdown(md, ctx=ctx)
    rb = doc.children[0]
    assert isinstance(rb, RawBlock)
    assert rb.format == "confluence-storage"
    assert "<p>raw</p>" in rb.content
    assert len(ctx.fallbacks) >= 1


def test_parse_inline_macro() -> None:
    doc = parse_markdown('{{confluence:status colour="Green" title="OK"}}')
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    im = p.inlines[0]
    assert isinstance(im, InlineMacro)
    assert im.name == "status"
    assert im.params["colour"] == "Green"
    assert im.params["title"] == "OK"


def test_parse_inline_macro_no_params() -> None:
    doc = parse_markdown("{{confluence:toc}}")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], InlineMacro)
    assert p.inlines[0].name == "toc"


def test_parse_confluence_page_link() -> None:
    doc = parse_markdown("[Home](confluence-page:MDD/Home)")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    cl = p.inlines[0]
    assert isinstance(cl, ConfluenceLink)
    assert cl.target_kind == "page"
    # ``<Space>/<Title>`` is unpacked into target + space_key so
    # both authoring shapes feed the same IR.
    assert cl.target == "Home"
    assert cl.space_key == "MDD"


def test_parse_confluence_page_link_with_space_and_anchor() -> None:
    doc = parse_markdown("[Home](confluence-page:Home;space-key=MDD;anchor=intro)")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    cl = p.inlines[0]
    assert isinstance(cl, ConfluenceLink)
    assert cl.space_key == "MDD"
    assert cl.attributes.get("ac:anchor") == "intro"


def test_parse_confluence_attachment_image() -> None:
    doc = parse_markdown("![diagram](confluence-attachment:diagram.png)")
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    ci = p.inlines[0]
    assert isinstance(ci, ConfluenceImage)
    assert ci.source_kind == "attachment"
    assert ci.source == "diagram.png"


def test_parse_confluence_attachment_image_with_extras() -> None:
    doc = parse_markdown('![alt](confluence-attachment:file.png "width=400 align=center")')
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    ci = p.inlines[0]
    assert isinstance(ci, ConfluenceImage)
    assert ci.attributes.get("ac:width") == "400"
    assert ci.attributes.get("ac:align") == "center"


# ---------------------------------------------------------------------------
# source_format and node_id assignment
# ---------------------------------------------------------------------------


def test_source_format_is_markdown() -> None:
    doc = parse_markdown("Hello")
    assert doc.source_format == "markdown"


def test_node_ids_assigned() -> None:
    doc = parse_markdown("Hello\n\nWorld")
    for block in doc.children:
        assert hasattr(block, "node_id")
        assert block.node_id != ""


def test_fallbacks_on_document() -> None:
    ctx = IRContext()
    doc = parse_markdown("<div>raw</div>\n", ctx=ctx)
    assert doc.fallbacks == ctx.fallbacks


# ---------------------------------------------------------------------------
# Table alignment
# ---------------------------------------------------------------------------


def test_parse_table_alignment() -> None:
    md = "| L | C | R |\n|:--|:--:|--:|\n| a | b | c |"
    doc = parse_markdown(md)
    tbl = doc.children[0]
    assert isinstance(tbl, Table)
    assert "left" in tbl.align
    assert "center" in tbl.align
    assert "right" in tbl.align


# ---------------------------------------------------------------------------
# Layout fenced divs (spec S30 §"Layout")
# ---------------------------------------------------------------------------


def test_parse_layout_simple() -> None:
    """A minimal ``:::layout`` block round-trips into ``Layout`` IR."""
    md = (
        ":::layout\n"
        '::::layout-section layout_type="two_equal"\n'
        ":::::layout-cell\n\n"
        "left\n\n"
        ":::::\n"
        ":::::layout-cell\n\n"
        "right\n\n"
        ":::::\n"
        "::::\n"
        ":::\n"
    )
    doc = parse_markdown(md)
    assert len(doc.children) == 1
    layout = doc.children[0]
    assert isinstance(layout, Layout)
    assert len(layout.sections) == 1
    section = layout.sections[0]
    assert section.layout_type == "two_equal"
    assert len(section.cells) == 2
    left, right = section.cells
    assert isinstance(left.children[0], Paragraph)
    assert isinstance(right.children[0], Paragraph)
    assert isinstance(left.children[0].inlines[0], Text)
    assert left.children[0].inlines[0].content == "left"
    assert isinstance(right.children[0].inlines[0], Text)
    assert right.children[0].inlines[0].content == "right"


def test_layout_roundtrip_through_markdown() -> None:
    """Build IR → render → parse should reproduce the layout structure."""
    doc = Document(
        children=[
            Layout(
                sections=[
                    LayoutSection(
                        layout_type="two_equal",
                        cells=[
                            LayoutCell(
                                children=[
                                    Heading(level=2, inlines=[Text("Left")]),
                                    Paragraph(inlines=[Text("first cell paragraph")]),
                                ]
                            ),
                            LayoutCell(
                                children=[
                                    BulletList(
                                        items=[
                                            ListItem(children=[Paragraph(inlines=[Text("alpha")])]),
                                            ListItem(children=[Paragraph(inlines=[Text("beta")])]),
                                        ]
                                    ),
                                ]
                            ),
                        ],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    assert len(parsed.children) == 1
    layout = parsed.children[0]
    assert isinstance(layout, Layout)
    assert len(layout.sections) == 1
    section = layout.sections[0]
    assert section.layout_type == "two_equal"
    assert len(section.cells) == 2

    cell_a, cell_b = section.cells
    # First cell: heading + paragraph
    assert len(cell_a.children) == 2
    h, p = cell_a.children
    assert isinstance(h, Heading)
    assert h.level == 2
    assert isinstance(h.inlines[0], Text)
    assert h.inlines[0].content == "Left"
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Text)
    assert p.inlines[0].content == "first cell paragraph"
    # Second cell: bullet list with two items
    assert len(cell_b.children) == 1
    lst = cell_b.children[0]
    assert isinstance(lst, BulletList)
    assert len(lst.items) == 2


def test_layout_multiple_sections_roundtrip() -> None:
    """A Layout with multiple sections (each with multiple cells) round-trips."""
    doc = Document(
        children=[
            Layout(
                sections=[
                    LayoutSection(
                        layout_type="single",
                        cells=[LayoutCell(children=[Paragraph(inlines=[Text("intro")])])],
                    ),
                    LayoutSection(
                        layout_type="three_equal",
                        cells=[
                            LayoutCell(children=[Paragraph(inlines=[Text("a")])]),
                            LayoutCell(children=[Paragraph(inlines=[Text("b")])]),
                            LayoutCell(children=[Paragraph(inlines=[Text("c")])]),
                        ],
                    ),
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    layout = parsed.children[0]
    assert isinstance(layout, Layout)
    assert [s.layout_type for s in layout.sections] == ["single", "three_equal"]
    assert [len(s.cells) for s in layout.sections] == [1, 3]
    flat: list[str] = []
    for s in layout.sections:
        for cell in s.cells:
            para = cell.children[0]
            assert isinstance(para, Paragraph)
            tok = para.inlines[0]
            assert isinstance(tok, Text)
            flat.append(tok.content)
    assert flat == ["intro", "a", "b", "c"]
