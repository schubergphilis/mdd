"""Tests for the mdd.cli argparse dispatcher."""

import pytest

from mdd.cli import main


class TestCLI:
    def test_no_args_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main([])
        assert result == 0
        out = capsys.readouterr().out
        assert "mdd" in out
        assert "convert" in out

    def test_help_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["help"])
        assert result == 0
        out = capsys.readouterr().out
        assert "mdd" in out
        assert "convert" in out

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        # argparse's version action prints and exits 0.
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["--version"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        # Assert the shape, not an exact string: editable/dev installs carry a
        # `.devN+g…` suffix derived from git (S43 §Risks).
        assert out.startswith("mdd ")
        assert out.split()[1][0].isdigit()

    def test_version_importable(self) -> None:
        import mdd

        assert isinstance(mdd.__version__, str)
        assert mdd.__version__
        assert mdd.__version__[0].isdigit()

    def test_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["--help"])
        assert exc_info.value.code == 0
        assert "convert" in capsys.readouterr().out

    def test_unknown_command_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["no-such-command"])
        assert exc_info.value.code == 2
        assert "no-such-command" in capsys.readouterr().err

    def test_echo_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = main(["echo", "hello", "world"])
        assert result == 0
        assert "hello world" in capsys.readouterr().out

    def test_convert_dispatches(self, capsys: pytest.CaptureFixture[str]) -> None:
        # No source argument → prints help and returns 1; argparse should not exit.
        result = main(["convert"])
        assert result == 1

    def test_gitlab_dispatches(self, capsys: pytest.CaptureFixture[str]) -> None:
        # argparse-routed: a missing subcommand exits with SystemExit(2).
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["gitlab"])
        assert exc_info.value.code == 2

    def test_confluence_dispatches(self, capsys: pytest.CaptureFixture[str]) -> None:
        # argparse-routed: a missing subcommand exits with SystemExit(2).
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["confluence"])
        assert exc_info.value.code == 2

    def test_sharepoint_dispatches(self, capsys: pytest.CaptureFixture[str]) -> None:
        # argparse-routed: a missing subcommand exits with SystemExit(2).
        with pytest.raises(SystemExit) as exc_info:
            _ = main(["sharepoint"])
        assert exc_info.value.code == 2


class TestBuildDispatcher:
    """build_dispatcher(default_backend, extra_commands) — spec S44 / plan P03 MR A5."""

    def test_core_help_lists_the_provider_neutral_commands(self) -> None:
        from mdd.cli import build_dispatcher

        parser = build_dispatcher()
        # The built-in command set is present regardless of default_backend.
        help_text = parser.format_help()
        for cmd in ("convert", "confluence", "sharepoint", "ai", "search"):
            assert cmd in help_text

    def test_core_help_excludes_the_site_specific_commands(self) -> None:
        """`gitlab` / `lucid` are wrapper extras, not core commands (spec S44).

        Keeping them out of ``_REGISTERED_MODULES`` is what lets the
        open-source cut drop ``mdd/gitlab/`` and ``mdd/lucid/`` without
        editing ``cli.py``.
        """
        from mdd.cli import build_dispatcher

        help_text = build_dispatcher().format_help()
        assert "gitlab" not in help_text
        assert "lucid" not in help_text

    def test_main_registers_the_site_specific_commands(self) -> None:
        """This distribution's entry point injects them via ``extra_commands``."""
        import contextlib
        import importlib.util
        import io

        import pytest

        from mdd.cli import main

        if importlib.util.find_spec("mdd.commands.gitlab") is None:
            pytest.skip("distribution ships no site-specific commands")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
            _ = main(["--help"])
        help_text = buf.getvalue()
        assert "gitlab" in help_text
        assert "lucid" in help_text

    def test_default_backend_selects_registered_backend(self) -> None:
        from mdd.cli import build_dispatcher
        from mdd.mirror.git import GenericGitBackend
        from mdd.mirror.registry import default_backend

        _ = build_dispatcher(default_backend="git")
        assert isinstance(default_backend(), GenericGitBackend)

    def test_extra_commands_are_registered(self) -> None:
        import argparse
        from types import ModuleType, SimpleNamespace
        from typing import cast

        from mdd.cli import CommonParents, SubParsers, build_dispatcher

        registered: list[str] = []

        def _run(_ns: argparse.Namespace) -> int:
            return 0

        def _register(subparsers: SubParsers, parents: CommonParents) -> None:
            sp = subparsers.add_parser("frobnicate", help="a wrapper-only command")
            sp.set_defaults(func=_run)
            registered.append("frobnicate")

        fake_module = cast("ModuleType", SimpleNamespace(register=_register))
        parser = build_dispatcher(extra_commands=(fake_module,))

        assert registered == ["frobnicate"]
        assert "frobnicate" in parser.format_help()
        assert isinstance(parser, argparse.ArgumentParser)


class TestRun:
    """`run(parser, argv)` — the second half of the wrapper seam (spec S44)."""

    def test_dispatches_to_the_selected_command(self) -> None:
        from mdd.cli import build_dispatcher, run

        assert run(build_dispatcher(), ["echo", "hello"]) == 0

    def test_no_command_prints_help_and_returns_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mdd.cli import build_dispatcher, run

        assert run(build_dispatcher(), []) == 0
        assert "usage: mdd" in capsys.readouterr().out

    def test_applies_the_root_logging_flags(self) -> None:
        """A wrapper gets -v/--trace handling without reimplementing it."""
        import logging

        from mdd.cli import build_dispatcher, run

        _ = run(build_dispatcher(), ["-vv", "echo", "hi"])
        assert logging.getLogger("mdd").level <= logging.DEBUG


class TestVersionOverride:
    """A wrapper's `--version` must report the wrapper, not the core (S44)."""

    def test_defaults_to_the_core_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        import contextlib

        from mdd import __version__
        from mdd.cli import build_dispatcher, run

        with contextlib.suppress(SystemExit):
            _ = run(build_dispatcher(), ["--version"])
        assert f"mdd {__version__}" in capsys.readouterr().out

    def test_wrapper_supplied_version_wins(self, capsys: pytest.CaptureFixture[str]) -> None:
        import contextlib

        from mdd.cli import build_dispatcher, run

        with contextlib.suppress(SystemExit):
            _ = run(build_dispatcher(version="mdd 9.9.9 (core mdd 1.2.3)"), ["--version"])
        assert "mdd 9.9.9 (core mdd 1.2.3)" in capsys.readouterr().out
