"""Frozen-dataclass equality + immutability checks for every IR node.

Spec S28 names `from_json(to_json(ir)) == ir` as a real invariant.
The pre-condition is that every node defines structural equality
and forbids field mutation. This module hand-builds at least one
instance of every block + inline class and asserts both.
"""

from __future__ import annotations

import dataclasses

import pytest

from mdd.ir import (
    ALL_CLASSES,
    BlockQuote,
    BulletList,
    Callout,
    Code,
    CodeBlock,
    ConfluenceImage,
    ConfluenceLink,
    ConfluenceMacro,
    Document,
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


def _sample_inline() -> list[object]:
    """One instance of every inline class, for equality testing."""
    return [
        Text("hi"),
        LineBreak(),
        SoftBreak(),
        Strong(tokens=[Text("bold")]),
        Emph(tokens=[Text("italic")]),
        Strikethrough(tokens=[Text("gone")]),
        Code("x"),
        Link(href="https://example.com", tokens=[Text("eg")]),
        ConfluenceLink(target_kind="page", target="Home"),
        Image(src="img.png", alt="a"),
        ConfluenceImage(source_kind="attachment", source="img.png"),
        InlineMacro(name="status", params={"colour": "green"}),
        Emoticon(name="smile"),
        Placeholder(content="todo"),
        RawInline(content="<x/>"),
    ]


def _sample_blocks() -> list[object]:
    """One instance of every block class."""
    return [
        HorizontalRule(),
        Heading(level=1, inlines=[Text("h")]),
        Paragraph(inlines=[Text("p")]),
        BulletList(items=[ListItem(children=[Paragraph(inlines=[Text("li")])])]),
        OrderedList(items=[ListItem(children=[Paragraph(inlines=[Text("li")])])], start=2),
        CodeBlock(content="x = 1", language="python"),
        BlockQuote(children=[Paragraph(inlines=[Text("q")])]),
        Table(
            rows=[
                TableRow(cells=[TableCell(children=[Paragraph(inlines=[Text("c")])])]),
            ],
            has_header=False,
            align=["left"],
        ),
        Callout(kind="info", body=[Paragraph(inlines=[Text("note")])]),
        ConfluenceMacro(name="excerpt", body=[Paragraph(inlines=[Text("e")])], rich_body=True),
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
        ),
        RawBlock(content="<x/>"),
    ]


class TestEquality:
    def test_text_equality(self) -> None:
        assert Text("hi") == Text("hi")
        assert Text("hi") != Text("ho")

    def test_inline_samples_equal_themselves(self) -> None:
        assert _sample_inline() == _sample_inline()

    def test_block_samples_equal_themselves(self) -> None:
        assert _sample_blocks() == _sample_blocks()

    def test_document_equality(self) -> None:
        a = Document(children=[Paragraph(inlines=[Text("p")])])
        b = Document(children=[Paragraph(inlines=[Text("p")])])
        assert a == b


class TestFrozen:
    def test_paragraph_is_frozen(self) -> None:
        p = Paragraph(inlines=[Text("p")])
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.node_id = "b00001"  # type: ignore[misc]

    def test_text_is_frozen(self) -> None:
        t = Text("hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.content = "bye"  # type: ignore[misc]


class TestRegistry:
    def test_all_classes_covers_every_node(self) -> None:
        expected = {type(b).__name__ for b in _sample_blocks()}
        expected |= {type(i).__name__ for i in _sample_inline()}
        expected |= {"TableRow", "TableCell", "ListItem", "LayoutSection", "LayoutCell"}
        missing = expected - set(ALL_CLASSES)
        assert not missing, f"ALL_CLASSES missing: {sorted(missing)}"

    def test_all_classes_lookup_constructs_instance(self) -> None:
        cls = ALL_CLASSES["Heading"]
        h = cls(level=2, inlines=[Text("hi")])  # type: ignore[call-arg]
        assert isinstance(h, Heading)
