"""Tests for the shared fenced-code-block line scanner."""

from __future__ import annotations

import time

from mdd.utils.markdown_fences import (
    blank_spans,
    find_fenced_code_blocks,
    iter_fenced_code_blocks,
    remove_spans,
)


class TestFindFencedCodeBlocks:
    def test_no_fences(self) -> None:
        assert find_fenced_code_blocks("plain\ntext\n") == []

    def test_backtick_fence_span_excludes_trailing_newline(self) -> None:
        text = "Before\n```python\nx = 1\n```\nAfter"
        spans = find_fenced_code_blocks(text)
        assert len(spans) == 1
        start, end = spans[0]
        assert text[start:end] == "```python\nx = 1\n```"
        assert text[end] == "\n"

    def test_tilde_fence(self) -> None:
        text = "~~~\ncode\n~~~\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "~~~\ncode\n~~~"

    def test_closing_fence_must_use_same_character(self) -> None:
        text = "```\ncode\n~~~\nmore\n```\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "```\ncode\n~~~\nmore\n```"

    def test_longer_closing_fence_closes(self) -> None:
        text = "```\ncode\n`````\nafter\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "```\ncode\n`````"

    def test_shorter_run_does_not_close(self) -> None:
        text = "````\n```\nstill code\n````\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "````\n```\nstill code\n````"

    def test_closing_fence_tolerates_trailing_whitespace_and_indent(self) -> None:
        text = "```\ncode\n   ```  \t\nafter\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[1] :] == "\nafter\n"

    def test_closing_fence_with_text_after_it_does_not_close(self) -> None:
        text = "```\ncode\n``` not closing\n```\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "```\ncode\n``` not closing\n```"

    def test_four_space_indent_is_not_a_fence(self) -> None:
        assert find_fenced_code_blocks("    ```\n    code\n    ```\n") == []

    def test_unterminated_fence_runs_to_end(self) -> None:
        text = "prose\n```\nnever closed\n"
        assert find_fenced_code_blocks(text) == [(6, len(text))]

    def test_multiple_blocks(self) -> None:
        text = "```\na\n```\n\n~~~\nb\n~~~\n"
        spans = find_fenced_code_blocks(text)
        assert [text[s:e] for s, e in spans] == ["```\na\n```", "~~~\nb\n~~~"]

    def test_many_openers_finish_quickly(self) -> None:
        text = "```x\n" * 40_000
        start = time.perf_counter()
        spans = find_fenced_code_blocks(text)
        elapsed = time.perf_counter() - start
        assert len(spans) == 1
        assert elapsed < 1.0, f"fence scan took {elapsed:.3f}s"

    def test_crlf_fence_closes(self) -> None:
        text = "```\r\ncode\r\n```\r\nafter\r\n"
        (span,) = find_fenced_code_blocks(text)
        assert text[span[0] : span[1]] == "```\r\ncode\r\n```"


class TestIterFencedCodeBlocksFromPos:
    def test_pos_at_line_start_finds_block(self) -> None:
        text = "x\n```\nc\n```\n"
        assert list(iter_fenced_code_blocks(text, 2)) == [(2, 11)]

    def test_partial_line_at_pos_cannot_open_a_fence(self) -> None:
        text = "ab```\nc\n```\n"
        assert list(iter_fenced_code_blocks(text, 2)) == [(8, 12)]
        assert list(iter_fenced_code_blocks("x```", 1)) == []

    def test_fence_opened_before_pos_does_not_carry_over(self) -> None:
        text = "```\nx\n```\ncode\n```\n"
        # From the start, the second fence line closes the first block.
        assert list(iter_fenced_code_blocks(text)) == [(0, 9), (15, len(text))]
        # From just after the first opener line, that line is not seen, so the
        # second fence line opens a block that the third closes.
        assert list(iter_fenced_code_blocks(text, 4)) == [(6, 18)]

    def test_stops_early_when_only_the_first_block_is_wanted(self) -> None:
        text = "```\na\n```\n" + "```x\n" * 1000
        assert next(iter_fenced_code_blocks(text)) == (0, 9)


class TestSpanHelpers:
    def test_blank_spans_keeps_newlines(self) -> None:
        text = "ab\ncd\nef"
        assert blank_spans(text, [(1, 7)]) == "a \n  \n f"

    def test_blank_spans_empty(self) -> None:
        assert blank_spans("abc", []) == "abc"

    def test_remove_spans(self) -> None:
        text = "keep DROP keep DROP2 keep"
        assert remove_spans(text, [(5, 9), (15, 20)]) == "keep  keep  keep"

    def test_remove_spans_empty(self) -> None:
        assert remove_spans("abc", []) == "abc"
