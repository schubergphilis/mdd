"""The test-side oracle's printable reasons: where a change is, never what it says."""

from __future__ import annotations

from tests.prose.oracle import difference, first_changed_line


def test_identical_documents_have_no_difference() -> None:
    assert difference("One. Two.\n", "One. Two.\n") is None


def test_moved_line_break_is_no_difference() -> None:
    assert difference("One. Two.\n", "One.\nTwo.\n") is None


def test_changed_literal_block_is_named_by_ordinal_and_kind() -> None:
    before = "Intro.\n\n```\nsecret\n```\n"
    after = "Intro.\n\n```\nsecret  \n```\n"
    assert difference(before, after) == "literal block 1 of 1 (fence) changed"


def test_lost_literal_block_is_counted() -> None:
    reason = difference("    code\n", "code\n")
    assert reason == "the number of literal blocks went from 1 to 0"


def test_rendered_change_names_the_block_line_without_its_text() -> None:
    before = "First.\n\nSecond.\n\n# Heading\n"
    after = "First.\n\nSecond.\n- Heading\n"
    reason = difference(before, after)
    assert reason == "the rendered document changed, first in the block at line 5"


def test_removed_trailing_block_names_its_line() -> None:
    reason = difference("One.\n\nTwo.\n", "One.\n")
    assert reason == "the rendered document changed, first in the block at line 3"


def test_first_changed_line() -> None:
    assert first_changed_line("a\nb\nc\n", "a\nB\nc\n") == 2
    assert first_changed_line("a\n", "a\nb\n") == 2


def test_whitespace_inside_a_kbd_element_is_content() -> None:
    reason = difference("A <kbd>x  y</kbd> b.\n", "A <kbd>x y</kbd> b.\n")
    assert reason == "the rendered document changed, first in the block at line 1"


def test_whitespace_inside_an_xmp_element_across_blank_lines_is_content() -> None:
    before = "<xmp>\n\nfirst  column\n\n</xmp>\n"
    assert difference(before, "<xmp>\n\nfirst column\n\n</xmp>\n") is not None


def test_whitespace_after_a_closed_xmp_element_is_not_content() -> None:
    assert difference("<XMP>a</XMP> b  c\n", "<XMP>a</XMP> b c\n") is None
