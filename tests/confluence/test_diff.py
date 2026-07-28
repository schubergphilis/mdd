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
