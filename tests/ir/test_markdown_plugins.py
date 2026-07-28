"""Tests for the custom markdown-it-py plugins.

Covers parse + render-and-reparse for each plugin's syntax.
"""

from __future__ import annotations

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
from mdd.markdown.ir.flavour import build_md

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
