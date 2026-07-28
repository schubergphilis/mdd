"""Tests for the echo subcommand."""

from typing import TYPE_CHECKING

from mdd.cli import main

if TYPE_CHECKING:
    import pytest


class TestEcho:
    def test_prints_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["echo", "foo", "bar"])
        assert result == 0
        assert "foo bar" in capsys.readouterr().out

    def test_empty_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["echo"])
        assert result == 0
        assert capsys.readouterr().out.strip() == ""

    def test_single_arg(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["echo", "hello"])
        assert result == 0
        assert "hello" in capsys.readouterr().out
