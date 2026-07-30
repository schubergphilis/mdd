"""Round-trip tests for `to_json` / `from_json`.

The invariants guarded here: round-trip equality, schema version,
stable key order, human-readable formatting.
"""

from __future__ import annotations

import json

import pytest

from mdd.ir import (
    MDD_IR_VERSION,
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
    FallbackEmitted,
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
    ValidationError,
    from_json,
    to_json,
)


def _every_node_doc() -> Document:
    """Hand-built document covering every block and inline class."""
    return Document(
        children=[
            HorizontalRule(node_id="b00001"),
            Heading(
                level=2,
                inlines=[Text("Hello "), Strong(tokens=[Text("world")])],
                node_id="b00002",
            ),
            Paragraph(
                inlines=[
                    Text("a "),
                    Emph(tokens=[Text("b")]),
                    Strikethrough(tokens=[Text("c")]),
                    LineBreak(),
                    SoftBreak(),
                    Code("d"),
                    Link(href="https://example.com", tokens=[Text("e")], title="t"),
                    ConfluenceLink(target_kind="page", target="Home", space_key="MDD"),
                    Image(src="i.png", alt="alt"),
                    ConfluenceImage(source_kind="attachment", source="a.png"),
                    InlineMacro(name="status", params={"colour": "green"}),
                    Emoticon(name="smile"),
                    Placeholder(content="todo"),
                    RawInline(content="<x/>"),
                ],
                node_id="b00003",
            ),
            BulletList(
                items=[ListItem(children=[Paragraph(inlines=[Text("li")], node_id="b00005")])],
                tight=True,
                node_id="b00004",
            ),
            OrderedList(
                items=[ListItem(children=[Paragraph(inlines=[Text("li")], node_id="b00007")])],
                start=3,
                node_id="b00006",
            ),
            CodeBlock(content="x = 1", language="python", info="python {.numbered}"),
            BlockQuote(
                children=[Paragraph(inlines=[Text("q")], node_id="b00009")], node_id="b00008"
            ),
            Table(
                rows=[
                    TableRow(
                        cells=[
                            TableCell(
                                children=[Paragraph(inlines=[Text("c")], node_id="b00011")],
                                header=True,
                            )
                        ]
                    ),
                ],
                has_header=True,
                align=["left", "right"],
                node_id="b00010",
            ),
            Callout(
                kind="info",
                title="Heads up",
                body=[Paragraph(inlines=[Text("body")], node_id="b00013")],
                node_id="b00012",
            ),
            ConfluenceMacro(
                name="excerpt",
                body=[Paragraph(inlines=[Text("e")], node_id="b00015")],
                rich_body=True,
                node_id="b00014",
            ),
            Layout(
                sections=[
                    LayoutSection(
                        layout_type="two_equal",
                        cells=[
                            LayoutCell(children=[Paragraph(inlines=[Text("L")], node_id="b00017")]),
                            LayoutCell(children=[Paragraph(inlines=[Text("R")], node_id="b00018")]),
                        ],
                    )
                ],
                node_id="b00016",
            ),
            RawBlock(content="<x/>", node_id="b00019"),
        ],
        page_title="Sample",
        node_id_counter=19,
        source_format="confluence-storage",
        parsed_at="2026-05-13T12:00:00Z",
        fallbacks=[
            FallbackEmitted(
                kind="block",
                source_format="confluence-storage",
                reason="unknown macro",
                content_preview="<x/>",
                path=("Document", "children", "13"),
            )
        ],
    )


class TestRoundtrip:
    def test_empty_document(self) -> None:
        doc = Document()
        assert from_json(to_json(doc)) == doc

    def test_every_node_roundtrips(self) -> None:
        doc = _every_node_doc()
        assert from_json(to_json(doc)) == doc


class TestSchemaVersion:
    def test_version_field_present(self) -> None:
        payload = json.loads(to_json(Document()))
        assert payload["mdd_ir_version"] == MDD_IR_VERSION

    def test_unknown_version_rejected(self) -> None:
        bad = json.dumps({"mdd_ir_version": 999, "root": {"type": "Document"}})
        with pytest.raises(ValidationError, match="unsupported mdd_ir_version"):
            from_json(bad)

    def test_missing_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing 'mdd_ir_version'"):
            from_json('{"root": {"type": "Document"}}')

    def test_missing_root_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing 'root'"):
            from_json('{"mdd_ir_version": 2}')

    def test_unknown_node_rejected(self) -> None:
        bad = json.dumps(
            {
                "mdd_ir_version": 2,
                "root": {
                    "type": "Document",
                    "children": [{"type": "BogusNode"}],
                },
            }
        )
        with pytest.raises(ValidationError, match="unknown IR node type"):
            from_json(bad)


class TestFormatting:
    def test_keys_sorted(self) -> None:
        out = to_json(Document(children=[Paragraph(inlines=[Text("p")])]))
        # Top-level keys must be alphabetical: mdd_ir_version then root.
        assert out.index('"mdd_ir_version"') < out.index('"root"')
        # And the nested Document object's keys must also be sorted.
        # Pick a few canonical neighbours.
        assert out.index('"children"') < out.index('"fallbacks"')

    def test_two_space_indent(self) -> None:
        out = to_json(Document(children=[Paragraph(inlines=[Text("p")])]))
        assert "\n  " in out
        assert "\n    " in out  # nested indent

    def test_ensure_ascii_false(self) -> None:
        doc = Document(children=[Paragraph(inlines=[Text("Café 🚀")])])
        out = to_json(doc)
        assert "Café 🚀" in out

    def test_stable_across_two_calls(self) -> None:
        doc = _every_node_doc()
        assert to_json(doc) == to_json(doc)
