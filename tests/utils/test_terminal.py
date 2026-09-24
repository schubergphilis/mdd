"""Tests for mdd.utils.terminal."""

from __future__ import annotations

import pytest

from mdd.utils.terminal import neutralise_controls, neutralise_lines

PLACEHOLDER = "\ufffd"


class TestNeutraliseControls:
    def test_keeps_length_and_tab(self) -> None:
        raw = "a\x00b\tc\x7fd\x9fe"
        out = neutralise_controls(raw)
        assert out == f"a{PLACEHOLDER}b\tc{PLACEHOLDER}d{PLACEHOLDER}e"
        assert len(out) == len(raw)

    def test_replaces_bidi_overrides_only(self) -> None:
        # Explicit embedding/override/isolate controls are replaced; implicit
        # right-to-left text and the LRM/RLM marks pass through.
        raw = "a\u202eb\u2066c\u2069d\u200e\u05d0"
        out = neutralise_controls(raw)
        assert out == f"a{PLACEHOLDER}b{PLACEHOLDER}c{PLACEHOLDER}d\u200e\u05d0"
        assert len(out) == len(raw)

    def test_keeps_newline_replaces_carriage_return(self) -> None:
        assert neutralise_controls("a\nb\rc") == f"a\nb{PLACEHOLDER}c"

    @pytest.mark.parametrize(
        "sequence",
        [
            "\x1b[2K",  # ESC CSI erase line
            "\x9b1A",  # C1 CSI cursor up
            "\x1b]0;title\x07",  # OSC window title
            "\x1b]52;c;aGk=\x07",  # OSC clipboard write
            "\x1b[8m",  # SGR conceal
            "\u202e",  # right-to-left override
        ],
    )
    def test_no_escape_sequence_survives(self, sequence: str) -> None:
        out = neutralise_controls(f"before{sequence}after")
        assert out.startswith("before")
        assert out.endswith("after")
        assert not any(c in out for c in "\x1b\x9b\x07\u202e")

    def test_plain_text_unchanged(self) -> None:
        text = "Plain title: café, 日本語, tab\there"
        assert neutralise_controls(text) == text


class TestNeutraliseLines:
    def test_keeps_line_breaks_and_trailing_newline(self) -> None:
        assert neutralise_lines("a\x00b\nc\td\n") == f"a{PLACEHOLDER}b\nc\td\n"

    def test_keeps_leading_whitespace(self) -> None:
        text = "--- remote\n+++ local\n@@ -1 +1 @@\n context\n-old\n+new\n"
        assert neutralise_lines(text) == text

    def test_drops_carriage_return_at_line_end(self) -> None:
        assert neutralise_lines("one\r\ntwo\r\n") == "one\ntwo\n"

    def test_replaces_carriage_return_inside_line(self) -> None:
        assert neutralise_lines("one\rtwo") == f"one{PLACEHOLDER}two"

    def test_replaces_escape_sequences_per_line(self) -> None:
        out = neutralise_lines("+\x1b[1A\x1b[2Khidden\n-\x9b8m")
        assert out == f"+{PLACEHOLDER}[1A{PLACEHOLDER}[2Khidden\n-{PLACEHOLDER}8m"
