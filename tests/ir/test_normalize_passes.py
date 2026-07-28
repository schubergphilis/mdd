"""Tests for the normalisation pipeline — one test per pass plus idempotency.

See spec S31 §"Normalisation passes" for the contract each pass must uphold.
"""

from __future__ import annotations

from mdd.ir.document import Document
from mdd.ir.nodes import (
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    Heading,
    ListItem,
    OrderedList,
    Paragraph,
    SoftBreak,
    Table,
    TableCell,
    TableRow,
    Text,
)
from mdd.ir.normalize import (
    NORMALISING_PIPELINE,
    attach_callout_kind,
    collapse_soft_breaks,
    dedupe_attrs,
    default_ordered_start,
    drop_empty_paragraphs,
    normalise,
    normalise_entities,
    normalise_whitespace,
    sort_attrs,
    tighten_lists,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def doc(*children: object) -> Document:
    return Document(children=list(children))  # type: ignore[arg-type]


def para(*inlines: object) -> Paragraph:
    return Paragraph(inlines=list(inlines))  # type: ignore[arg-type]


def heading(level: int, *inlines: object) -> Heading:
    return Heading(level=level, inlines=list(inlines))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pass 1: collapse_soft_breaks
# ---------------------------------------------------------------------------


class TestCollapseSoftBreaks:
    def test_soft_break_in_paragraph_becomes_space(self) -> None:
        d = doc(para(Text("hello"), SoftBreak(), Text("world")))
        result = collapse_soft_breaks(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("hello"), Text(" "), Text("world")]

    def test_soft_break_in_heading_becomes_space(self) -> None:
        d = doc(heading(1, Text("A"), SoftBreak(), Text("B")))
        result = collapse_soft_breaks(d)
        h = result.children[0]
        assert isinstance(h, Heading)
        assert h.inlines == [Text("A"), Text(" "), Text("B")]

    def test_no_soft_break_unchanged(self) -> None:
        d = doc(para(Text("hello world")))
        result = collapse_soft_breaks(d)
        assert result == d

    def test_multiple_soft_breaks(self) -> None:
        d = doc(para(Text("a"), SoftBreak(), Text("b"), SoftBreak(), Text("c")))
        result = collapse_soft_breaks(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("a"), Text(" "), Text("b"), Text(" "), Text("c")]


# ---------------------------------------------------------------------------
# Pass 2: tighten_lists
# ---------------------------------------------------------------------------


class TestTightenLists:
    def test_bullet_list_with_single_para_items_becomes_tight(self) -> None:
        items = [ListItem(children=[para(Text("a"))]), ListItem(children=[para(Text("b"))])]
        d = doc(BulletList(items=items, tight=False))
        result = tighten_lists(d)
        bl = result.children[0]
        assert isinstance(bl, BulletList)
        assert bl.tight is True

    def test_ordered_list_with_single_para_items_becomes_tight(self) -> None:
        items = [ListItem(children=[para(Text("1"))]), ListItem(children=[para(Text("2"))])]
        d = doc(OrderedList(items=items, start=1, tight=False))
        result = tighten_lists(d)
        ol = result.children[0]
        assert isinstance(ol, OrderedList)
        assert ol.tight is True

    def test_list_with_multi_child_item_stays_loose(self) -> None:
        items = [
            ListItem(children=[para(Text("a")), para(Text("b"))]),
            ListItem(children=[para(Text("c"))]),
        ]
        d = doc(BulletList(items=items, tight=False))
        result = tighten_lists(d)
        bl = result.children[0]
        assert isinstance(bl, BulletList)
        assert bl.tight is False

    def test_empty_list_not_tightened(self) -> None:
        d = doc(BulletList(items=[], tight=False))
        result = tighten_lists(d)
        bl = result.children[0]
        assert isinstance(bl, BulletList)
        assert bl.tight is False


# ---------------------------------------------------------------------------
# Pass 3: default_ordered_start
# ---------------------------------------------------------------------------


class TestDefaultOrderedStart:
    def test_start_1_preserved_as_default(self) -> None:
        d = doc(OrderedList(items=[], start=1))
        result = default_ordered_start(d)
        ol = result.children[0]
        assert isinstance(ol, OrderedList)
        assert ol.start == 1

    def test_start_3_not_touched(self) -> None:
        d = doc(OrderedList(items=[], start=3))
        result = default_ordered_start(d)
        ol = result.children[0]
        assert isinstance(ol, OrderedList)
        assert ol.start == 3


# ---------------------------------------------------------------------------
# Pass 4: normalise_entities
# ---------------------------------------------------------------------------


class TestNormaliseEntities:
    def test_hellip_converted(self) -> None:
        d = doc(para(Text("wait&hellip;for it")))
        result = normalise_entities(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("wait…for it")]

    def test_mdash_converted(self) -> None:
        d = doc(para(Text("foo&mdash;bar")))
        result = normalise_entities(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("foo—bar")]

    def test_no_entities_unchanged(self) -> None:
        d = doc(para(Text("hello world")))
        result = normalise_entities(d)
        assert result == d

    def test_unknown_entity_left_alone(self) -> None:
        d = doc(para(Text("&unknown123;")))
        result = normalise_entities(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        # Unknown entities are left as-is.
        assert p.inlines == [Text("&unknown123;")]


# ---------------------------------------------------------------------------
# Pass 5: normalise_whitespace
# ---------------------------------------------------------------------------


class TestNormaliseWhitespace:
    def test_internal_whitespace_collapsed(self) -> None:
        d = doc(para(Text("hello   world")))
        result = normalise_whitespace(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("hello world")]

    def test_leading_whitespace_trimmed(self) -> None:
        d = doc(para(Text("  hello")))
        result = normalise_whitespace(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("hello")]

    def test_trailing_whitespace_trimmed(self) -> None:
        d = doc(para(Text("hello  ")))
        result = normalise_whitespace(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("hello")]

    def test_clean_text_unchanged(self) -> None:
        d = doc(para(Text("hello world")))
        result = normalise_whitespace(d)
        assert result == d


# ---------------------------------------------------------------------------
# Pass 6: drop_empty_paragraphs
# ---------------------------------------------------------------------------


class TestDropEmptyParagraphs:
    def test_empty_paragraph_removed(self) -> None:
        d = doc(Paragraph(), para(Text("keep")))
        result = drop_empty_paragraphs(d)
        assert len(result.children) == 1
        assert isinstance(result.children[0], Paragraph)

    def test_whitespace_only_paragraph_removed(self) -> None:
        d = doc(para(Text(" ")), para(Text("keep")))
        result = drop_empty_paragraphs(d)
        assert len(result.children) == 1

    def test_empty_text_paragraph_removed(self) -> None:
        d = doc(para(Text("")), para(Text("keep")))
        result = drop_empty_paragraphs(d)
        assert len(result.children) == 1

    def test_non_empty_paragraph_kept(self) -> None:
        d = doc(para(Text("content")))
        result = drop_empty_paragraphs(d)
        assert result == d

    def test_code_block_not_affected(self) -> None:
        d = doc(CodeBlock(content=""))
        result = drop_empty_paragraphs(d)
        assert len(result.children) == 1


# ---------------------------------------------------------------------------
# Pass 7: attach_callout_kind
# ---------------------------------------------------------------------------


class TestAttachCalloutKind:
    def test_tip_block_quote_becomes_callout(self) -> None:
        d = doc(BlockQuote(children=[para(Text("[!tip] This is a tip"))]))
        result = attach_callout_kind(d)
        c = result.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "tip"
        # Body has one paragraph with the rest of the text.
        assert len(c.body) == 1
        p = c.body[0]
        assert isinstance(p, Paragraph)
        assert p.inlines == [Text("This is a tip")]

    def test_note_block_quote_becomes_callout(self) -> None:
        d = doc(BlockQuote(children=[para(Text("[!note]"))]))
        result = attach_callout_kind(d)
        c = result.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "note"

    def test_warning_block_quote_becomes_callout(self) -> None:
        d = doc(BlockQuote(children=[para(Text("[!warning] watch out"))]))
        result = attach_callout_kind(d)
        c = result.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "warning"

    def test_info_and_panel_supported(self) -> None:
        for kind in ("info", "panel"):
            d = doc(BlockQuote(children=[para(Text(f"[!{kind}]"))]))
            result = attach_callout_kind(d)
            c = result.children[0]
            assert isinstance(c, Callout)
            assert c.kind == kind

    def test_case_insensitive_matching(self) -> None:
        d = doc(BlockQuote(children=[para(Text("[!TIP] Upper case"))]))
        result = attach_callout_kind(d)
        c = result.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "tip"

    def test_unknown_callout_kind_not_converted(self) -> None:
        d = doc(BlockQuote(children=[para(Text("[!unknown] nope"))]))
        result = attach_callout_kind(d)
        assert isinstance(result.children[0], BlockQuote)

    def test_plain_block_quote_not_converted(self) -> None:
        d = doc(BlockQuote(children=[para(Text("just a quote"))]))
        result = attach_callout_kind(d)
        assert isinstance(result.children[0], BlockQuote)

    def test_multi_paragraph_callout_body_preserved(self) -> None:
        d = doc(
            BlockQuote(
                children=[
                    para(Text("[!tip] title line")),
                    para(Text("second paragraph")),
                ]
            )
        )
        result = attach_callout_kind(d)
        c = result.children[0]
        assert isinstance(c, Callout)
        assert len(c.body) == 2


# ---------------------------------------------------------------------------
# Pass 8: dedupe_attrs
# ---------------------------------------------------------------------------


class TestDedupeAttrs:
    def test_colspan_1_removed(self) -> None:
        row = TableRow(
            cells=[
                TableCell(
                    children=[],
                    colspan=1,
                    rowspan=1,
                    attributes={"colspan": "1", "x": "y"},
                )
            ]
        )
        d = doc(Table(rows=[row]))
        result = dedupe_attrs(d)
        tbl = result.children[0]
        assert isinstance(tbl, Table)
        cell = tbl.rows[0].cells[0]
        assert "colspan" not in cell.attributes
        assert cell.attributes.get("x") == "y"

    def test_rowspan_1_removed(self) -> None:
        row = TableRow(cells=[TableCell(children=[], attributes={"rowspan": "1"})])
        d = doc(Table(rows=[row]))
        result = dedupe_attrs(d)
        tbl = result.children[0]
        assert isinstance(tbl, Table)
        cell = tbl.rows[0].cells[0]
        assert "rowspan" not in cell.attributes

    def test_non_default_attrs_kept(self) -> None:
        row = TableRow(cells=[TableCell(children=[], attributes={"colspan": "2"})])
        d = doc(Table(rows=[row]))
        result = dedupe_attrs(d)
        tbl = result.children[0]
        assert isinstance(tbl, Table)
        assert tbl.rows[0].cells[0].attributes.get("colspan") == "2"

    def test_block_without_attrs_unchanged(self) -> None:
        d = doc(para(Text("x")))
        result = dedupe_attrs(d)
        assert result == d


# ---------------------------------------------------------------------------
# Pass 9: sort_attrs
# ---------------------------------------------------------------------------


class TestSortAttrs:
    def test_attrs_sorted(self) -> None:
        d = doc(Paragraph(inlines=[], attributes={"z": "1", "a": "2", "m": "3"}))
        result = sort_attrs(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert list(p.attributes.keys()) == ["a", "m", "z"]

    def test_already_sorted_unchanged(self) -> None:
        d = doc(Paragraph(inlines=[], attributes={"a": "1", "b": "2"}))
        result = sort_attrs(d)
        p = result.children[0]
        assert isinstance(p, Paragraph)
        assert list(p.attributes.keys()) == ["a", "b"]

    def test_empty_attrs_unchanged(self) -> None:
        d = doc(para(Text("x")))
        result = sort_attrs(d)
        assert result == d


# ---------------------------------------------------------------------------
# Pipeline completeness + idempotency
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_pipeline_has_nine_passes(self) -> None:
        assert len(NORMALISING_PIPELINE) == 9

    def test_normalise_applies_all_passes(self) -> None:
        # Document that exercises several passes: soft break + entity + empty para.
        d = doc(
            para(Text("hello"), SoftBreak(), Text("&hellip; world")),
            Paragraph(),
        )
        result = normalise(d)
        # Empty paragraph dropped.
        assert len(result.children) == 1
        p = result.children[0]
        assert isinstance(p, Paragraph)
        # SoftBreak collapsed to space, entity converted to unicode.
        content = "".join(tok.content for tok in p.inlines if isinstance(tok, Text))
        assert "…" in content
        assert "SoftBreak" not in content

    def test_normalise_is_idempotent(self) -> None:
        d = doc(
            para(Text("  hello   "), SoftBreak(), Text("&hellip;")),
            Paragraph(),
            BulletList(
                items=[
                    ListItem(children=[para(Text("a"))]),
                    ListItem(children=[para(Text("b"))]),
                ]
            ),
        )
        once = normalise(d)
        twice = normalise(once)
        assert once == twice

    def test_normalise_empty_document(self) -> None:
        d = Document()
        result = normalise(d)
        assert result == d
