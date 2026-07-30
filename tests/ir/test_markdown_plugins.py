"""Tests for the custom markdown-it-py plugins.

Covers parse + render-and-reparse for each plugin's syntax.
"""

from __future__ import annotations

import time

from mdd.ir.document import Document
from mdd.ir.nodes import (
    Callout,
    ConfluenceMacro,
    InlineMacro,
    Paragraph,
    RawInline,
    Text,
)
from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.markdown.ir._patterns import ATTR_RE, INLINE_MACRO_RE
from mdd.markdown.ir.flavour import build_md
from mdd.markdown.ir.reader import macros as reader_macros

# ---------------------------------------------------------------------------
# Fenced div plugin (callouts.py)
# ---------------------------------------------------------------------------


class TestFencedDivPlugin:
    def test_callout_tip_parses(self) -> None:
        doc = parse_markdown(":::callout-tip\nThis is a tip.\n:::")
        assert len(doc.children) == 1
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "tip"

    def test_callout_info_parses(self) -> None:
        doc = parse_markdown(":::callout-info\nInfo content.\n:::")
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "info"

    def test_callout_note_parses(self) -> None:
        doc = parse_markdown(":::callout-note\nNote content.\n:::")
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "note"

    def test_callout_warning_parses(self) -> None:
        doc = parse_markdown(":::callout-warning\nWarning content.\n:::")
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "warning"

    def test_callout_panel_parses(self) -> None:
        doc = parse_markdown(":::callout-panel\nPanel content.\n:::")
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "panel"

    def test_callout_body_is_block_list(self) -> None:
        doc = parse_markdown(":::callout-tip\nFirst para.\n\nSecond para.\n:::")
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert len(c.body) == 2

    def test_callout_with_params(self) -> None:
        doc = parse_markdown(':::callout-tip {title="My Tip"}\nContent\n:::')
        c = doc.children[0]
        assert isinstance(c, Callout)
        assert c.params.get("title") == "My Tip"

    def test_callout_render_and_reparse(self) -> None:
        """Render a Callout to markdown, then parse it back."""
        original = Document(
            children=[Callout(kind="info", body=[Paragraph(inlines=[Text("Info body")])])]
        )
        md = render_markdown(original)
        assert ":::callout-info" in md
        assert ":::" in md
        rt = parse_markdown(md)
        c = rt.children[0]
        assert isinstance(c, Callout)
        assert c.kind == "info"

    def test_confluence_macro_parses(self) -> None:
        doc = parse_markdown(':::confluence-macro {name="toc"}\n\n:::')
        cm = doc.children[0]
        assert isinstance(cm, ConfluenceMacro)
        assert cm.name == "toc"

    def test_confluence_macro_render_and_reparse(self) -> None:
        original = Document(
            children=[
                ConfluenceMacro(
                    name="toc",
                    params={"minLevel": "2"},
                    body=[],
                    plain_body=None,
                    rich_body=False,
                )
            ]
        )
        md = render_markdown(original)
        assert ":::confluence-macro" in md
        rt = parse_markdown(md)
        cm = rt.children[0]
        assert isinstance(cm, ConfluenceMacro)
        assert cm.name == "toc"

    def test_fenced_div_not_triggered_for_unknown_names(self) -> None:
        # An unknown container name should NOT parse as a fenced div.
        doc = parse_markdown(":::custom-block\ncontent\n:::")
        # Should fall through to paragraph or some other parse.
        for block in doc.children:
            assert not isinstance(block, Callout)

    def test_callout_in_middle_of_document(self) -> None:
        md = "Before\n\n:::callout-tip\nTip text.\n:::\n\nAfter"
        doc = parse_markdown(md)
        assert len(doc.children) == 3
        assert isinstance(doc.children[1], Callout)


# ---------------------------------------------------------------------------
# Confluence inline macro plugin (inline_macros.py)
# ---------------------------------------------------------------------------


class TestConfluenceInlineMacroPlugin:
    def test_inline_macro_simple(self) -> None:
        doc = parse_markdown("{{confluence:toc}}")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert isinstance(p.inlines[0], InlineMacro)
        assert p.inlines[0].name == "toc"

    def test_inline_macro_with_params(self) -> None:
        doc = parse_markdown('{{confluence:status colour="Blue" title="Pass"}}')
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        im = p.inlines[0]
        assert isinstance(im, InlineMacro)
        assert im.name == "status"
        assert im.params["colour"] == "Blue"
        assert im.params["title"] == "Pass"

    def test_inline_macro_mid_sentence(self) -> None:
        doc = parse_markdown('Start {{confluence:status colour="Green" title="OK"}} end.')
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        texts = [t for t in p.inlines if isinstance(t, Text)]
        macros = [t for t in p.inlines if isinstance(t, InlineMacro)]
        assert any("Start" in t.content for t in texts)
        assert len(macros) == 1
        assert macros[0].name == "status"

    def test_inline_macro_render_and_reparse(self) -> None:
        original = Document(
            children=[
                Paragraph(
                    inlines=[InlineMacro(name="status", params={"colour": "Red", "title": "Fail"})]
                )
            ]
        )
        md = render_markdown(original)
        assert "{{confluence:status" in md
        rt = parse_markdown(md)
        p = rt.children[0]
        assert isinstance(p, Paragraph)
        im = p.inlines[0]
        assert isinstance(im, InlineMacro)
        assert im.name == "status"
        assert im.params["colour"] == "Red"

    def test_inline_macro_base64_roundtrip(self) -> None:
        """Macros with complex params use base64 encoding and survive a round-trip."""
        original = Document(
            children=[
                Paragraph(inlines=[InlineMacro(name="html", params={"body": "<b>hello</b>"})])
            ]
        )
        md = render_markdown(original)
        assert "{{confluence-raw:" in md
        rt = parse_markdown(md)
        p = rt.children[0]
        assert isinstance(p, Paragraph)
        # The round-trip produces a RawInline with the decoded XML content.
        raw = p.inlines[0]
        assert isinstance(raw, RawInline)
        assert "html" in raw.content
        assert "hello" in raw.content

    def test_multiple_inline_macros_in_one_paragraph(self) -> None:
        doc = parse_markdown(
            '{{confluence:status colour="Green" title="A"}} '
            '{{confluence:status colour="Red" title="B"}}'
        )
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        macros = [t for t in p.inlines if isinstance(t, InlineMacro)]
        assert len(macros) == 2


# ---------------------------------------------------------------------------
# Inline macro marker regex (_patterns.py) — ReDoS regression
# ---------------------------------------------------------------------------


class TestInlineMacroPatternRedos:
    """Pins the fix for CodeQL ``py/redos`` alerts 2 and 3.

    ``INLINE_MACRO_RE``'s attribute-key class used to be ``[^=}]+``, which
    matches whitespace and therefore overlaps the ``\\s+`` separator in front
    of it. For a non-matching input there were exponentially many ways to
    split each whitespace run between ``\\s+`` and the key, so backtracking
    blew up: ``{{confluence:-`` followed by N repetitions of ``  <=""`` took
    time exponential in N.
    """

    def test_pathological_input_fails_fast(self) -> None:
        evil = "{{confluence:-" + '  <=""' * 40
        start = time.perf_counter()
        assert INLINE_MACRO_RE.match(evil) is None
        elapsed = time.perf_counter() - start
        # The fixed pattern rejects this in microseconds. The bound is loose
        # on purpose (a loaded CI box must not flake); the pre-fix pattern
        # needed longer than the age of the universe at N=40.
        assert elapsed < 1.0, f"regex took {elapsed:.3f}s — exponential backtracking is back"

    def test_pathological_input_fails_fast_via_parser(self) -> None:
        """Same input through the full parse path, not just the bare regex."""
        evil = "{{confluence:-" + '  <=""' * 40
        start = time.perf_counter()
        doc = parse_markdown(evil)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"parse took {elapsed:.3f}s — exponential backtracking is back"
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        assert not [t for t in p.inlines if isinstance(t, InlineMacro)]

    def test_multiple_attributes_still_match(self) -> None:
        m = INLINE_MACRO_RE.match('{{confluence:status colour="Blue" title="Pass phrase"}}')
        assert m is not None
        assert m.group(1) == "status"
        params = {m2.group(1): m2.group(2) for m2 in ATTR_RE.finditer(m.group(2))}
        assert params == {"colour": "Blue", "title": "Pass phrase"}

    def test_no_attributes_still_match(self) -> None:
        m = INLINE_MACRO_RE.match("{{confluence:toc}}")
        assert m is not None
        assert m.group(1) == "toc"
        assert m.group(2) == ""

    def test_hyphenated_key_and_trailing_space_still_match(self) -> None:
        m = INLINE_MACRO_RE.match('{{confluence:mention account-id="557058:738d-4176" }}')
        assert m is not None
        params = {m2.group(1): m2.group(2) for m2 in ATTR_RE.finditer(m.group(2))}
        assert params == {"account-id": "557058:738d-4176"}

    def test_key_class_matches_the_attribute_parser(self) -> None:
        """A key the recogniser accepts must be one ``ATTR_RE`` can extract."""
        m = INLINE_MACRO_RE.match('{{confluence:x a.b="v"}}')
        assert m is None  # dotted key is not a key ATTR_RE can parse — reject outright

    def test_tokeniser_and_reader_share_one_pattern(self) -> None:
        """One definition, so a fix here cannot regress in only one module."""
        from mdd.markdown.ir import inline_macros

        assert inline_macros.INLINE_MACRO_RE is INLINE_MACRO_RE
        assert reader_macros.INLINE_MACRO_RE is INLINE_MACRO_RE


# ---------------------------------------------------------------------------
# Token-level checks on the raw parser
# ---------------------------------------------------------------------------


class TestRawParserTokens:
    def test_fenced_div_emits_container_tokens(self) -> None:
        md_parser = build_md()
        tokens = md_parser.parse(":::callout-tip\nhello\n:::")
        types = [t.type for t in tokens]
        assert "container_callout-tip_open" in types
        assert "container_callout-tip_close" in types

    def test_confluence_inline_token_emitted(self) -> None:
        md_parser = build_md()
        tokens = md_parser.parse("{{confluence:toc}}")
        inline_token = next(t for t in tokens if t.type == "inline")
        children = inline_token.children or []
        child_types = [c.type for c in children]
        assert "confluence_inline" in child_types

    def test_strikethrough_tokens(self) -> None:
        md_parser = build_md()
        tokens = md_parser.parse("~~struck~~")
        inline_token = next(t for t in tokens if t.type == "inline")
        children = inline_token.children or []
        child_types = [c.type for c in children]
        assert "s_open" in child_types
        assert "s_close" in child_types
