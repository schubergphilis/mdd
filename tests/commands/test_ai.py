"""Tests for mdd.commands.ai — CLI dispatcher (spec S35 entrypoint)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.ai.models import AiError
from mdd.cli import main as cli_main

if TYPE_CHECKING:
    from pathlib import Path


def cmd_ai(args: list[str]) -> int:
    """Test helper: invoke `mdd ai` via the argparse entry point."""
    return cli_main(["ai", *args])


class TestCmdAiNoArgs:
    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai([])
        assert exc_info.value.code == 2

    def test_unknown_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["bogus"])
        assert exc_info.value.code == 2

    def test_help_lists_subcommands(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for verb in ("rewrite", "index", "review"):
            assert verb in out


class TestRewrite:
    def test_no_files_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["rewrite"])
        assert exc_info.value.code == 2

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["rewrite", "--bogus", "foo.md"])
        assert exc_info.value.code == 2

    def test_missing_style_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        md = tmp_path / "page.md"
        _ = md.write_text("# Hi\n", encoding="utf-8")
        missing_style = tmp_path / "no-style.md"
        result = cmd_ai(["rewrite", "--style", str(missing_style), str(md)])
        assert result == 1
        assert "style file not found" in capsys.readouterr().err

    def test_missing_file_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        missing = tmp_path / "no-such.md"
        result = cmd_ai(["rewrite", str(missing)])
        assert result == 1
        assert "file not found" in capsys.readouterr().err

    def test_ai_config_error_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        md = tmp_path / "page.md"
        _ = md.write_text("# Hi\n", encoding="utf-8")
        with patch("mdd.ai.client.Client", side_effect=AiError("no config")):
            result = cmd_ai(["rewrite", str(md)])
        assert result == 1
        assert "AI config" in capsys.readouterr().err


class TestIndex:
    def test_no_directory_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["index"])
        assert exc_info.value.code == 2

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["index", ".", "--bogus"])
        assert exc_info.value.code == 2

    def test_invalid_depth_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["index", ".", "--depth", "bogus"])
        assert exc_info.value.code == 2

    def test_not_a_directory_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        missing = tmp_path / "no-such-dir"
        result = cmd_ai(["index", str(missing)])
        assert result == 1
        assert "not a directory" in capsys.readouterr().err

    def test_ai_config_error_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        with patch("mdd.ai.client.Client", side_effect=AiError("no config")):
            result = cmd_ai(["index", str(tmp_path)])
        assert result == 1
        assert "AI config" in capsys.readouterr().err


class TestReview:
    def test_no_directory_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["review"])
        assert exc_info.value.code == 2

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["review", ".", "--bogus"])
        assert exc_info.value.code == 2

    def test_no_mode_flag_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        result = cmd_ai(["review", str(tmp_path)])
        assert result == 1
        assert "at least one mode flag" in capsys.readouterr().err

    def test_not_a_directory_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        missing = tmp_path / "no-such-dir"
        result = cmd_ai(["review", str(missing), "--duplicates"])
        assert result == 1
        assert "not a directory" in capsys.readouterr().err

    def test_top_k_non_integer_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cmd_ai(["review", str(tmp_path), "--duplicates", "--top-k", "not-a-number"])
        assert exc_info.value.code == 2

    def test_ai_config_error_returns_1(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        with patch("mdd.ai.client.Client", side_effect=AiError("no config")):
            result = cmd_ai(["review", str(tmp_path), "--duplicates"])
        assert result == 1
        assert "AI config" in capsys.readouterr().err
