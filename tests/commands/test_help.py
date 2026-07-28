"""Tests for the help subcommand (alias for --help)."""

import importlib.util
from typing import TYPE_CHECKING

from mdd.cli import main

if TYPE_CHECKING:
    import pytest


# The provider-neutral command set every distribution ships.
_CORE_COMMANDS = (
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

# Site-specific groups injected by this distribution's entry point via
# `extra_commands` (spec S44). A distribution that does not ship them is
# still valid, so they are asserted only when their module is importable.
_SITE_COMMANDS = tuple(
    name
    for name, module in (("gitlab", "mdd.commands.gitlab"), ("lucid", "mdd.commands.lucid"))
    if importlib.util.find_spec(module) is not None
)

_EXPECTED_COMMANDS = _CORE_COMMANDS + _SITE_COMMANDS


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
