"""Tests for `IdAllocator`, `assign_ids`, and `reattach`."""

from __future__ import annotations

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
