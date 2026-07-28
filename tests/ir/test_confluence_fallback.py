"""Integration test: FallbackEmitted events surface through Document.fallbacks.

Validates spec S29 §"Fallback policy": every unknown element produces a
``FallbackEmitted`` event with ``kind="block"`` or ``kind="inline"`` and
``source_format="confluence-storage"``.
"""

from __future__ import annotations

from mdd.confluence.ir import parse_confluence_storage
from mdd.ir.fallback import IRContext
from mdd.ir.nodes import RawBlock, RawInline


class TestFallbackContract:
    def test_unknown_block_produces_fallback_event(self) -> None:
        ctx = IRContext()
        parse_confluence_storage(
            "<ac:foo-totally-unknown-element>content</ac:foo-totally-unknown-element>",
            ctx=ctx,
        )
        assert len(ctx.fallbacks) >= 1
        event = ctx.fallbacks[0]
        assert event.kind == "block"
        assert event.source_format == "confluence-storage"
        assert "content" in event.content_preview

    def test_unknown_block_lands_on_document_fallbacks(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:mystery-macro>secret</ac:mystery-macro>",
            ctx=ctx,
        )
        assert doc.fallbacks
        assert doc.fallbacks[0].kind == "block"
        assert doc.fallbacks[0].source_format == "confluence-storage"

    def test_document_fallbacks_equals_ctx_fallbacks(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:unknown1>a</ac:unknown1><ac:unknown2>b</ac:unknown2>",
            ctx=ctx,
        )
        assert len(doc.fallbacks) == len(ctx.fallbacks)
        assert doc.fallbacks[0].source_format == ctx.fallbacks[0].source_format

    def test_unknown_block_produces_raw_block(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:foo-unknown>content here</ac:foo-unknown>",
            ctx=ctx,
        )
        raw_blocks = [b for b in doc.children if isinstance(b, RawBlock)]
        assert raw_blocks
        assert raw_blocks[0].format == "confluence-storage"

    def test_unknown_inline_produces_fallback_event(self) -> None:
        ctx = IRContext()
        parse_confluence_storage(
            "<p><ac:unknown-inline>value</ac:unknown-inline></p>",
            ctx=ctx,
        )
        assert len(ctx.fallbacks) >= 1
        event = ctx.fallbacks[0]
        assert event.kind == "inline"
        assert event.source_format == "confluence-storage"

    def test_unknown_inline_produces_raw_inline(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<p><ac:unknown-inline>value</ac:unknown-inline></p>",
            ctx=ctx,
        )
        from mdd.ir.nodes import Paragraph

        p = doc.children[0]
        assert isinstance(p, Paragraph)
        raw_inlines = [t for t in p.inlines if isinstance(t, RawInline)]
        assert raw_inlines
        assert raw_inlines[0].format == "confluence-storage"

    def test_no_fallback_for_known_elements(self) -> None:
        ctx = IRContext()
        parse_confluence_storage(
            "<h1>Title</h1><p>Text</p><ul><li>item</li></ul>",
            ctx=ctx,
        )
        assert ctx.fallbacks == []

    def test_multiple_unknown_elements_accumulate(self) -> None:
        ctx = IRContext()
        doc = parse_confluence_storage(
            "<ac:unknown-a>x</ac:unknown-a><ac:unknown-b>y</ac:unknown-b>",
            ctx=ctx,
        )
        assert len(ctx.fallbacks) == 2
        assert len(doc.fallbacks) == 2

    def test_fallback_without_ctx_still_works(self) -> None:
        doc = parse_confluence_storage("<ac:totally-unknown>content</ac:totally-unknown>")
        assert len(doc.children) >= 1
        assert isinstance(doc.children[0], RawBlock)
        assert len(doc.fallbacks) >= 1
