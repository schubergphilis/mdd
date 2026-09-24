"""Reader behaviour on oversized or malformed remote page bodies.

The storage reader must finish in time and memory proportional to the
document for any attribute value, entity count or nesting depth the remote
page happens to carry, and must never raise out of ``parse_confluence_storage``
for such input.
"""

from __future__ import annotations

import time
import warnings

import pytest
from lxml import etree

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.confluence.ir.elements.block import MAX_BLOCK_DEPTH
from mdd.confluence.ir.elements.table import read_span_attr
from mdd.ir.fallback import IRContext
from mdd.ir.nodes import BlockQuote, BulletList, Paragraph, RawBlock, Table


def _table(colspan: str, rowspan: str = "1") -> str:
    return (
        "<table><tbody><tr>"
        f'<td colspan="{colspan}" rowspan="{rowspan}" style="text-align: right">a</td>'
        "<td>b</td>"
        "</tr></tbody></table>"
    )


class TestTableSpanAttributes:
    def test_non_numeric_colspan_is_treated_as_one(self) -> None:
        doc = parse_confluence_storage(_table("x"))
        tbl = doc.children[0]
        assert isinstance(tbl, Table)
        assert tbl.rows[0].cells[0].colspan == 1
        assert tbl.align == ["right", "default"]

    def test_non_numeric_rowspan_is_treated_as_one(self) -> None:
        doc = parse_confluence_storage(_table("1", "abc"))
        tbl = doc.children[0]
        assert isinstance(tbl, Table)
        assert tbl.rows[0].cells[0].rowspan == 1

    def test_huge_colspan_parses_promptly_as_raw_block(self) -> None:
        started = time.perf_counter()
        doc = parse_confluence_storage(_table("99999999999"))
        assert time.perf_counter() - started < 1.0
        assert isinstance(doc.children[0], RawBlock)

    def test_five_thousand_digit_colspan_parses_promptly(self) -> None:
        started = time.perf_counter()
        doc = parse_confluence_storage(_table("9" * 5000))
        assert time.perf_counter() - started < 1.0
        assert isinstance(doc.children[0], RawBlock)

    def test_ordinary_span_is_kept_verbatim(self) -> None:
        doc = parse_confluence_storage(_table("2"))
        raw = doc.children[0]
        assert isinstance(raw, RawBlock)
        assert 'colspan="2"' in raw.content

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, 1),
            ("", 1),
            ("  ", 1),
            ("0", 1),
            ("-3", 1),
            ("2.5", 1),
            ("²", 1),
            ("3", 3),
            (" 7 ", 7),
            ("00001", 1),
            ("0" * 50 + "2", 2),
            ("0" * 50 + "2000", 1000),
            ("1000", 1000),
            ("1001", 1000),
            ("99999999999", 1000),
            ("9" * 5000, 1000),
        ],
    )
    def test_span_attr_helper(self, raw: str | None, expected: int) -> None:
        node = etree.Element("td")
        if raw is not None:
            node.set("colspan", raw)
        assert read_span_attr(node, "colspan") == expected


class TestRepeatedEntities:
    def test_seven_thousand_nbsp_parse_and_round_trip(self) -> None:
        body = "<p>" + "a&nbsp;" * 7000 + "</p>"
        doc = parse_confluence_storage(body, mode="preserving")
        assert isinstance(doc.children[0], Paragraph)
        assert render_confluence_storage(doc, mode="preserving") == body

    def test_seven_thousand_nbsp_parse_in_normalising_mode(self) -> None:
        body = "<table><tbody>" + "<tr><td>&nbsp;</td></tr>" * 7000 + "</tbody></table>"
        doc = parse_confluence_storage(body)
        tbl = doc.children[0]
        assert isinstance(tbl, Table)
        assert len(tbl.rows) == 7000

    def test_many_distinct_entities_share_one_marker_each(self) -> None:
        body = "<p>" + "&hellip;&mdash;&rsquo;&nbsp;" * 3000 + "</p>"
        doc = parse_confluence_storage(body, mode="preserving")
        assert render_confluence_storage(doc, mode="preserving") == body


class TestNestingDepth:
    def test_thousand_nested_blockquotes_parse_without_error(self) -> None:
        body = "<blockquote>" * 1000 + "<p>deep</p>" + "</blockquote>" * 1000
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            doc = parse_confluence_storage(body)
        assert isinstance(doc.children[0], BlockQuote)
        assert any("nested deeper" in fb.reason for fb in doc.fallbacks)

    def test_nesting_at_the_limit_is_read_structurally(self) -> None:
        # The innermost paragraph is itself a block, so it sits one level
        # below the deepest blockquote.
        depth = MAX_BLOCK_DEPTH - 1
        body = "<blockquote>" * depth + "<p>deep</p>" + "</blockquote>" * depth
        doc = parse_confluence_storage(body, mode="preserving")
        assert not doc.fallbacks
        node = doc.children[0]
        for _ in range(depth - 1):
            assert isinstance(node, BlockQuote)
            node = node.children[0]
        assert isinstance(node, BlockQuote)
        assert isinstance(node.children[0], Paragraph)

    def test_nesting_past_the_limit_is_kept_verbatim(self) -> None:
        depth = MAX_BLOCK_DEPTH
        body = "<blockquote>" * depth + "<p>deep</p>" + "</blockquote>" * depth
        doc = parse_confluence_storage(body, mode="preserving")
        assert len(doc.fallbacks) == 1
        assert "deep" in render_confluence_storage(doc, mode="preserving")

    def test_deeply_nested_lists_parse_without_error(self) -> None:
        body = "<ul><li>" * 300 + "leaf" + "</li></ul>" * 300
        doc = parse_confluence_storage(body)
        assert isinstance(doc.children[0], BulletList)
        assert doc.fallbacks

    def test_depth_counter_is_reset_after_parse(self) -> None:
        ctx = IRContext()
        body = "<blockquote>" * 10 + "<p>x</p>" + "</blockquote>" * 10
        parse_confluence_storage(body, ctx=ctx)
        assert ctx.depth == 0
