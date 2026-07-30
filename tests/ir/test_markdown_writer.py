"""Tests for mdd.markdown.ir.writer — render_markdown() and round-trips."""

from __future__ import annotations

from mdd.ir.document import Document
from mdd.ir.nodes import (
    BlockQuote,
    BulletList,
    Callout,
    Code,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Emoticon,
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
    Placeholder,
    RawBlock,
    RawInline,
    SoftBreak,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
)
from mdd.markdown.ir import parse_markdown, render_markdown

# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------


def test_render_heading() -> None:
    doc = Document(children=[Heading(level=2, inlines=[Text("Hello")])])
    md = render_markdown(doc)
    assert md.startswith("## Hello")


def test_render_paragraph() -> None:
    doc = Document(children=[Paragraph(inlines=[Text("Simple paragraph")])])
    md = render_markdown(doc)
    assert "Simple paragraph" in md


def test_render_horizontal_rule() -> None:
    doc = Document(children=[HorizontalRule()])
    md = render_markdown(doc)
    assert "---" in md


def test_render_code_block() -> None:
    doc = Document(children=[CodeBlock(content="print('hi')", language="python")])
    md = render_markdown(doc)
    assert "```python" in md
    assert "print('hi')" in md
    assert "```" in md


def test_render_code_block_no_lang() -> None:
    doc = Document(children=[CodeBlock(content="plain code")])
    md = render_markdown(doc)
    assert "```\n" in md


def test_render_blockquote() -> None:
    doc = Document(children=[BlockQuote(children=[Paragraph(inlines=[Text("quoted")])])])
    md = render_markdown(doc)
    assert "> quoted" in md


def test_render_bullet_list() -> None:
    doc = Document(
        children=[
            BulletList(
                items=[
                    ListItem(children=[Paragraph(inlines=[Text("a")])]),
                    ListItem(children=[Paragraph(inlines=[Text("b")])]),
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "- a" in md
    assert "- b" in md


def test_render_ordered_list() -> None:
    doc = Document(
        children=[
            OrderedList(
                start=1,
                items=[
                    ListItem(children=[Paragraph(inlines=[Text("first")])]),
                    ListItem(children=[Paragraph(inlines=[Text("second")])]),
                ],
            )
        ]
    )
    md = render_markdown(doc)
    assert "1. first" in md
    assert "2. second" in md


def test_render_ordered_list_start() -> None:
    doc = Document(
        children=[
            OrderedList(
                start=3,
                items=[
                    ListItem(children=[Paragraph(inlines=[Text("third")])]),
                ],
            )
        ]
    )
    md = render_markdown(doc)
    assert "3. third" in md


def test_render_task_list_done() -> None:
    doc = Document(
        children=[
            BulletList(
                items=[
                    ListItem(
                        children=[Paragraph(inlines=[Text("done item")])],
                        attributes={"task": "done"},
                    ),
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "- [x] done item" in md


def test_render_task_list_open() -> None:
    doc = Document(
        children=[
            BulletList(
                items=[
                    ListItem(
                        children=[Paragraph(inlines=[Text("open item")])],
                        attributes={"task": "open"},
                    ),
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "- [ ] open item" in md


# ---------------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------------


def test_render_strong() -> None:
    doc = Document(children=[Paragraph(inlines=[Strong(tokens=[Text("bold")])])])
    md = render_markdown(doc)
    assert "**bold**" in md


def test_render_emph() -> None:
    doc = Document(children=[Paragraph(inlines=[Emph(tokens=[Text("italic")])])])
    md = render_markdown(doc)
    assert "*italic*" in md


def test_render_strikethrough() -> None:
    doc = Document(children=[Paragraph(inlines=[Strikethrough(tokens=[Text("struck")])])])
    md = render_markdown(doc)
    assert "~~struck~~" in md


def test_render_code_inline() -> None:
    doc = Document(children=[Paragraph(inlines=[Code(content="x = 1")])])
    md = render_markdown(doc)
    assert "`x = 1`" in md


def test_render_link() -> None:
    doc = Document(
        children=[Paragraph(inlines=[Link(href="https://example.com", tokens=[Text("click")])])]
    )
    md = render_markdown(doc)
    assert "[click](https://example.com)" in md


def test_render_image() -> None:
    doc = Document(
        children=[Paragraph(inlines=[Image(src="https://example.com/img.png", alt="alt text")])]
    )
    md = render_markdown(doc)
    assert "![alt text](https://example.com/img.png)" in md


def test_render_linebreak() -> None:
    doc = Document(children=[Paragraph(inlines=[Text("a"), LineBreak(), Text("b")])])
    md = render_markdown(doc)
    assert "  \n" in md


def test_render_softbreak() -> None:
    doc = Document(children=[Paragraph(inlines=[Text("a"), SoftBreak(), Text("b")])])
    md = render_markdown(doc)
    assert " " in md


# ---------------------------------------------------------------------------
# Confluence-specific rendering
# ---------------------------------------------------------------------------


def test_render_confluence_link_page() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="page",
                        target="Home",
                        space_key="MDD",
                        body_tokens=[Text("Home page")],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "confluence-page:" in md
    assert "Home" in md


def test_render_confluence_link_url() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="url",
                        target="https://example.com",
                        body_tokens=[Text("link")],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "[link](https://example.com)" in md


def test_render_confluence_image_attachment() -> None:
    doc = Document(
        children=[
            Paragraph(inlines=[ConfluenceImage(source_kind="attachment", source="diagram.png")])
        ]
    )
    md = render_markdown(doc)
    assert "confluence-attachment:diagram.png" in md


def test_render_inline_macro() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[InlineMacro(name="status", params={"colour": "Green", "title": "OK"})]
            )
        ]
    )
    md = render_markdown(doc)
    assert "{{confluence:status" in md
    assert 'colour="Green"' in md


def test_render_emoticon() -> None:
    doc = Document(children=[Paragraph(inlines=[Emoticon(name="smile")])])
    md = render_markdown(doc)
    assert '{{confluence:emoticon name="smile"}}' in md


def test_render_placeholder() -> None:
    doc = Document(children=[Paragraph(inlines=[Placeholder(content="Enter text here")])])
    md = render_markdown(doc)
    assert "{{confluence:placeholder" in md
    assert "Enter text here" in md


def test_render_raw_inline() -> None:
    doc = Document(children=[Paragraph(inlines=[RawInline(content="<em>raw</em>", format="html")])])
    md = render_markdown(doc)
    assert "<em>raw</em>" in md


def test_render_callout_tip() -> None:
    doc = Document(children=[Callout(kind="tip", body=[Paragraph(inlines=[Text("content")])])])
    md = render_markdown(doc)
    assert ":::callout-tip" in md
    assert "content" in md
    assert ":::" in md


def test_render_callout_all_kinds() -> None:
    for kind in ("tip", "info", "note", "warning", "panel"):
        doc = Document(
            children=[
                Callout(
                    kind=kind,
                    body=[  # pyright: ignore[reportArgumentType]
                        Paragraph(inlines=[Text("x")])
                    ],
                )
            ]
        )
        md = render_markdown(doc)
        assert f":::callout-{kind}" in md


def test_render_confluence_macro() -> None:
    doc = Document(
        children=[
            ConfluenceMacro(
                name="toc",
                params={"minLevel": "1"},
                body=[],
                plain_body=None,
                rich_body=False,
            )
        ]
    )
    md = render_markdown(doc)
    assert ":::confluence-macro" in md
    assert 'name="toc"' in md


def test_render_raw_block_markdown() -> None:
    doc = Document(children=[RawBlock(content="raw **verbatim**", format="markdown")])
    md = render_markdown(doc)
    assert "raw **verbatim**" in md


def test_render_raw_block_confluence_storage() -> None:
    doc = Document(children=[RawBlock(content="<p>xml</p>", format="confluence-storage")])
    md = render_markdown(doc)
    assert "```confluence-xml" in md
    assert "<p>xml</p>" in md


def test_render_raw_block_html() -> None:
    doc = Document(children=[RawBlock(content="<div>html</div>", format="html")])
    md = render_markdown(doc)
    assert "<div>html</div>" in md


def test_render_table() -> None:
    doc = Document(
        children=[
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("A")])], header=True),
                            TableCell(children=[Paragraph(inlines=[Text("B")])], header=True),
                        ]
                    ),
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("1")])]),
                            TableCell(children=[Paragraph(inlines=[Text("2")])]),
                        ]
                    ),
                ],
                has_header=True,
            )
        ]
    )
    md = render_markdown(doc)
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md
    assert "---" in md


def test_render_table_alignment() -> None:
    doc = Document(
        children=[
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("L")])], header=True),
                            TableCell(children=[Paragraph(inlines=[Text("C")])], header=True),
                            TableCell(children=[Paragraph(inlines=[Text("R")])], header=True),
                        ]
                    ),
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("1")])]),
                            TableCell(children=[Paragraph(inlines=[Text("2")])]),
                            TableCell(children=[Paragraph(inlines=[Text("3")])]),
                        ]
                    ),
                ],
                has_header=True,
                align=["left", "center", "right"],
            )
        ]
    )
    md = render_markdown(doc)
    assert ":---" in md
    assert ":---:" in md
    assert "---:" in md


def test_render_table_merged_cells_html_fallback() -> None:
    doc = Document(
        children=[
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(
                                children=[Paragraph(inlines=[Text("merged")])],
                                header=False,
                                colspan=2,
                            ),
                        ]
                    ),
                ],
                has_header=False,
            )
        ]
    )
    md = render_markdown(doc)
    assert "<table>" in md
    assert 'colspan="2"' in md


def test_render_layout() -> None:
    doc = Document(
        children=[
            Layout(
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
        ]
    )
    md = render_markdown(doc)
    assert ":::layout" in md
    assert "left" in md
    assert "right" in md


def test_callout_inside_layout_cell_uses_deeper_fence() -> None:
    """A callout nested inside ``:::::layout-cell`` (5 colons) must use a
    fence count strictly greater than 5 — otherwise its ``:::`` close
    fence collides with the outer ``:::layout`` close and the markdown
    reader prematurely terminates the outermost div.
    """
    doc = Document(
        children=[
            Layout(
                sections=[
                    LayoutSection(
                        layout_type="two_equal",
                        cells=[
                            LayoutCell(
                                children=[
                                    Callout(
                                        kind="tip",
                                        body=[Paragraph(inlines=[Text("hello")])],
                                    ),
                                    Paragraph(inlines=[Text("after callout")]),
                                ]
                            ),
                            LayoutCell(children=[Paragraph(inlines=[Text("right")])]),
                        ],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    # Outer layout uses 3 colons, section 4, cell 5. The callout must use ≥6
    # so its close cannot be misparsed as a 3-colon layout close.
    assert "::::::callout-tip" in md, f"expected nested callout to use ≥6 colons, got:\n{md}"


def test_callout_inside_layout_cell_roundtrips() -> None:
    """Round-trip a callout inside a two-column layout cell with trailing
    paragraphs. Without depth-aware fences the callout's ``:::`` close
    pairs with the outer ``:::layout`` open and the trailing paragraphs
    escape the layout entirely.
    """
    doc = Document(
        children=[
            Layout(
                sections=[
                    LayoutSection(
                        layout_type="two_equal",
                        cells=[
                            LayoutCell(
                                children=[
                                    Callout(
                                        kind="tip",
                                        body=[Paragraph(inlines=[Text("tip body")])],
                                    ),
                                    Paragraph(inlines=[Text("After the callout.")]),
                                ]
                            ),
                            LayoutCell(children=[Paragraph(inlines=[Text("right cell")])]),
                        ],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    rt = parse_markdown(md)

    assert len(rt.children) == 1, (
        f"layout should be the only top-level block, got {len(rt.children)}:\n{md}"
    )
    layout = rt.children[0]
    assert isinstance(layout, Layout)
    section = layout.sections[0]
    assert len(section.cells) == 2

    left_cell = section.cells[0]
    assert len(left_cell.children) == 2, (
        f"left cell must keep both children (callout + paragraph), got "
        f"{len(left_cell.children)} from:\n{md}"
    )
    assert isinstance(left_cell.children[0], Callout)
    assert left_cell.children[0].kind == "tip"
    assert isinstance(left_cell.children[1], Paragraph)

    right_cell = section.cells[1]
    assert len(right_cell.children) == 1
    assert isinstance(right_cell.children[0], Paragraph)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


def test_roundtrip_heading() -> None:
    md = "# Hello\n"
    rt = parse_markdown(render_markdown(parse_markdown(md)))
    h = rt.children[0]
    assert isinstance(h, Heading)
    assert h.inlines[0].content == "Hello"  # type: ignore[union-attr]


def test_roundtrip_paragraph() -> None:
    doc = Document(children=[Paragraph(inlines=[Text("Hello world")])])
    rt = parse_markdown(render_markdown(doc))
    p = rt.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Text)
    assert p.inlines[0].content == "Hello world"


def test_roundtrip_strikethrough() -> None:
    doc = Document(children=[Paragraph(inlines=[Strikethrough(tokens=[Text("struck")])])])
    rt = parse_markdown(render_markdown(doc))
    p = rt.children[0]
    assert isinstance(p, Paragraph)
    assert isinstance(p.inlines[0], Strikethrough)


def test_roundtrip_callout() -> None:
    doc = Document(children=[Callout(kind="info", body=[Paragraph(inlines=[Text("body text")])])])
    rt = parse_markdown(render_markdown(doc))
    c = rt.children[0]
    assert isinstance(c, Callout)
    assert c.kind == "info"


def test_roundtrip_confluence_macro() -> None:
    doc = Document(
        children=[
            ConfluenceMacro(
                name="toc",
                params={"minLevel": "1"},
                body=[],
                plain_body=None,
                rich_body=False,
            )
        ]
    )
    rt = parse_markdown(render_markdown(doc))
    cm = rt.children[0]
    assert isinstance(cm, ConfluenceMacro)
    assert cm.name == "toc"


def test_roundtrip_raw_block_confluence() -> None:
    doc = Document(children=[RawBlock(content="<p>xml</p>", format="confluence-storage")])
    rt = parse_markdown(render_markdown(doc))
    rb = rt.children[0]
    assert isinstance(rb, RawBlock)
    assert rb.format == "confluence-storage"
    assert rb.content == "<p>xml</p>"


def test_roundtrip_inline_macro() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[InlineMacro(name="status", params={"colour": "Blue", "title": "Pass"})]
            )
        ]
    )
    rt = parse_markdown(render_markdown(doc))
    p = rt.children[0]
    assert isinstance(p, Paragraph)
    im = p.inlines[0]
    assert isinstance(im, InlineMacro)
    assert im.name == "status"
    assert im.params["colour"] == "Blue"


def test_roundtrip_table() -> None:
    doc = Document(
        children=[
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("H1")])], header=True),
                        ]
                    ),
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("D1")])]),
                        ]
                    ),
                ],
                has_header=True,
                align=["left"],
            )
        ]
    )
    md = render_markdown(doc)
    rt = parse_markdown(md)
    tbl = rt.children[0]
    assert isinstance(tbl, Table)
    assert tbl.has_header is True


def test_every_node_roundtrip() -> None:
    """Build an IR with one of every block/inline type and verify structural round-trip."""
    doc = Document(
        children=[
            Heading(level=1, inlines=[Text("Title")]),
            Paragraph(
                inlines=[
                    Text("plain "),
                    Strong(tokens=[Text("bold")]),
                    Text(" "),
                    Emph(tokens=[Text("italic")]),
                    Text(" "),
                    Strikethrough(tokens=[Text("struck")]),
                    Text(" "),
                    Code(content="code"),
                    Text(" "),
                    Link(href="https://example.com", tokens=[Text("link")]),
                    Text(" "),
                    Image(src="https://example.com/img.png", alt="img"),
                    Text(" "),
                    SoftBreak(),
                    Text("more"),
                    LineBreak(),
                    Text("newline"),
                    Text(" "),
                    ConfluenceLink(
                        target_kind="page",
                        target="Home",
                        space_key="MDD",
                        body_tokens=[Text("home")],
                    ),
                    Text(" "),
                    ConfluenceImage(source_kind="attachment", source="file.png"),
                    Text(" "),
                    InlineMacro(name="status", params={"colour": "Green", "title": "OK"}),
                ]
            ),
            Heading(level=2, inlines=[Text("Lists")]),
            BulletList(
                items=[
                    ListItem(children=[Paragraph(inlines=[Text("bullet a")])]),
                    ListItem(
                        children=[Paragraph(inlines=[Text("task")])],
                        attributes={"task": "done"},
                    ),
                ]
            ),
            OrderedList(
                start=1,
                items=[
                    ListItem(children=[Paragraph(inlines=[Text("ordered")])]),
                ],
            ),
            BlockQuote(children=[Paragraph(inlines=[Text("quote")])]),
            HorizontalRule(),
            CodeBlock(content="x = 1", language="python"),
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("H")])], header=True),
                        ]
                    ),
                    TableRow(
                        cells=[
                            TableCell(children=[Paragraph(inlines=[Text("D")])]),
                        ]
                    ),
                ],
                has_header=True,
            ),
            Callout(kind="tip", body=[Paragraph(inlines=[Text("tip body")])]),
            ConfluenceMacro(name="toc", params={}, body=[], plain_body=None, rich_body=False),
            RawBlock(content="<p>html</p>", format="html"),
            RawBlock(content="<p>xml</p>", format="confluence-storage"),
        ]
    )

    md = render_markdown(doc)
    rt = parse_markdown(md)

    # Verify structural block types match in order.
    original_types = [type(b).__name__ for b in doc.children]
    rt_types = [type(b).__name__ for b in rt.children]
    assert rt_types == original_types, (
        f"Block type mismatch:\n  expected: {original_types}\n  got:      {rt_types}"
    )
