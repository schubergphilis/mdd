"""Tests for mdd.search.output — formatters and ripgrep JSON parsing."""

from __future__ import annotations

import io
import json
from pathlib import Path

from mdd.search.color import Color
from mdd.search.output import (
    RgMatch,
    StreamingFormatter,
    Submatch,
    _format_match_line,  # pyright: ignore[reportPrivateUsage]
    _highlight_match_text,  # pyright: ignore[reportPrivateUsage]
    _parse_rg_json_lines,  # pyright: ignore[reportPrivateUsage]
    _read_frontmatter,  # pyright: ignore[reportPrivateUsage]
    _relative_display_path,  # pyright: ignore[reportPrivateUsage]
    _truncate_line,  # pyright: ignore[reportPrivateUsage]
    format_human,
    format_json,
)
from mdd.search.roots import MirrorRoot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
CONFLUENCE_MIRROR = FIXTURES / "confluence-mirror"
SHAREPOINT_MIRROR = FIXTURES / "sharepoint-mirror"


def _confluence_root(path: Path = CONFLUENCE_MIRROR) -> MirrorRoot:
    return MirrorRoot(
        path=path,
        mirror_name="confluence/ENGINEERING",
        source_type="confluence",
        identifier="ENGINEERING",
    )


def _sharepoint_root(path: Path = SHAREPOINT_MIRROR) -> MirrorRoot:
    return MirrorRoot(
        path=path,
        mirror_name="sharepoint/Engineering",
        source_type="sharepoint",
        identifier="Engineering",
    )


def _make_rg_json_line(
    path: str,
    line_number: int,
    text: str,
    *,
    submatches: list[tuple[int, int]] | None = None,
) -> str:
    data: dict[str, object] = {
        "path": {"text": path},
        "line_number": line_number,
        "lines": {"text": text},
    }
    if submatches is not None:
        data["submatches"] = [
            {"match": {"text": text[s:e]}, "start": s, "end": e} for s, e in submatches
        ]
    return json.dumps({"type": "match", "data": data})


# ---------------------------------------------------------------------------
# _parse_rg_json_lines
# ---------------------------------------------------------------------------


class TestParseRgJsonLines:
    def test_parses_match_records(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        line = _make_rg_json_line(str(f), 5, "some matching text\n")
        results = _parse_rg_json_lines(line)
        assert len(results) == 1
        assert results[0].path == f
        assert results[0].line_number == 5
        assert results[0].line_text == "some matching text"

    def test_ignores_non_match_records(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        begin = json.dumps({"type": "begin", "data": {"path": {"text": str(f)}}})
        match = _make_rg_json_line(str(f), 1, "hello")
        end = json.dumps({"type": "end", "data": {}})
        results = _parse_rg_json_lines("\n".join([begin, match, end]))
        assert len(results) == 1

    def test_handles_empty_output(self) -> None:
        assert _parse_rg_json_lines("") == []

    def test_handles_invalid_json_lines(self) -> None:
        bad = "not json\n" + _make_rg_json_line("/tmp/x.md", 1, "ok")  # noqa: S108  # literal path string for a parsing/path test; no temp file created
        results = _parse_rg_json_lines(bad)
        # Only the valid JSON line should produce a result
        assert len(results) == 1

    def test_multiple_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "a.md"
        lines = "\n".join(
            [
                _make_rg_json_line(str(f), 1, "first"),
                _make_rg_json_line(str(f), 3, "second"),
            ]
        )
        results = _parse_rg_json_lines(lines)
        assert len(results) == 2
        assert results[0].line_number == 1
        assert results[1].line_number == 3


# ---------------------------------------------------------------------------
# _read_frontmatter
# ---------------------------------------------------------------------------


class TestReadFrontmatter:
    def test_reads_title_and_page_id(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: My Page\npage_id: 99\n---\n\n# body\n")
        title, page_id = _read_frontmatter(f)
        assert title == "My Page"
        assert page_id == "99"

    def test_reads_nested_confluence_page_id(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: Test\nconfluence:\n  page_id: '1234'\n---\n\n# body\n")
        title, page_id = _read_frontmatter(f)
        assert title == "Test"
        assert page_id == "1234"

    def test_falls_back_to_h1_when_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# No frontmatter\n")
        title, page_id = _read_frontmatter(f)
        assert title == "No frontmatter"
        assert page_id is None

    def test_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        title, page_id = _read_frontmatter(tmp_path / "no-such.md")
        assert title is None
        assert page_id is None

    def test_falls_back_to_h1_when_frontmatter_lacks_title(self, tmp_path: Path) -> None:
        # Confluence sync stores page_id in frontmatter but the title as H1.
        f = tmp_path / "test.md"
        f.write_text(
            "---\nconfluence:\n  page_id: '7'\n  space_key: TEST\n---\n\n# The Real Title\n\nbody\n"
        )
        title, page_id = _read_frontmatter(f)
        assert title == "The Real Title"
        assert page_id == "7"

    def test_frontmatter_title_wins_over_h1(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\ntitle: From Frontmatter\n---\n\n# From Body\n")
        title, _ = _read_frontmatter(f)
        assert title == "From Frontmatter"

    def test_returns_none_when_no_title_and_no_h1(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("---\nconfluence:\n  page_id: '9'\n---\n\nNo H1 here at all.\n")
        title, page_id = _read_frontmatter(f)
        assert title is None
        assert page_id == "9"

    def test_h1_inside_frontmatter_is_ignored(self, tmp_path: Path) -> None:
        # A ``# X`` line inside the YAML block must not be picked up as the H1.
        f = tmp_path / "test.md"
        f.write_text(
            "---\n# this is a yaml comment\nconfluence:\n  page_id: '1'\n---\n\n# Body H1\n"
        )
        title, _ = _read_frontmatter(f)
        assert title == "Body H1"


# ---------------------------------------------------------------------------
# _relative_display_path
# ---------------------------------------------------------------------------


class TestRelativeDisplayPath:
    def test_path_relative_to_mirror(self, tmp_path: Path) -> None:
        mirror = _confluence_root(tmp_path / "mirror")
        f = tmp_path / "mirror" / "subdir" / "page.md"
        result = _relative_display_path(f, mirror)
        assert result == "confluence/ENGINEERING/subdir/page.md"

    def test_path_outside_mirror(self, tmp_path: Path) -> None:
        f = tmp_path / "other" / "page.md"
        result = _relative_display_path(f, None)
        assert result == str(f)

    def test_none_mirror(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        result = _relative_display_path(f, None)
        assert result == str(f)


# ---------------------------------------------------------------------------
# format_human
# ---------------------------------------------------------------------------


class TestFormatHuman:
    def test_basic_output(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text(
            "---\ntitle: My Page\nconfluence:\n  page_id: '42'\n---\n\n# Matching text here\n"
        )
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 7, "# Matching text here")
        output = format_human(rg_line, [root])
        assert "confluence/TEST" in output
        assert "My Page" in output
        assert "L7" in output
        assert "Matching text here" in output

    def test_frontmatter_match_excluded_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        # Line 2 is inside frontmatter (1=---, 2=title, 3=---)
        f.write_text("---\ntitle: Secret Title\n---\n\n# Body content\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        # Match on line 2 (inside frontmatter)
        rg_line = _make_rg_json_line(str(f), 2, "title: Secret Title")
        output = format_human(rg_line, [root], include_frontmatter=False)
        # Should be empty because the match is in frontmatter
        assert output == "" or "Secret Title" not in output

    def test_frontmatter_match_included_with_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: Secret Title\n---\n\n# Body content\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 2, "title: Secret Title")
        output = format_human(rg_line, [root], include_frontmatter=True)
        assert "Secret Title" in output

    def test_empty_output_for_empty_input(self) -> None:
        assert format_human("", []) == ""

    def test_title_derived_from_h1_for_confluence_synced_file(self, tmp_path: Path) -> None:
        # Confluence sync omits ``title:`` from frontmatter and renders the
        # page title as the first H1. mdd search should surface that title.
        f = tmp_path / "page.md"
        f.write_text(
            "---\nconfluence:\n  page_id: '42'\n  space_key: ENG\n---\n\n"
            "# Onboarding Guide\n\nWelcome to the team.\n"
        )
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/ENG",
            source_type="confluence",
            identifier="ENG",
        )
        rg_line = _make_rg_json_line(str(f), 8, "Welcome to the team.")
        output = format_human(rg_line, [root])
        assert "Title:" in output
        assert "Onboarding Guide" in output


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------


class TestFormatJson:
    def test_produces_json_records(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: My Page\nconfluence:\n  page_id: '99'\n---\n\n# Body\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 7, "# Body")
        output = format_json(rg_line, [root])
        assert output
        record = json.loads(output.splitlines()[0])
        assert record["mirror"] == "confluence/TEST"
        assert record["line"] == 7
        assert record["snippet"] == "# Body"
        assert record["title"] == "My Page"
        assert record["page_id"] == "99"

    def test_frontmatter_excluded_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: Secret\n---\n\n# Body\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        # Match on line 2 (inside frontmatter block 1-3)
        rg_line = _make_rg_json_line(str(f), 2, "title: Secret")
        output = format_json(rg_line, [root], include_frontmatter=False)
        assert output == ""

    def test_frontmatter_included_with_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: Secret\n---\n\n# Body\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 2, "title: Secret")
        output = format_json(rg_line, [root], include_frontmatter=True)
        assert output
        record = json.loads(output.splitlines()[0])
        assert record["snippet"] == "title: Secret"

    def test_empty_input_returns_empty(self) -> None:
        assert format_json("", []) == ""


# ---------------------------------------------------------------------------
# End-to-end: real ripgrep against fixture files
# ---------------------------------------------------------------------------


class TestFixtureEndToEnd:
    """End-to-end tests that run real ripgrep against fixture trees."""

    def test_rg_finds_laptop_in_confluence_fixture(self) -> None:
        import subprocess

        result = subprocess.run(
            ["rg", "--type", "md", "-n", "--json", "--smart-case", "--", "laptop"],
            cwd=str(CONFLUENCE_MIRROR),
            capture_output=True,
            text=True,
        )
        root = _confluence_root()
        output = format_human(result.stdout, [root])
        assert "Provision laptop" in output or "laptop" in output.lower()

    def test_rg_finds_laptop_in_sharepoint_fixture(self) -> None:
        import subprocess

        result = subprocess.run(
            ["rg", "--type", "md", "-n", "--json", "--smart-case", "--", "laptop"],
            cwd=str(SHAREPOINT_MIRROR),
            capture_output=True,
            text=True,
        )
        root = _sharepoint_root()
        output = format_human(result.stdout, [root])
        assert "Laptop provisioned" in output or "laptop" in output.lower()


# ---------------------------------------------------------------------------
# StreamingFormatter
# ---------------------------------------------------------------------------


class TestStreamingFormatter:
    def _make_root(self, tmp_path: Path) -> MirrorRoot:
        return MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )

    def test_emits_header_blank_then_match(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: P\nconfluence:\n  page_id: '1'\n---\n\n# Body\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
        )
        sf.consume(_make_rg_json_line(str(f), 7, "# Body"))
        out_lines = stream.getvalue().splitlines()
        assert out_lines[0].startswith("confluence/TEST/")
        assert out_lines[1] == "  Title: P"
        assert out_lines[2] == ""
        assert out_lines[3] == "  L7:  # Body"

    def test_total_limit_stops_consumer(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("a\nb\nc\nd\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=2,
            stream=stream,
        )
        assert sf.consume(_make_rg_json_line(str(f), 1, "match 1")) is True
        assert sf.consume(_make_rg_json_line(str(f), 2, "match 2")) is False
        # Further calls return False (limit reached) and emit nothing extra.
        assert sf.consume(_make_rg_json_line(str(f), 3, "match 3")) is False
        body = stream.getvalue()
        assert "match 1" in body
        assert "match 2" in body
        assert "match 3" not in body

    def test_json_mode_one_record_per_line(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: P\n---\n\n# Body\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=True,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
        )
        sf.consume(_make_rg_json_line(str(f), 5, "first"))
        sf.consume(_make_rg_json_line(str(f), 7, "second"))
        records = [json.loads(ln) for ln in stream.getvalue().splitlines() if ln]
        assert [r["line"] for r in records] == [5, 7]
        assert [r["snippet"] for r in records] == ["first", "second"]

    def test_frontmatter_match_skipped_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        # Lines 1-3 are frontmatter
        f.write_text("---\ntitle: Secret\n---\n\nbody\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
        )
        sf.consume(_make_rg_json_line(str(f), 2, "title: Secret"))
        # No output: the match fell inside the frontmatter block.
        assert stream.getvalue() == ""

    def test_blank_line_between_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f1.write_text("a\nb\n")
        f2 = tmp_path / "b.md"
        f2.write_text("a\nb\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
        )
        sf.consume(_make_rg_json_line(str(f1), 1, "in a"))
        sf.consume(_make_rg_json_line(str(f2), 1, "in b"))
        body = stream.getvalue()
        # Just before the second file's header line there should be a blank line.
        idx_b_header = body.index("confluence/TEST/b.md")
        preceding = body[:idx_b_header].rstrip("\n")
        assert body[len(preceding) : idx_b_header] == "\n\n"


# ---------------------------------------------------------------------------
# Submatch parsing + highlighting
# ---------------------------------------------------------------------------


class TestSubmatchHighlighting:
    def _make_root(self, tmp_path: Path) -> MirrorRoot:
        return MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )

    def test_streaming_wraps_match_in_ansi_when_color_enabled(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("# greetings world\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=True),
        )
        # "world" starts at byte/char 11 in "# greetings world"
        rg_line = _make_rg_json_line(str(f), 1, "# greetings world", submatches=[(12, 17)])
        sf.consume(rg_line)
        out = stream.getvalue()
        assert "\x1b[1;31mworld\x1b[0m" in out

    def test_streaming_no_ansi_when_color_disabled(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("# greetings world\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=False),
        )
        rg_line = _make_rg_json_line(str(f), 1, "# greetings world", submatches=[(12, 17)])
        sf.consume(rg_line)
        out = stream.getvalue()
        assert "\x1b[" not in out
        assert "world" in out

    def test_json_mode_forces_color_off(self, tmp_path: Path) -> None:
        """JSON output must never contain ANSI escapes even with Color(enabled=True)."""
        f = tmp_path / "page.md"
        f.write_text("# greetings world\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=True,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=True),
        )
        rg_line = _make_rg_json_line(str(f), 1, "# greetings world", submatches=[(12, 17)])
        sf.consume(rg_line)
        out = stream.getvalue()
        assert "\x1b[" not in out

    def test_byte_offset_to_char_offset_for_multibyte(self, tmp_path: Path) -> None:
        """Submatch char offset must account for multi-byte UTF-8 prefix bytes."""
        f = tmp_path / "page.md"
        f.write_text("→ greetings world\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=True),
        )
        # "→" is 3 bytes in UTF-8; "world" starts at byte 14, char 12.
        text = "→ greetings world"
        encoded = text.encode("utf-8")
        byte_start = encoded.index(b"world")
        byte_end = byte_start + len("world")
        rg_line = _make_rg_json_line(str(f), 1, text, submatches=[(byte_start, byte_end)])
        sf.consume(rg_line)
        out = stream.getvalue()
        # The match must wrap exactly "world", not slice into something adjacent.
        assert "\x1b[1;31mworld\x1b[0m" in out

    def test_bulk_format_human_highlights(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: T\n---\n\n# foo bar\n")
        root = self._make_root(tmp_path)
        rg_line = _make_rg_json_line(str(f), 5, "# foo bar", submatches=[(2, 5)])
        out = format_human(rg_line, [root], color=Color(enabled=True))
        assert "\x1b[1;31mfoo\x1b[0m" in out


# ---------------------------------------------------------------------------
# Long-line truncation
# ---------------------------------------------------------------------------


class TestTruncateLine:
    def _make_root(self, tmp_path: Path) -> MirrorRoot:
        return MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )

    def test_short_line_passes_through(self, tmp_path: Path) -> None:

        text = "short line"
        subs = (Submatch(start=0, end=5),)
        out_text, out_subs = _truncate_line(text, subs, max_len=500)
        assert out_text == text
        assert out_subs == subs

    def test_long_line_with_match_at_start(self) -> None:

        text = "MATCH" + ("x" * 1000)
        subs = (Submatch(start=0, end=5),)
        out_text, out_subs = _truncate_line(text, subs, max_len=100)
        assert len(out_text) <= 102  # cap + at most two ellipses
        assert out_text.endswith("…")
        assert not out_text.startswith("…")  # match was at start, no left elision
        assert out_text[: out_subs[0].end][out_subs[0].start :] == "MATCH"

    def test_long_line_with_match_at_end(self) -> None:

        text = ("x" * 1000) + "MATCH"
        subs = (Submatch(start=1000, end=1005),)
        out_text, out_subs = _truncate_line(text, subs, max_len=100)
        assert out_text.startswith("…")
        assert not out_text.endswith("…")
        assert out_text[out_subs[0].start : out_subs[0].end] == "MATCH"

    def test_long_line_with_match_in_middle(self) -> None:

        text = ("x" * 500) + "MATCH" + ("x" * 500)
        subs = (Submatch(start=500, end=505),)
        out_text, out_subs = _truncate_line(text, subs, max_len=100)
        assert out_text.startswith("…")
        assert out_text.endswith("…")
        assert out_text[out_subs[0].start : out_subs[0].end] == "MATCH"
        # Body length is max_len (100) plus the two ellipses
        assert len(out_text) == 102

    def test_no_submatches_truncates_from_right(self) -> None:

        text = "x" * 1000
        out_text, out_subs = _truncate_line(text, (), max_len=50)
        assert len(out_text) == 50
        assert out_text.endswith("…")
        assert out_subs == ()

    def test_submatch_offsets_remain_consistent(self) -> None:
        """Highlighting must still wrap the exact match text after truncation."""
        text = ("a" * 1000) + "TARGET" + ("b" * 1000)
        subs = (Submatch(start=1000, end=1006),)
        new_text, new_subs = _truncate_line(text, subs, max_len=100)
        highlighted = _highlight_match_text(new_text, new_subs, Color(enabled=True))
        assert "\x1b[1;31mTARGET\x1b[0m" in highlighted

    def test_format_match_line_truncates_500(self, tmp_path: Path) -> None:
        """End-to-end: a >500 char match line gets shortened in the formatter."""

        long_text = ("x" * 600) + "FOO" + ("y" * 600)
        match = RgMatch(
            path=tmp_path / "page.md",
            line_number=42,
            line_text=long_text,
            submatches=(Submatch(start=600, end=603),),
        )
        out = _format_match_line(match, Color(enabled=False))
        # The label + "  " + body. The body should be ≤ 502 chars (500 + two ellipses).
        body = out.split(":  ", 1)[1]
        assert len(body) <= 502
        assert "FOO" in body
        assert body.startswith("…")
        assert body.endswith("…")

    def test_long_line_in_streaming_output(self, tmp_path: Path) -> None:
        """The streaming formatter applies the same truncation."""
        f = tmp_path / "page.md"
        f.write_text("# long\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=False,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=False),
        )
        long_text = ("a" * 700) + "needle" + ("b" * 700)
        # Submatch start = 700, end = 706 in the original UTF-8/char space (ASCII so same).
        rg_line = _make_rg_json_line(str(f), 1, long_text, submatches=[(700, 706)])
        sf.consume(rg_line)
        out = stream.getvalue()
        body_lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("L1:")]
        assert body_lines
        body = body_lines[0].split(":  ", 1)[1]
        assert "needle" in body
        assert len(body) <= 502
        assert body.startswith("…")
        assert body.endswith("…")

    def test_json_keeps_full_line(self, tmp_path: Path) -> None:
        """JSON snippet must not be truncated (machine consumer concern)."""
        f = tmp_path / "page.md"
        f.write_text("# long\n")
        root = self._make_root(tmp_path)
        stream = io.StringIO()
        sf = StreamingFormatter(
            [root],
            json_mode=True,
            include_frontmatter=False,
            total_limit=10,
            stream=stream,
            color=Color(enabled=False),
        )
        long_text = ("a" * 700) + "needle" + ("b" * 700)
        rg_line = _make_rg_json_line(str(f), 1, long_text, submatches=[(700, 706)])
        sf.consume(rg_line)
        record = json.loads(stream.getvalue().strip())
        assert record["snippet"] == long_text
