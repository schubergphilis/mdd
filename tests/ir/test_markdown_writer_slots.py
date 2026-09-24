"""Round-trip of fence-header params, link destinations and inline code delimiters."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir.document import Document
from mdd.ir.nodes import Callout, Code, ConfluenceMacro, Image, Inline, Link, Paragraph, Text
from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.markdown.ir.writer.escape import escape_url
from mdd.markdown.ir.writer.inlines import (
    _longest_backtick_run,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Characters that stress the one-line fence header and the link destination.
_HOSTILE_ALPHABET = 'ab \t\n\r"\\{}[]()<>!&;#%:*_`~|=-\x00\x01\x0b\x0c\x1c\x7f\x85  é'
_PREFIX = "confluence-b64:"


def _seeded_rng() -> random.Random:
    """Return a fixed-seed generator so a failing input reproduces."""
    return random.Random(20260924)  # noqa: S311  # test input generation, not cryptography


def _random_value(rng: random.Random, max_len: int = 12) -> str:
    return "".join(rng.choice(_HOSTILE_ALPHABET) for _ in range(rng.randint(0, max_len)))


def _callout(params: dict[str, str]) -> Document:
    return Document(
        children=[Callout(kind="panel", params=params, body=[Paragraph(inlines=[Text("b")])])]
    )


def _macro(params: dict[str, str]) -> Document:
    return Document(
        children=[
            ConfluenceMacro(
                name="expand",
                params=params,
                body=[Paragraph(inlines=[Text("b")])],
                plain_body=None,
                rich_body=True,
            )
        ]
    )


def _header_line(md: str) -> str:
    return md.split("\n", 1)[0]


# ---------------------------------------------------------------------------
# Fence-header params
# ---------------------------------------------------------------------------


def test_panel_param_with_newline_survives_pull_and_push() -> None:
    storage = (
        '<ac:structured-macro ac:name="panel">'
        '<ac:parameter ac:name="borderColor">red\nsecond line</ac:parameter>'
        "<ac:rich-text-body><p>b</p></ac:rich-text-body></ac:structured-macro>"
    )
    md = render_markdown(parse_confluence_storage(storage))
    lines = md.splitlines()
    assert lines[0].startswith(':::callout-panel {borderColor="')
    assert lines[0].endswith('"}')
    assert lines[1] == "b"
    pushed = render_confluence_storage(parse_markdown(md))
    assert '<ac:parameter ac:name="borderColor">red\nsecond line</ac:parameter>' in pushed
    assert 'second line"}' not in pushed


def test_plain_param_values_are_written_verbatim() -> None:
    md = render_markdown(_callout({"title": 'say "hi" \\ <b>', "bgColor": "#fff"}))
    assert _header_line(md) == ':::callout-panel {title="say \\"hi\\" \\\\ <b>" bgColor="#fff"}'


@pytest.mark.parametrize(
    "value",
    ["red\nsecond", "a\rb", "a}b", "a\x00b", "a\x0bb", "a b", "a\x85b", f"{_PREFIX}xyz"],
)
def test_unsafe_param_values_are_base64_encoded(value: str) -> None:
    md = render_markdown(_callout({"k": value}))
    header = _header_line(md)
    assert header.startswith(f':::callout-panel {{k="{_PREFIX}')
    assert header.endswith('"}')
    rt = parse_markdown(md).children[0]
    assert isinstance(rt, Callout)
    assert rt.params == {"k": value}


def test_prefixed_value_that_is_not_base64_is_kept_as_written() -> None:
    md = f':::callout-panel {{k="{_PREFIX}not base64!"}}\nb\n\n:::\n'
    rt = parse_markdown(md).children[0]
    assert isinstance(rt, Callout)
    assert rt.params == {"k": f"{_PREFIX}not base64!"}


def test_prefixed_value_that_is_not_utf8_is_kept_as_written() -> None:
    md = f':::callout-panel {{k="{_PREFIX}/w=="}}\nb\n\n:::\n'
    rt = parse_markdown(md).children[0]
    assert isinstance(rt, Callout)
    assert rt.params == {"k": f"{_PREFIX}/w=="}


def test_macro_params_with_unsafe_values_roundtrip() -> None:
    params = {"title": "t\n![x](a/b.pdf)", "other": "plain"}
    md = render_markdown(_macro(params))
    assert "\n![x]" not in md
    assert 'other="plain"' in _header_line(md)
    rt = parse_markdown(md).children[0]
    assert isinstance(rt, ConfluenceMacro)
    assert rt.name == "expand"
    assert rt.params == params


@pytest.mark.parametrize("build", [_callout, _macro])
def test_random_param_values_roundtrip_on_one_header_line(
    build: Callable[[dict[str, str]], Document],
) -> None:
    rng = _seeded_rng()
    for _ in range(300):
        params = {f"k{i}": _random_value(rng) for i in range(rng.randint(1, 3))}
        md = render_markdown(build(params))
        children = parse_markdown(md).children
        assert len(children) == 1, (params, md)
        rt = children[0]
        assert isinstance(rt, (Callout, ConfluenceMacro))
        assert rt.params == params, (params, md)
        assert len(rt.body) == 1, (params, md)
        body = rt.body[0]
        assert isinstance(body, Paragraph), (params, md)
        assert body.inlines == [Text("b")], (params, md)


# ---------------------------------------------------------------------------
# Link and image destinations
# ---------------------------------------------------------------------------


def _roundtrip_inline(tok: Inline) -> list[Inline]:
    md = render_markdown(Document(children=[Paragraph(inlines=[tok])]))
    children = parse_markdown(md).children
    assert len(children) == 1, md
    para = children[0]
    assert isinstance(para, Paragraph), md
    return para.inlines


def test_href_with_newlines_survives_pull_and_push() -> None:
    storage = '<p><a href="http://a/&#10;[l]:x.md&#10;y">t</a></p>'
    md = render_markdown(parse_confluence_storage(storage))
    assert md == "[t](http://a/%0A[l]:x.md%0Ay)\n"
    assert render_confluence_storage(parse_markdown(md)) == storage


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("a b(c)", "a%20b%28c%29"),
        ("a\nb\rc\td", "a%0Ab%0Dc%09d"),
        ("<x>", "%3Cx%3E"),
        ("a\\)b", "a%5C%29b"),
        ("a&amp;b&#10;c&#x41;d", "a%26amp;b%26#10;c%26#x41;d"),
        ("x?q=1&r=2", "x?q=1&r=2"),
        ("a\x00b\x7fc", "a%00b%7Fc"),
        ("é%20[x]", "é%20[x]"),
        ("a\x85b\xa0c\u2028d", "a%C2%85b%C2%A0c%E2%80%A8d"),
    ],
)
def test_escape_url_encodes_characters_that_leave_the_destination(href: str, expected: str) -> None:
    assert escape_url(href) == expected


def test_random_hrefs_and_image_sources_roundtrip() -> None:
    rng = _seeded_rng()
    for _ in range(500):
        # A literal ``%XX`` is decoded on read by design; keep it out.
        target = "http://h/" + _random_value(rng, 16).replace("%", "")
        link = _roundtrip_inline(Link(href=target, tokens=[Text("t")]))
        assert link == [Link(href=target, tokens=[Text("t")])], repr(target)
        image = _roundtrip_inline(Image(src=target, alt="a"))
        assert image == [Image(src=target, alt="a")], repr(target)


# ---------------------------------------------------------------------------
# Inline code delimiter
# ---------------------------------------------------------------------------


def _old_ticks(content: str) -> str:
    n = 1
    while "`" * n in content:
        n += 1
    return "`" * n


def _render_code(content: str) -> str:
    return render_markdown(Document(children=[Paragraph(inlines=[Code(content=content)])]))


def test_longest_backtick_run_matches_previous_delimiter_choice() -> None:
    rng = _seeded_rng()
    for _ in range(2000):
        content = "".join(rng.choice("``` a\n") for _ in range(rng.randint(0, 40)))
        assert "`" * (_longest_backtick_run(content) + 1) == _old_ticks(content), repr(content)


@pytest.mark.parametrize("content", ["", "x", "`", "a``b", "``", "`a`", "a ``` b ` c"])
def test_inline_code_output_is_unchanged(content: str) -> None:
    ticks = _old_ticks(content)
    pad = " " if content.startswith("`") or content.endswith("`") else ""
    assert _render_code(content) == f"{ticks}{pad}{content}{pad}{ticks}\n"


def test_inline_code_with_a_million_backticks_renders_quickly() -> None:
    content = "`" * 1_000_000
    start = time.perf_counter()
    md = _render_code(content)
    elapsed = time.perf_counter() - start
    assert md.startswith("`" * 1_000_001 + " ")
    assert elapsed < 1.0
