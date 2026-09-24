"""Tests for `IdAllocator`, `assign_ids`, and `reattach`."""

from __future__ import annotations

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir import (
    BulletList,
    ConfluenceLink,
    Document,
    Heading,
    Layout,
    LayoutCell,
    LayoutSection,
    ListItem,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    Text,
    assign_ids,
    reattach,
)
from mdd.ir.identity import IdAllocator
from mdd.markdown.ir import parse_markdown


def _storage_section(layout_type: str, n_cells: int, local_id: str) -> str:
    cells = "".join(f"<ac:layout-cell><p>cell{i}</p></ac:layout-cell>" for i in range(n_cells))
    return (
        f'<ac:layout-section ac:type="{layout_type}" ac:local-id="{local_id}">'
        f"{cells}</ac:layout-section>"
    )


def _markdown_section(layout_type: str, n_cells: int) -> str:
    cells = "".join(f":::::layout-cell\n\ncell{i}\n\n:::::\n" for i in range(n_cells))
    return f'::::layout-section layout_type="{layout_type}"\n{cells}::::\n'


class TestIdAllocator:
    def test_monotonic_b00001(self) -> None:
        a = IdAllocator()
        assert a.next() == "b00001"
        assert a.next() == "b00002"
        assert a.counter == 2

    def test_custom_start(self) -> None:
        a = IdAllocator(start=42)
        assert a.next() == "b00042"


class TestAssignIds:
    def test_assigns_to_top_level_blocks(self) -> None:
        doc = Document(
            children=[
                Paragraph(inlines=[Text("a")]),
                Paragraph(inlines=[Text("b")]),
            ]
        )
        out = assign_ids(doc)
        assert out.children[0].node_id == "b00001"  # type: ignore[union-attr]
        assert out.children[1].node_id == "b00002"  # type: ignore[union-attr]
        assert out.node_id_counter == 2

    def test_preserves_existing_ids(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Text("a")], node_id="b09999")])
        out = assign_ids(doc)
        assert out.children[0].node_id == "b09999"  # type: ignore[union-attr]

    def test_recurses_into_lists(self) -> None:
        doc = Document(
            children=[
                BulletList(
                    items=[
                        ListItem(children=[Paragraph(inlines=[Text("li")])]),
                    ]
                )
            ]
        )
        out = assign_ids(doc)
        bl: BulletList = out.children[0]  # type: ignore[assignment]
        assert bl.node_id == "b00001"
        assert bl.items[0].node_id == "b00002"
        assert bl.items[0].children[0].node_id == "b00003"  # type: ignore[union-attr]

    def test_recurses_into_layout(self) -> None:
        doc = Document(
            children=[
                Layout(
                    sections=[
                        LayoutSection(
                            layout_type="two_equal",
                            cells=[
                                LayoutCell(children=[Paragraph(inlines=[Text("L")])]),
                                LayoutCell(children=[Paragraph(inlines=[Text("R")])]),
                            ],
                        )
                    ]
                )
            ]
        )
        out = assign_ids(doc)
        layout: Layout = out.children[0]  # type: ignore[assignment]
        assert layout.node_id == "b00001"
        assert layout.sections[0].cells[0].children[0].node_id == "b00002"  # type: ignore[union-attr]
        assert layout.sections[0].cells[1].children[0].node_id == "b00003"  # type: ignore[union-attr]


class TestReattach:
    def test_grafts_node_id_on_matching_shape(self) -> None:
        cached = assign_ids(
            Document(children=[Paragraph(inlines=[Text("hi")], attributes={"ac:macro-id": "m1"})])
        )
        fresh = Document(children=[Paragraph(inlines=[Text("hi")])])
        merged = reattach(fresh, cached)
        assert merged.children[0].node_id == "b00001"  # type: ignore[union-attr]
        assert merged.children[0].attributes.get("ac:macro-id") == "m1"  # type: ignore[union-attr]

    def test_diverging_shape_keeps_fresh(self) -> None:
        cached = assign_ids(
            Document(children=[Heading(level=1, inlines=[Text("h")], attributes={"x": "1"})])
        )
        fresh = Document(children=[Paragraph(inlines=[Text("h")])])
        merged = reattach(fresh, cached)
        # Paragraph != Heading — no grafting, fresh's empty attributes stays.
        assert merged.children[0].attributes == {}  # type: ignore[union-attr]
        assert merged.children[0].node_id == ""  # type: ignore[union-attr]

    def test_extra_fresh_blocks_keep_their_state(self) -> None:
        cached = assign_ids(Document(children=[Paragraph(inlines=[Text("a")])]))
        fresh = Document(
            children=[
                Paragraph(inlines=[Text("a")]),
                Paragraph(inlines=[Text("b")]),  # new content
            ]
        )
        merged = reattach(fresh, cached)
        assert merged.children[0].node_id == "b00001"  # type: ignore[union-attr]
        assert merged.children[1].node_id == ""  # type: ignore[union-attr]

    def test_grafts_inline_identity_on_confluence_link(self) -> None:
        cached = Document(
            children=[
                Paragraph(
                    inlines=[
                        ConfluenceLink(
                            target_kind="page",
                            target="Home",
                            space_key="MDD",
                            attributes={"ac:macro-id": "lk1"},
                        )
                    ],
                    node_id="b00001",
                )
            ]
        )
        fresh = Document(
            children=[
                Paragraph(
                    inlines=[
                        ConfluenceLink(target_kind="page", target="Home"),
                    ]
                )
            ]
        )
        merged = reattach(fresh, cached)
        para: Paragraph = merged.children[0]  # type: ignore[assignment]
        link: ConfluenceLink = para.inlines[0]  # type: ignore[assignment]
        assert link.attributes.get("ac:macro-id") == "lk1"

    def test_layout_section_keeps_fresh_layout_type(self) -> None:
        """An authored `layout_type` change beats the cached `ac:type`."""
        cached = Document(
            children=[
                Layout(
                    sections=[
                        LayoutSection(
                            layout_type="two_equal",
                            cells=[LayoutCell(children=[Paragraph(inlines=[Text("a")])])],
                            attributes={"ac:type": "two_equal", "ac:local-id": "s1"},
                        )
                    ],
                    node_id="b00001",
                )
            ]
        )
        fresh = Document(
            children=[
                Layout(
                    sections=[
                        LayoutSection(
                            layout_type="three_equal",
                            cells=[LayoutCell(children=[Paragraph(inlines=[Text("a")])])],
                        )
                    ]
                )
            ]
        )
        merged = reattach(fresh, cached)
        layout: Layout = merged.children[0]  # type: ignore[assignment]
        section = layout.sections[0]
        assert section.layout_type == "three_equal"
        # `ac:type` is not grafted, so the writer falls back to `layout_type`.
        assert "ac:type" not in section.attributes
        # Every other cached attribute still grafts.
        assert section.attributes.get("ac:local-id") == "s1"

    def test_layout_section_insert_does_not_shift_types(self) -> None:
        """Inserting a section keeps every later section's authored type."""
        cached_storage = (
            "<ac:layout>"
            + _storage_section("fixed-width", 1, "s1")
            + _storage_section("two_equal", 2, "s2")
            + _storage_section("fixed-width", 1, "s3")
            + "</ac:layout>"
        )
        fresh_markdown = (
            ":::layout\n"
            + _markdown_section("fixed-width", 1)
            + _markdown_section("two_equal", 2)
            + _markdown_section("two_equal", 2)  # inserted before the footer
            + _markdown_section("fixed-width", 1)
            + ":::\n"
        )
        cached = parse_confluence_storage(cached_storage, mode="preserving")
        merged = reattach(parse_markdown(fresh_markdown), cached)
        layout: Layout = merged.children[0]  # type: ignore[assignment]
        assert [s.layout_type for s in layout.sections] == [
            "fixed-width",
            "two_equal",
            "two_equal",
            "fixed-width",
        ]
        out = render_confluence_storage(merged, mode="preserving")
        assert out.count('ac:type="two_equal"') == 2
        assert out.count('ac:type="fixed-width"') == 2

    def test_table_reattach(self) -> None:
        cached = Document(
            children=[
                Table(
                    rows=[
                        TableRow(
                            cells=[
                                TableCell(
                                    children=[Paragraph(inlines=[Text("c")], node_id="b00003")],
                                    attributes={"ac:local-id": "c1"},
                                )
                            ],
                            attributes={"ac:local-id": "r1"},
                        )
                    ],
                    node_id="b00001",
                )
            ]
        )
        fresh = Document(
            children=[
                Table(rows=[TableRow(cells=[TableCell(children=[Paragraph(inlines=[Text("c")])])])])
            ]
        )
        merged = reattach(fresh, cached)
        tbl: Table = merged.children[0]  # type: ignore[assignment]
        assert tbl.node_id == "b00001"
        assert tbl.rows[0].attributes.get("ac:local-id") == "r1"
        assert tbl.rows[0].cells[0].attributes.get("ac:local-id") == "c1"
        assert tbl.rows[0].cells[0].children[0].node_id == "b00003"  # type: ignore[union-attr]


def _publish(cached_storage: str, fresh_markdown: str) -> str:
    """Storage → IR, markdown → IR, reattach, render — the update-page path."""
    cached = parse_confluence_storage(cached_storage, mode="preserving")
    merged = reattach(parse_markdown(fresh_markdown), cached)
    return render_confluence_storage(merged, mode="preserving").strip()


class TestReattachInlineEdits:
    """Edits that markdown carries must survive, visible text or not."""

    @pytest.mark.parametrize(
        ("cached_storage", "fresh_markdown", "expected"),
        [
            pytest.param(
                '<p>see <a href="https://a.example/old">docs</a></p>',
                "see [docs](https://b.example/new)\n",
                '<p>see <a href="https://b.example/new">docs</a></p>',
                id="link-target-changed",
            ),
            pytest.param(
                '<p>see <a href="https://a.example/old">docs</a></p>',
                "see [the docs](https://b.example/new)\n",
                '<p>see <a href="https://b.example/new">the docs</a></p>',
                id="link-target-and-label-changed",
            ),
            pytest.param(
                "<p>see <strong>this</strong></p>",
                "see *this*\n",
                "<p>see <em>this</em></p>",
                id="strong-to-emph",
            ),
            pytest.param(
                "<p>see this</p>",
                "see that\n",
                "<p>see that</p>",
                id="plain-text-edited",
            ),
        ],
    )
    def test_edit_reaches_the_page(
        self, cached_storage: str, fresh_markdown: str, expected: str
    ) -> None:
        assert _publish(cached_storage, fresh_markdown) == expected

    def test_softbreak_collapse_keeps_cached_inlines(self) -> None:
        """The tolerance the short-circuit exists for: markdown drops SoftBreaks."""
        cached_storage = "<p>see\nthis</p>"
        assert _publish(cached_storage, "see this\n") == cached_storage

    def test_autolink_from_plain_text_keeps_cached_inlines(self) -> None:
        """A bare URL in text comes back as a `Link`; that is not an edit."""
        cached_storage = "<p>see https://example.com/docs</p>"
        assert _publish(cached_storage, "see https://example.com/docs\n") == cached_storage


_REMOTE_WARNING_PANEL = (
    '<ac:structured-macro ac:name="warning" ac:schema-version="1" ac:macro-id="m1">'
    '<ac:parameter ac:name="title">Remote</ac:parameter>'
    "<ac:rich-text-body><p>hi</p></ac:rich-text-body></ac:structured-macro>"
)

_REMOTE_HTML_MACRO = (
    '<ac:structured-macro ac:name="html" ac:schema-version="1" ac:macro-id="m2">'
    '<ac:parameter ac:name="foo">bar</ac:parameter>'
    "<ac:plain-text-body><![CDATA[<b>x</b>]]></ac:plain-text-body></ac:structured-macro>"
)

_REMOTE_TASK_LIST = (
    "<ac:task-list><ac:task><ac:task-id>7</ac:task-id>"
    "<ac:task-status>complete</ac:task-status><ac:task-body>task</ac:task-body>"
    "</ac:task></ac:task-list>"
)


class TestReattachBlockEdits:
    """Block-level edits that markdown carries must survive too."""

    def test_edited_code_block_keeps_its_own_characters(self) -> None:
        """Cached entity offsets are not spliced into different code text."""
        assert _publish("<pre><code>a &lt; b</code></pre>", "```\nx = 1\n```\n") == (
            "<pre><code>x = 1</code></pre>"
        )

    def test_unedited_code_block_keeps_cached_entities(self) -> None:
        cached_storage = "<pre><code>a &lt; b</code></pre>"
        assert _publish(cached_storage, "```\na < b\n```\n") == cached_storage

    def test_callout_kind_change_reaches_the_page(self) -> None:
        """An authored `warning` -> `info` change beats the cached `ac:name`."""
        out = _publish(_REMOTE_WARNING_PANEL, ":::callout-info\n\nhi\n\n:::\n")
        assert out.startswith(
            '<ac:structured-macro ac:name="info" ac:schema-version="1" ac:macro-id="m1">'
        )
        # The cached title belonged to the replaced panel.
        assert "Remote" not in out

    def test_same_callout_kind_restores_cached_title(self) -> None:
        assert _publish(_REMOTE_WARNING_PANEL, ":::callout-warning\n\nhi\n\n:::\n") == (
            _REMOTE_WARNING_PANEL
        )

    def test_macro_name_change_drops_cached_params_and_body(self) -> None:
        """A fresh `toc` at a cached `html` macro's position publishes as `toc`."""
        out = _publish(_REMOTE_HTML_MACRO, ':::confluence-macro {name="toc"}\n\n:::\n')
        assert out.startswith(
            '<ac:structured-macro ac:name="toc" ac:schema-version="1" ac:macro-id="m2">'
        )
        assert "<ac:parameter" not in out
        assert "<ac:plain-text-body>" not in out

    def test_same_macro_name_restores_cached_shape(self) -> None:
        assert _publish(_REMOTE_HTML_MACRO, ':::confluence-macro {name="html"}\n\n:::\n') == (
            _REMOTE_HTML_MACRO
        )

    def test_unnamed_macro_fence_takes_cached_name_and_shape(self) -> None:
        """The markdown leg may drop the name entirely; cached then fills it."""
        assert _publish(_REMOTE_HTML_MACRO, ":::confluence-macro\n\n:::\n") == _REMOTE_HTML_MACRO

    def test_plain_bullet_at_task_position_stays_plain(self) -> None:
        assert _publish(_REMOTE_TASK_LIST, "- task\n") == "<ul>\n<li>task</li>\n</ul>"

    def test_task_item_keeps_cached_task_id_and_own_status(self) -> None:
        out = _publish(_REMOTE_TASK_LIST, "- [ ] task\n")
        assert "<ac:task-id>7</ac:task-id>" in out
        assert "<ac:task-status>incomplete</ac:task-status>" in out
