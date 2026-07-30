"""Tests for the mdd.cli argparse dispatcher."""

import argparse
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from mdd.cli import CommonParents, SubParsers, build_dispatcher, main, run


def _fake_command_module(
    calls: list[argparse.Namespace],
    *,
    name: str = "frobnicate",
    exit_code: int = 0,
) -> ModuleType:
    """A stand-in for a downstream distribution's command module (spec S44).

    Matches the contract the real modules under ``src/mdd/commands/`` follow:
    a module-level ``register(subparsers, parents)`` that adds one subparser,
    opts into the shared parent parsers, and wires its handler through
    ``set_defaults(func=...)``. Self-contained on purpose — the seam must be
    testable without any wrapper distribution being installed.
    """

    def _run_fake(ns: argparse.Namespace) -> int:
        calls.append(ns)
        return exit_code

    def register(subparsers: SubParsers, parents: CommonParents) -> None:
        p = subparsers.add_parser(
            name,
            parents=[parents.config_required, parents.dry_run],
            help="a wrapper-only command",
        )
        _ = p.add_argument("target")
        _ = p.add_argument("--times", type=int, default=1)
        p.set_defaults(func=_run_fake)

    return cast("ModuleType", SimpleNamespace(register=register))


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
        # `.devN+g…` suffix derived from git.
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

    def test_default_backend_selects_registered_backend(self) -> None:
        from mdd.cli import build_dispatcher
        from mdd.mirror.git import GenericGitBackend
        from mdd.mirror.registry import default_backend

        _ = build_dispatcher(default_backend="git")
        assert isinstance(default_backend(), GenericGitBackend)

    def test_extra_commands_are_registered(self) -> None:
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


class TestExtraCommandsDispatch:
    """An injected command must be reachable end-to-end through `run()` (spec S44).

    Registration alone is not the contract downstream distributions rely on:
    the composed parser has to route ``mdd <extra-command> ...`` to the
    module's own handler, with the shared parent flags parsed in and the
    handler's return value becoming the process exit status.
    """

    def test_run_reaches_the_injected_handler_with_the_parsed_namespace(self) -> None:
        calls: list[argparse.Namespace] = []
        parser = build_dispatcher(extra_commands=(_fake_command_module(calls),))

        exit_code = run(
            parser, ["frobnicate", "--config", "site.toml", "--dry-run", "widget", "--times", "3"]
        )

        assert exit_code == 0
        assert len(calls) == 1, "the injected command's func was not invoked exactly once"
        ns = calls[0]
        # Assert the command-relevant slice of the namespace, not the whole object:
        # the root parser also stashes logging flags and `_root_parser` on it.
        interesting = {"command", "target", "times", "config", "dry_run"}
        assert {k: v for k, v in vars(ns).items() if k in interesting} == {
            "command": "frobnicate",
            "target": "widget",
            "times": 3,
            # `--config` comes from the `config_required` common parent, so
            # inherited parents reach an injected command's namespace too —
            # including the parent's `type=Path` coercion.
            "config": Path("site.toml"),
            # `--dry-run` comes from the `dry_run` common parent.
            "dry_run": True,
        }

    def test_common_parent_defaults_apply_when_the_flags_are_omitted(self) -> None:
        calls: list[argparse.Namespace] = []
        parser = build_dispatcher(extra_commands=(_fake_command_module(calls),))

        assert run(parser, ["frobnicate", "widget"]) == 0
        ns = calls[0]
        assert ns.config is None
        assert ns.dry_run is False
        assert ns.times == 1

    def test_handler_return_value_becomes_the_exit_status(self) -> None:
        calls: list[argparse.Namespace] = []
        parser = build_dispatcher(extra_commands=(_fake_command_module(calls, exit_code=3),))

        assert run(parser, ["frobnicate", "widget"]) == 3
        assert len(calls) == 1

    def test_every_injected_module_is_dispatchable(self) -> None:
        """``extra_commands`` is a sequence; each entry gets its own route."""
        first_calls: list[argparse.Namespace] = []
        second_calls: list[argparse.Namespace] = []
        parser = build_dispatcher(
            extra_commands=(
                _fake_command_module(first_calls, name="frobnicate"),
                _fake_command_module(second_calls, name="quux", exit_code=4),
            )
        )

        assert run(parser, ["quux", "widget"]) == 4
        assert first_calls == []
        assert len(second_calls) == 1
        assert second_calls[0].command == "quux"

    def test_core_commands_still_dispatch_alongside_the_extras(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls: list[argparse.Namespace] = []
        parser = build_dispatcher(extra_commands=(_fake_command_module(calls),))

        assert run(parser, ["echo", "hello"]) == 0
        assert "hello" in capsys.readouterr().out
        assert calls == []


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
