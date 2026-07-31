"""Tests for mdd.commands.search."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mdd.cli import main as cli_main
from mdd.commands.search import (
    _build_rg_cmd,  # pyright: ignore[reportPrivateUsage]
    _build_rg_type_args,  # pyright: ignore[reportPrivateUsage]
    _check_rg,  # pyright: ignore[reportPrivateUsage]
)
from mdd.search.roots import MirrorRoot

FIXTURES = Path(__file__).parent.parent / "search" / "fixtures"
CONFLUENCE_MIRROR = FIXTURES / "confluence-mirror"
SHAREPOINT_MIRROR = FIXTURES / "sharepoint-mirror"


def cmd_search(args: list[str]) -> int:
    """Test helper: invoke `mdd search` via the argparse entry point."""
    return cli_main(["search", *args])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rg_json_line(path: str, line_number: int, text: str) -> str:
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": path},
                "line_number": line_number,
                "lines": {"text": text},
            },
        }
    )


class _FakePopen:
    """Minimal stand-in for ``subprocess.Popen`` driving the streaming consumer."""

    def __init__(self, lines: list[str], *, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = iter(line + "\n" for line in lines)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self._terminated = False

    def poll(self) -> int | None:
        return self.returncode if self._terminated else None

    def terminate(self) -> None:
        self._terminated = True

    def kill(self) -> None:
        self._terminated = True

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        self._terminated = True
        return self.returncode


def _empty_fake_popen(_cmd: list[str]) -> _FakePopen:
    """Return a fake Popen that produced no output (used when only argv matters)."""
    return _FakePopen([], returncode=1)


def _confluence_root(path: Path) -> MirrorRoot:
    return MirrorRoot(
        path=path,
        mirror_name="confluence/ENGINEERING",
        source_type="confluence",
        identifier="ENGINEERING",
    )


# ---------------------------------------------------------------------------
# _check_rg
# ---------------------------------------------------------------------------


class TestCheckRg:
    def test_returns_true_when_rg_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _which_found(name: str) -> str:
            return "/usr/bin/rg"

        monkeypatch.setattr("shutil.which", _which_found)
        assert _check_rg() is True

    def test_returns_false_and_prints_when_rg_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import logging

        def _which_none(name: str) -> None:
            return None

        monkeypatch.setattr("shutil.which", _which_none)
        # _check_rg now uses log.error. Force-configure logging on the mdd logger
        # so the error reaches a stderr StreamHandler that capsys can see.
        from mdd.utils.logging import configure as configure_logging

        _ = configure_logging(level=logging.ERROR)
        result = _check_rg()
        assert result is False
        captured = capsys.readouterr()
        assert "ripgrep" in captured.err
        assert "brew" in captured.err


# ---------------------------------------------------------------------------
# _build_rg_type_args
# ---------------------------------------------------------------------------


class TestBuildRgTypeArgs:
    def test_md_type(self) -> None:
        args = _build_rg_type_args("md")
        assert "--type" in args
        assert "md" in args

    def test_qmd_type_uses_glob(self) -> None:
        args = _build_rg_type_args("qmd")
        assert "--glob" in args
        assert "*.qmd" in args

    def test_all_type_includes_both(self) -> None:
        args = _build_rg_type_args("all")
        assert "md" in args
        assert "qmd:*.qmd" in args
        assert "qmd" in args


class TestBuildRgCmd:
    def test_per_file_limit_passed_via_max_count(self) -> None:
        root = _confluence_root(CONFLUENCE_MIRROR)
        cmd = _build_rg_cmd("q", [root], type_filter="md", per_file_limit=7)
        assert "--max-count" in cmd
        assert cmd[cmd.index("--max-count") + 1] == "7"

    def test_query_is_last_before_paths(self) -> None:
        root = _confluence_root(CONFLUENCE_MIRROR)
        cmd = _build_rg_cmd("hello", [root], type_filter="md", per_file_limit=10)
        # rg invocation should end with `-- <query> <paths...>`
        sep = cmd.index("--")
        assert cmd[sep + 1] == "hello"
        assert cmd[sep + 2] == str(CONFLUENCE_MIRROR)


# ---------------------------------------------------------------------------
# cmd_search argument parsing
# ---------------------------------------------------------------------------


class TestCmdSearchArgs:
    def _run(
        self,
        args: list[str],
        roots: list[MirrorRoot],
        rg_lines: list[str] | None = None,
        rg_returncode: int = 1,
        rg_stderr: str = "",
    ) -> tuple[int, str, str]:
        """Helper: run cmd_search with mocked roots and a fake streaming rg."""

        def mock_resolve(*a: Any, **kw: Any) -> list[MirrorRoot]:
            return roots

        def fake_open_rg(cmd: list[str]) -> _FakePopen:
            return _FakePopen(rg_lines or [], returncode=rg_returncode, stderr=rg_stderr)

        def fake_run_buffered(cmd: list[str]) -> tuple[int, str, str]:
            stdout = "\n".join(rg_lines or [])
            return rg_returncode, stdout, rg_stderr

        with (
            patch("mdd.commands.search.resolve_roots", mock_resolve),
            patch("mdd.commands.search._open_rg", fake_open_rg),
            patch("mdd.commands.search._run_buffered", fake_run_buffered),
            patch("mdd.commands.search._check_rg", return_value=True),
        ):
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                rc = cmd_search(args)
                out = sys.stdout.getvalue()
                err = sys.stderr.getvalue()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
        return rc, out, err

    def test_missing_query_exits(self) -> None:
        """argparse exits with code 2 when the required query positional is missing."""
        with pytest.raises(SystemExit) as exc_info:
            cmd_search([])
        assert exc_info.value.code == 2

    def test_empty_query_string_returns_1(self) -> None:
        rc, _, err = self._run([""], [])
        assert rc == 1
        assert "empty" in err.lower() or "query" in err.lower()

    def test_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_search(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "search" in captured.out.lower()

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_search(["--no-such-flag", "query"])
        assert exc_info.value.code == 2

    def test_no_roots_returns_0_with_message(self) -> None:
        rc, out, _ = self._run(["query"], [])
        assert rc == 0
        assert "No configured" in out

    def test_no_matches_returns_1_with_message(self) -> None:
        root = _confluence_root(CONFLUENCE_MIRROR)
        rc, out, _ = self._run(["unfindable_query_xyz"], [root], rg_lines=[], rg_returncode=1)
        assert rc == 1
        assert "No matches" in out

    def test_rg_error_exits_1(self) -> None:
        root = _confluence_root(CONFLUENCE_MIRROR)
        rc, _, _ = self._run(["query"], [root], rg_lines=[], rg_returncode=2, rg_stderr="boom")
        assert rc == 1

    def test_missing_rg_returns_1(self) -> None:
        with patch("mdd.commands.search._check_rg", return_value=False):
            rc = cmd_search(["query"])
        assert rc == 1

    def test_matches_returns_0(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\nconfluence:\n  page_id: '1'\n---\n\n# Laptop provisioning\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 5, "# Laptop provisioning")
        rc, out, _ = self._run(["laptop"], [root], rg_lines=[rg_line], rg_returncode=0)
        assert rc == 0
        assert "Laptop" in out or "laptop" in out

    def test_json_flag_produces_json_records(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\nconfluence:\n  page_id: '2'\n---\n\n# Body\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        rg_line = _make_rg_json_line(str(f), 5, "# Body")
        rc, out, _ = self._run(["body", "--json"], [root], rg_lines=[rg_line], rg_returncode=0)
        assert rc == 0
        record = json.loads(out.strip())
        assert "mirror" in record
        assert "line" in record

    def test_per_file_limit_forwarded(self) -> None:
        """--per-file-limit shows up in the rg --max-count argument."""
        root = _confluence_root(CONFLUENCE_MIRROR)
        captured_cmd: list[list[str]] = []

        original = _build_rg_cmd

        def spy_build(
            query: str, roots: list[MirrorRoot], *, type_filter: str, per_file_limit: int
        ) -> list[str]:
            cmd = original(query, roots, type_filter=type_filter, per_file_limit=per_file_limit)
            captured_cmd.append(cmd)
            return cmd

        with (
            patch("mdd.commands.search.resolve_roots", return_value=[root]),
            patch("mdd.commands.search._build_rg_cmd", spy_build),
            patch("mdd.commands.search._open_rg", _empty_fake_popen),
            patch("mdd.commands.search._check_rg", return_value=True),
        ):
            cmd_search(["query", "--per-file-limit", "42"])

        assert captured_cmd, "rg cmd was not built"
        cmd = captured_cmd[0]
        assert cmd[cmd.index("--max-count") + 1] == "42"

    def test_total_limit_caps_results(self, tmp_path: Path) -> None:
        """--limit caps total matches across all files in streaming mode."""
        f = tmp_path / "page.md"
        f.write_text("a\nb\nc\nd\ne\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        lines = [_make_rg_json_line(str(f), n, f"line {n}") for n in range(1, 6)]
        rc, out, _ = self._run(["x", "--limit", "2"], [root], rg_lines=lines, rg_returncode=0)
        assert rc == 0
        match_lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("L")]
        assert len(match_lines) == 2

    def test_sort_mode_buffers_and_groups(self, tmp_path: Path) -> None:
        """--sort uses the buffered/grouped formatter rather than streaming."""
        f1 = tmp_path / "a.md"
        f1.write_text("a\nb\n")
        f2 = tmp_path / "b.md"
        f2.write_text("a\nb\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        lines = [
            _make_rg_json_line(str(f1), 1, "match in a"),
            _make_rg_json_line(str(f2), 1, "match in b"),
            _make_rg_json_line(str(f1), 2, "match in a again"),
        ]
        rc, out, _ = self._run(["match", "--sort"], [root], rg_lines=lines, rg_returncode=0)
        assert rc == 0
        # In sort mode, both lines from a.md are grouped together
        idx_a1 = out.index("match in a\n")
        idx_a2 = out.index("match in a again")
        idx_b = out.index("match in b")
        assert idx_a1 < idx_a2 < idx_b or idx_b < idx_a1 < idx_a2

    def test_color_always_emits_ansi(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: P\n---\n\n# foo bar\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        # rg byte offsets for "foo" inside "# foo bar"
        line = _make_rg_json_line(str(f), 5, "# foo bar")
        # _make_rg_json_line doesn't support submatches; embed manually
        import json as _json

        decoded = _json.loads(line)
        decoded["data"]["submatches"] = [{"match": {"text": "foo"}, "start": 2, "end": 5}]
        line = _json.dumps(decoded)
        rc, out, _ = self._run(
            ["foo", "--color", "always"], [root], rg_lines=[line], rg_returncode=0
        )
        assert rc == 0
        assert "\x1b[1;31mfoo\x1b[0m" in out

    def test_color_never_no_ansi(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("---\ntitle: P\n---\n\n# foo\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        line = _make_rg_json_line(str(f), 5, "# foo")
        rc, out, _ = self._run(
            ["foo", "--color", "never"], [root], rg_lines=[line], rg_returncode=0
        )
        assert rc == 0
        assert "\x1b[" not in out

    def test_trace_prints_rg_argv(self, tmp_path: Path) -> None:
        f = tmp_path / "page.md"
        f.write_text("# foo\n")
        root = MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )
        line = _make_rg_json_line(str(f), 1, "# foo")
        rc, _, err = self._run(["foo", "--trace"], [root], rg_lines=[line], rg_returncode=0)
        assert rc == 0
        assert "[mdd search]" in err
        assert "rg" in err
        assert "foo" in err

    def test_exclude_blacklisted_flag_calls_filter(self) -> None:
        """--exclude-blacklisted causes filter_blacklisted to be called."""
        root = _confluence_root(CONFLUENCE_MIRROR)
        filter_called: list[bool] = []

        def mock_filter(
            roots: list[MirrorRoot],
            *,
            blacklist_file: Path | None = None,
        ) -> list[MirrorRoot]:
            filter_called.append(True)
            return roots

        with (
            patch("mdd.commands.search.resolve_roots", return_value=[root]),
            patch("mdd.commands.search.filter_blacklisted", mock_filter),
            patch("mdd.commands.search._open_rg", _empty_fake_popen),
            patch("mdd.commands.search._check_rg", return_value=True),
        ):
            cmd_search(["query", "--exclude-blacklisted"])

        assert filter_called == [True]

    def test_type_all_forwarded(self) -> None:
        """--type all is forwarded as a union of the md and qmd rg types."""
        root = _confluence_root(CONFLUENCE_MIRROR)
        captured_cmds: list[list[str]] = []

        original = _build_rg_cmd

        def spy_build(
            query: str, roots: list[MirrorRoot], *, type_filter: str, per_file_limit: int
        ) -> list[str]:
            cmd = original(query, roots, type_filter=type_filter, per_file_limit=per_file_limit)
            captured_cmds.append(cmd)
            return cmd

        with (
            patch("mdd.commands.search.resolve_roots", return_value=[root]),
            patch("mdd.commands.search._build_rg_cmd", spy_build),
            patch("mdd.commands.search._open_rg", _empty_fake_popen),
            patch("mdd.commands.search._check_rg", return_value=True),
        ):
            cmd_search(["query", "--type", "all"])

        assert captured_cmds, "rg cmd was not built"
        cmd = captured_cmds[0]
        assert "md" in cmd
        assert "qmd:*.qmd" in cmd
        assert "qmd" in cmd


# ---------------------------------------------------------------------------
# End-to-end: real ripgrep against fixture trees
# ---------------------------------------------------------------------------


class TestCmdSearchEndToEnd:
    """End-to-end tests that invoke rg for real against fixture trees."""

    def test_search_finds_laptop_across_both_mirrors(self) -> None:
        confluence_root = MirrorRoot(
            path=CONFLUENCE_MIRROR,
            mirror_name="confluence/ENGINEERING",
            source_type="confluence",
            identifier="ENGINEERING",
        )
        sharepoint_root = MirrorRoot(
            path=SHAREPOINT_MIRROR,
            mirror_name="sharepoint/Engineering",
            source_type="sharepoint",
            identifier="Engineering",
        )

        with patch(
            "mdd.commands.search.resolve_roots",
            return_value=[confluence_root, sharepoint_root],
        ):
            rc = cmd_search(["laptop"])

        assert rc == 0

    def test_search_no_results_returns_1(self) -> None:
        confluence_root = MirrorRoot(
            path=CONFLUENCE_MIRROR,
            mirror_name="confluence/ENGINEERING",
            source_type="confluence",
            identifier="ENGINEERING",
        )

        with patch("mdd.commands.search.resolve_roots", return_value=[confluence_root]):
            rc = cmd_search(["xyzzy_no_such_content_12345"])

        assert rc == 1

    def test_search_excludes_frontmatter_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "ENGINEERING" appears in frontmatter of fixture files
        confluence_root = MirrorRoot(
            path=CONFLUENCE_MIRROR,
            mirror_name="confluence/ENGINEERING",
            source_type="confluence",
            identifier="ENGINEERING",
        )

        with patch("mdd.commands.search.resolve_roots", return_value=[confluence_root]):
            cmd_search(["ENGINEERING"])

        captured = capsys.readouterr()
        for line in captured.out.splitlines():
            if line.strip().startswith("L"):
                assert "space: ENGINEERING" not in line

    def _type_filter_root(self, tmp_path: Path) -> MirrorRoot:
        """A root holding one .md and one .qmd file that share a search term."""
        (tmp_path / "page.md").write_text("# Quarto notes\n")
        (tmp_path / "notebook.qmd").write_text("# Quarto notes\n")
        return MirrorRoot(
            path=tmp_path,
            mirror_name="confluence/TEST",
            source_type="confluence",
            identifier="TEST",
        )

    def test_type_all_finds_both_md_and_qmd(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--type all must be the union of md and qmd, not narrowed to one of them."""
        root = self._type_filter_root(tmp_path)

        with patch("mdd.commands.search.resolve_roots", return_value=[root]):
            rc = cmd_search(["Quarto", "--type", "all"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "page.md" in out
        assert "notebook.qmd" in out

    def test_type_md_finds_only_md(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._type_filter_root(tmp_path)

        with patch("mdd.commands.search.resolve_roots", return_value=[root]):
            rc = cmd_search(["Quarto", "--type", "md"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "page.md" in out
        assert "notebook.qmd" not in out

    def test_type_qmd_finds_only_qmd(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._type_filter_root(tmp_path)

        with patch("mdd.commands.search.resolve_roots", return_value=[root]):
            rc = cmd_search(["Quarto", "--type", "qmd"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "notebook.qmd" in out
        assert "page.md" not in out
