"""Tests for the help subcommand (alias for --help)."""

from typing import TYPE_CHECKING

from mdd.cli import main

if TYPE_CHECKING:
    import pytest


# The provider-neutral command set this distribution ships. Site-specific
# groups a wrapper injects via `extra_commands` are not asserted here; that
# seam is covered end-to-end by `TestExtraCommandsDispatch` in
# tests/test_cli.py with a self-contained fake command module.
_EXPECTED_COMMANDS = (
    "echo",
    "help",
    "convert",
    "new",
    "new-pptx",
    "new-docx",
    "pdf",
    "pdf-pptx",
    "pdf-docx",
    "ai",
    "confluence",
    "search",
    "sharepoint",
    "skills",
)


class TestHelp:
    def test_returns_zero(self) -> None:
        assert main(["help"]) == 0

    def test_shows_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        _ = main(["help"])
        out = capsys.readouterr().out
        for name in _EXPECTED_COMMANDS:
            assert name in out, f"command {name!r} missing from `mdd help` output"

    def test_no_args_shows_same_listing(self, capsys: pytest.CaptureFixture[str]) -> None:
        _ = main([])
        out = capsys.readouterr().out
        for name in _EXPECTED_COMMANDS:
            assert name in out
