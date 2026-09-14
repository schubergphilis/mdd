"""Tests for inline span masking."""

from __future__ import annotations

from mdd.prose.inline import SpanClass, mask_flags, parse_link_target, scan, span_at


def spans(text: str) -> list[tuple[str, str]]:
    return [(span.cls.value, text[span.start : span.end]) for span in scan(text).masks]


def test_code_span_with_inner_backtick() -> None:
    assert spans("a ``b ` c`` d") == [("inline-code", "``b ` c``")]


def test_unclosed_backtick_is_literal() -> None:
    assert spans("a ` b") == []


def test_inline_link_masks_the_whole_construct() -> None:
    result = scan("see [the docs](a/b.md) now")
    assert [(s.cls, s.start, s.end) for s in result.masks] == [(SpanClass.LINK, 4, 22)]
    assert [(ref.target) for ref in result.links] == ["a/b.md"]


def test_image_is_masked_and_its_target_collected() -> None:
    result = scan("![alt](img.png)")
    assert result.masks[0].cls is SpanClass.LINK
    assert result.links[0].target == "img.png"


def test_reference_link_is_masked_without_a_target() -> None:
    result = scan("see [the docs][ref]")
    assert result.masks[0].cls is SpanClass.LINK
    assert result.links == ()


def test_footnote_reference() -> None:
    assert spans("a[^1] b") == [("footnote-ref", "[^1]")]


def test_autolink_and_raw_html() -> None:
    assert spans("<https://x.test/a,b> and <span class='x'>") == [
        ("autolink", "<https://x.test/a,b>"),
        ("raw-html", "<span class='x'>"),
    ]


def test_mailto_style_autolink() -> None:
    assert spans("<a@b.test>") == [("autolink", "<a@b.test>")]


def test_bare_angle_bracket_is_not_masked() -> None:
    assert spans("a < b") == []


def test_inline_math() -> None:
    assert spans("$a, b$ c") == [("math", "$a, b$")]


def test_dollar_before_space_is_not_math() -> None:
    assert spans("$ 5 and 6") == []


def test_escape_is_masked() -> None:
    assert spans(r"a \. b") == [("escape", r"\.")]


def test_start_offset_skips_a_prefix() -> None:
    assert scan("`x` y", start=3).masks == ()


def test_link_inside_link_text_does_not_break_matching() -> None:
    assert spans("[a [b] c](t.md)") == [("link", "[a [b] c](t.md)")]


def test_unclosed_bracket_is_literal() -> None:
    assert spans("a [b c") == []


def test_bracket_without_destination_is_literal() -> None:
    assert spans("a [b] c") == []


def test_parse_link_target_variants() -> None:
    assert parse_link_target(' a/b.md "title" ') == "a/b.md"
    assert parse_link_target("<a b.md>") == "a b.md"
    assert parse_link_target("   ") == ""


def test_mask_flags_and_span_at() -> None:
    result = scan("a `b` c")
    flags = mask_flags(7, result.masks)
    assert flags == [False, False, True, True, True, False, False]
    assert span_at(result.masks, 3) is not None
    assert span_at(result.masks, 0) is None
