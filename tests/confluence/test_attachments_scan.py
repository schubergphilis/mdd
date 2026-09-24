"""Tests for the code-blanking pass in front of the attachment scanner."""

from __future__ import annotations

import time

from mdd.confluence.attachments.scan import scan_local_image_refs, strip_code_for_scan


class TestStripCodeForScan:
    def test_fenced_block_blanked_but_newlines_kept(self) -> None:
        text = "a\n```\n![x](img.png)\n```\nb\n"
        result = strip_code_for_scan(text)
        assert result.count("\n") == text.count("\n")
        assert "img.png" not in result
        assert result.startswith("a\n")
        assert result.endswith("b\n")

    def test_single_backtick_span_blanked(self) -> None:
        text = "see `![x](a.png)` and ![y](b.png)"
        result = strip_code_for_scan(text)
        assert len(result) == len(text)
        assert "a.png" not in result
        assert "![y](b.png)" in result

    def test_double_backtick_span_with_inner_backtick(self) -> None:
        text = "``![x](a.png) ` still code`` ![y](b.png)"
        result = strip_code_for_scan(text)
        assert "a.png" not in result
        assert "still code" not in result
        assert "![y](b.png)" in result

    def test_span_closes_only_on_run_of_same_length(self) -> None:
        # The double-backtick opener is not closed by a single backtick.
        text = "``open ` ![x](a.png)"
        result = strip_code_for_scan(text)
        assert "![x](a.png)" in result

    def test_unmatched_run_is_literal_and_scan_continues(self) -> None:
        text = "x ``` `![x](a.png)` ![y](b.png)"
        result = strip_code_for_scan(text)
        assert "a.png" not in result
        assert "![y](b.png)" in result

    def test_four_backtick_span_blanked(self) -> None:
        text = "x ````![x](a.png)```` ![y](b.png)"
        result = strip_code_for_scan(text)
        assert "a.png" not in result
        assert "![y](b.png)" in result

    def test_multiline_span_keeps_newlines(self) -> None:
        text = "`line one\n![x](a.png)` ![y](b.png)"
        result = strip_code_for_scan(text)
        assert result.count("\n") == 1
        assert "a.png" not in result
        assert "![y](b.png)" in result

    def test_scan_ignores_code_but_finds_prose_refs(self) -> None:
        text = "```\n![x](a.png)\n```\n`![z](c.png)`\n![y](b.png)\n"
        assert scan_local_image_refs(text) == ["b.png"]

    def test_many_backtick_runs_finish_quickly(self) -> None:
        text = "a````" * 40_000
        start = time.perf_counter()
        strip_code_for_scan(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"inline code scan took {elapsed:.3f}s"

    def test_many_fence_openers_finish_quickly(self) -> None:
        text = "```x\n" * 40_000
        start = time.perf_counter()
        strip_code_for_scan(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"fence scan took {elapsed:.3f}s"
