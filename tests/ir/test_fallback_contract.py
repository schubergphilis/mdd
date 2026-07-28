"""Tests for `RawBlock` / `RawInline` + `IRContext` event plumbing."""

from __future__ import annotations

from mdd.ir import (
    FallbackEmitted,
    IRContext,
    RawBlock,
    RawInline,
    emit_block_fallback,
    emit_inline_fallback,
)


class TestEmitBlock:
    def test_returns_rawblock(self) -> None:
        rb = emit_block_fallback(
            "<weird/>", source_format="confluence-storage", reason="unknown macro"
        )
        assert isinstance(rb, RawBlock)
        assert rb.content == "<weird/>"
        assert rb.format == "confluence-storage"

    def test_records_event_when_ctx_given(self) -> None:
        ctx = IRContext()
        emit_block_fallback(
            "<weird/>",
            source_format="confluence-storage",
            reason="unknown macro",
            ctx=ctx,
            path=("doc", "children", "0"),
        )
        assert len(ctx.fallbacks) == 1
        ev = ctx.fallbacks[0]
        assert isinstance(ev, FallbackEmitted)
        assert ev.kind == "block"
        assert ev.source_format == "confluence-storage"
        assert ev.reason == "unknown macro"
        assert ev.content_preview == "<weird/>"
        assert ev.path == ("doc", "children", "0")

    def test_no_event_when_ctx_none(self) -> None:
        rb = emit_block_fallback(
            "<weird/>", source_format="confluence-storage", reason="unknown macro"
        )
        assert rb.content == "<weird/>"

    def test_format_override(self) -> None:
        rb = emit_block_fallback(
            "**md**",
            source_format="markdown",
            reason="unsupported",
            format_override="confluence-storage",
        )
        assert rb.format == "confluence-storage"

    def test_long_content_is_truncated_in_preview(self) -> None:
        ctx = IRContext()
        long = "x" * 500
        emit_block_fallback(long, source_format="xhtml", reason="big", ctx=ctx)
        assert len(ctx.fallbacks[0].content_preview) <= 80
        assert ctx.fallbacks[0].content_preview.endswith("…")


class TestEmitInline:
    def test_returns_rawinline(self) -> None:
        ri = emit_inline_fallback(
            "<ac:foo/>", source_format="confluence-storage", reason="unknown inline"
        )
        assert isinstance(ri, RawInline)
        assert ri.content == "<ac:foo/>"

    def test_records_inline_event(self) -> None:
        ctx = IRContext()
        emit_inline_fallback("<ac:foo/>", source_format="confluence-storage", reason="x", ctx=ctx)
        assert ctx.fallbacks[0].kind == "inline"


class TestIRContext:
    def test_starts_empty(self) -> None:
        ctx = IRContext()
        assert ctx.fallbacks == []

    def test_record_appends(self) -> None:
        ctx = IRContext()
        ctx.record(FallbackEmitted(kind="block", source_format="x", reason="y"))
        ctx.record(FallbackEmitted(kind="inline", source_format="x", reason="z"))
        assert len(ctx.fallbacks) == 2
        assert ctx.fallbacks[0].reason == "y"
        assert ctx.fallbacks[1].kind == "inline"
