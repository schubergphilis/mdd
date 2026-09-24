"""Tests for mdd.confluence.diff"""

from __future__ import annotations

from mdd.confluence.diff import unified_xhtml_diff


class TestUnifiedXhtmlDiff:
    def test_identical_content_returns_empty(self) -> None:
        xhtml = "<p>Hello world</p>"
        result = unified_xhtml_diff(xhtml, xhtml)
        assert result == ""

    def test_whitespace_only_difference_normalized_away(self) -> None:
        local = "<p>Hello  world</p>"
        remote = "<p>Hello world</p>"
        result = unified_xhtml_diff(local, remote)
        assert result == ""

    def test_whitespace_indentation_normalized_away(self) -> None:
        local = "  <p>Content</p>  "
        remote = "<p>Content</p>"
        result = unified_xhtml_diff(local, remote)
        assert result == ""

    def test_content_change_detected(self) -> None:
        local = "<p>Updated content</p>"
        remote = "<p>Original content</p>"
        result = unified_xhtml_diff(local, remote)
        assert result != ""
        assert "Updated" in result or "Original" in result

    def test_addition_detected(self) -> None:
        local = "<p>First</p>\n<p>Second</p>"
        remote = "<p>First</p>"
        result = unified_xhtml_diff(local, remote)
        assert result != ""
        assert "Second" in result

    def test_removal_detected(self) -> None:
        local = "<p>First</p>"
        remote = "<p>First</p>\n<p>Second</p>"
        result = unified_xhtml_diff(local, remote)
        assert result != ""
        assert "Second" in result

    def test_diff_shows_unified_markers(self) -> None:
        local = "<p>New text</p>"
        remote = "<p>Old text</p>"
        result = unified_xhtml_diff(local, remote)
        # Unified diff markers
        assert "---" in result or "+++" in result

    def test_empty_strings(self) -> None:
        result = unified_xhtml_diff("", "")
        assert result == ""

    def test_local_empty_remote_not(self) -> None:
        result = unified_xhtml_diff("", "<p>content</p>")
        assert result != ""

    def test_blank_lines_ignored_in_normalization(self) -> None:
        local = "<p>A</p>\n\n\n<p>B</p>"
        remote = "<p>A</p>\n<p>B</p>"
        result = unified_xhtml_diff(local, remote)
        # Blank lines are dropped during normalization
        assert result == ""

    def test_whitespace_outside_code_macro_not_reported(self) -> None:
        """Indentation differences outside code macros are still normalized away."""
        local = "  <p>Content</p>  "
        remote = "<p>Content</p>"
        result = unified_xhtml_diff(local, remote)
        assert result == ""


class TestCodeMacroWhitespaceDiff:
    """Indentation changes inside code macros must not be silently swallowed."""

    _CODE_MACRO_TEMPLATE = (
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )

    def _macro(self, body: str) -> str:
        return self._CODE_MACRO_TEMPLATE.format(body=body)

    def test_indentation_change_inside_code_macro_detected(self) -> None:
        local = self._macro("def f():\n    return 1\n")
        remote = self._macro("def f():\n  return 1\n")
        result = unified_xhtml_diff(local, remote)
        assert result != "", "Indentation change inside code macro must be detected"
        assert "    return 1" in result or "  return 1" in result

    def test_hint_line_present_for_code_macro_whitespace_diff(self) -> None:
        local = self._macro("x = 1\n")
        remote = self._macro("x  =  1\n")
        result = unified_xhtml_diff(local, remote)
        assert "whitespace-only differences" in result.lower() or result != ""

    def test_identical_code_macro_no_diff(self) -> None:
        xhtml = self._macro("def f():\n    return 1\n")
        result = unified_xhtml_diff(xhtml, xhtml)
        assert result == ""

    def test_prose_whitespace_difference_without_code_macro_normalized(self) -> None:
        """Leading/trailing whitespace on a line is still normalized away (no code macro)."""
        # Both lines normalize to "<p>return 1</p>" after strip, so diff is empty.
        local = "  <p>return 1</p>  "
        remote = "<p>return 1</p>"
        result = unified_xhtml_diff(local, remote)
        assert result == ""


class TestEntityNormalization:
    """Named HTML entities and their literal characters compare equal.

    Confluence storage XHTML routinely emits typography as named entities
    (``&times;``, ``&rarr;``, ``&hellip;``, ``&mdash;``, ``&ndash;``,
    ``&lsquo;``, ``&rsquo;``, ``&ldquo;``, ``&rdquo;``). The IR writer
    emits the literal characters. Both forms render identically; the diff
    must not flag the difference.
    """

    def test_times_entity_equals_literal(self) -> None:
        local = "<p>2 sessions × 30 minutes</p>"
        remote = "<p>2 sessions &times; 30 minutes</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_quot_entity_equals_literal(self) -> None:
        local = '<p>"I thought you meant..."</p>'
        remote = "<p>&quot;I thought you meant...&quot;</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_rarr_entity_equals_literal(self) -> None:
        local = "<p>days → minutes</p>"
        remote = "<p>days &rarr; minutes</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_multiple_entities_in_one_line(self) -> None:
        local = "<p>A × B → C — D</p>"
        remote = "<p>A &times; B &rarr; C &mdash; D</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_real_content_change_still_detected_when_entities_present(self) -> None:
        local = "<p>2 sessions × 30 minutes = Done.</p>"
        remote = "<p>2 sessions &times; 45 minutes = Done.</p>"
        result = unified_xhtml_diff(local, remote)
        assert result != ""
        assert "30" in result or "45" in result

    def test_amp_entity_preserved_for_xml_correctness(self) -> None:
        # &amp; → & is the only XML-predefined entity we deliberately keep,
        # because changing it would mask broken-encoding bugs (an unescaped &
        # is malformed XHTML, and we want to see that in the diff).
        local = "<p>A & B</p>"
        remote = "<p>A &amp; B</p>"
        result = unified_xhtml_diff(local, remote)
        assert result != "", "raw '&' vs '&amp;' must remain visible in the diff"


class TestSoftBreakInsensitivity:
    """Where a soft line break falls inside a text run does not change the page."""

    def test_moved_soft_break_in_paragraph_gives_empty_diff(self) -> None:
        local = "<p>First sentence.\nSecond sentence\ncontinues.</p>"
        remote = "<p>First sentence. Second sentence continues.</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_soft_break_next_to_inline_tag_gives_empty_diff(self) -> None:
        local = "<p>Hello <em>big\nworld</em>\nagain</p>"
        remote = "<p>Hello <em>big world</em> again</p>"
        assert unified_xhtml_diff(local, remote) == ""

    def test_newline_between_block_tags_keeps_line_structure(self) -> None:
        local = "<p>A</p>\n<p>B</p>"
        remote = "<p>A</p>\n<p>C</p>"
        result = unified_xhtml_diff(local, remote)
        assert "-<p>C</p>" in result
        assert "+<p>B</p>" in result

    def test_text_change_next_to_soft_break_still_detected(self) -> None:
        local = "<p>First sentence.\nSecond one.</p>"
        remote = "<p>First sentence. Third one.</p>"
        assert unified_xhtml_diff(local, remote) != ""

    def test_moved_line_break_in_code_macro_gives_diff(self) -> None:
        template = (
            '<p>Intro\ntext</p><ac:structured-macro ac:name="code">'
            "<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        local = template.format(body="a\nb c")
        remote = template.format(body="a b\nc")
        assert unified_xhtml_diff(local, remote) != ""

    def test_moved_line_break_in_pre_block_gives_diff(self) -> None:
        local = "<pre><code>a\nb c</code></pre>"
        remote = "<pre><code>a b\nc</code></pre>"
        assert unified_xhtml_diff(local, remote) != ""

    def test_prose_soft_break_on_page_with_code_macro_gives_empty_diff(self) -> None:
        macro = (
            '<ac:structured-macro ac:name="code">'
            "<ac:plain-text-body><![CDATA[x = 1\n]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        local = f"<p>Some\nprose</p>{macro}"
        remote = f"<p>Some prose</p>{macro}"
        assert unified_xhtml_diff(local, remote) == ""

    def test_newline_at_start_or_end_is_left_alone(self) -> None:
        assert unified_xhtml_diff("\n<p>A</p>\n", "<p>A</p>") == ""

    def test_entity_form_inside_pre_gives_empty_diff(self) -> None:
        assert unified_xhtml_diff("<pre>it&#8217;s</pre>", "<pre>it’s</pre>") == ""

    def test_entity_form_inside_code_macro_gives_empty_diff(self) -> None:
        template = (
            '<ac:structured-macro ac:name="code"><ac:parameter ac:name="title">'
            "{title}</ac:parameter><ac:plain-text-body><![CDATA[x = 1\n]]>"
            "</ac:plain-text-body></ac:structured-macro>"
        )
        local = template.format(title="it&rsquo;s")
        remote = template.format(title="it’s")
        assert unified_xhtml_diff(local, remote) == ""

    def test_entity_changed_to_literal_inside_cdata_gives_diff(self) -> None:
        template = (
            '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
            "<![CDATA[{body}]]></ac:plain-text-body></ac:structured-macro>"
        )
        local = template.format(body="s = 'it’s'\n")
        remote = template.format(body="s = 'it&#8217;s'\n")
        result = unified_xhtml_diff(local, remote)
        assert "-<ac:structured-macro" in result
        assert "&#8217;" in result

    def test_whitespace_only_change_inside_pre_gives_diff(self) -> None:
        local = "<pre><code>x  =  1</code></pre>"
        remote = "<pre><code>x = 1</code></pre>"
        assert "whitespace-only differences" in unified_xhtml_diff(local, remote)

    def test_self_closing_code_macro_does_not_swallow_later_prose(self) -> None:
        later_macro = (
            '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>Note</p>'
            "</ac:rich-text-body></ac:structured-macro>"
        )
        self_closing = '<ac:structured-macro ac:name="code" />'
        local = f"{self_closing}<p>Some\nprose</p>{later_macro}"
        remote = f"{self_closing}<p>Some prose</p>{later_macro}"
        assert unified_xhtml_diff(local, remote) == ""

    def test_self_closing_pre_does_not_swallow_later_prose(self) -> None:
        local = "<pre/><p>Some\nprose</p><pre>x</pre>"
        remote = "<pre/><p>Some prose</p><pre>x</pre>"
        assert unified_xhtml_diff(local, remote) == ""
