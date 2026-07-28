"""CLI entry point for mdd."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mdd import __version__
from mdd.commands import (
    ai,
    confluence,
    convert,
    echo,
    new,
    new_docx,
    new_pptx,
    pdf,
    pdf_docx,
    pdf_pptx,
    search,
    sharepoint,
    skills,
)
from mdd.commands import (
    help as help_cmd,
)
from mdd.mirror.registry import set_default_backend
from mdd.utils.logging import configure as configure_logging

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType


@dataclass(frozen=True)
class CommonParents:
    """Shared parent parsers passed to each command module's register()."""

    config_required: argparse.ArgumentParser
    dry_run: argparse.ArgumentParser


type SubParsers = argparse._SubParsersAction[argparse.ArgumentParser]  # pyright: ignore[reportPrivateUsage]


# Modules that expose register(subparsers, parents). These are the
# provider-neutral commands the open-source core ships (spec S44); the
# site-specific ones (`gitlab`, `lucid`) are injected by the wrapper's
# entry point through ``extra_commands`` rather than listed here, so the
# OSS cut needs no edit to this module.
_REGISTERED_MODULES = (
    echo,
    help_cmd,
    convert,
    new,
    new_pptx,
    new_docx,
    pdf,
    pdf_pptx,
    pdf_docx,
    search,
    skills,
    ai,
    sharepoint,
    confluence,
)


def _build_parents() -> CommonParents:
    config_required = argparse.ArgumentParser(add_help=False)
    _ = config_required.add_argument("--config", type=Path, default=None, metavar="FILE")
    dry_run = argparse.ArgumentParser(add_help=False)
    _ = dry_run.add_argument("--dry-run", action="store_true")
    return CommonParents(config_required=config_required, dry_run=dry_run)


def build_dispatcher(
    *,
    default_backend: str = "git",
    extra_commands: Sequence[ModuleType] = (),
    version: str | None = None,
) -> argparse.ArgumentParser:
    """Build the top-level argparse tree for the mdd CLI.

    This is the seam a private wrapper composes against (spec S44 / plan
    P03 MR A5): the open-source core defaults to the generic ``git``
    backend and the built-in command set, while a wrapper picks its own
    default backend and appends its own subcommands without editing the
    core.

    Args:
        default_backend: name of the registered
            :class:`~mdd.mirror.protocol.MirrorBackend` the sync engines
            default to. Recorded via
            :func:`mdd.mirror.registry.set_default_backend`.
        extra_commands: additional command modules exposing
            ``register(subparsers, parents)``, appended after the
            built-ins (S44 Open Question 2: a module list, matching the
            existing ``register(subparsers, parents)`` convention).
        version: what ``--version`` prints. Defaults to this package's
            version; a wrapper passes its own, since the version a user
            cares about is the one for the distribution they installed,
            not the core it happens to sit on.
    """
    set_default_backend(default_backend)

    root = argparse.ArgumentParser(
        prog="mdd",
        description="Markdown and Quarto document tooling.",
    )
    _ = root.add_argument(
        "--version",
        action="version",
        version=version if version is not None else f"mdd {__version__}",
    )
    _ = root.add_argument("-v", "--verbose", action="count", default=0)
    _ = root.add_argument("--trace", action="store_true")
    _ = root.add_argument("--trace-bodies", action="store_true")
    _ = root.add_argument("--log-level", default=None, metavar="LEVEL")

    parents = _build_parents()

    subparsers = root.add_subparsers(dest="command", metavar="<command>")
    root.set_defaults(_root_parser=root)
    for module in (*_REGISTERED_MODULES, *extra_commands):
        module.register(subparsers, parents)

    return root


class _RootArgs(argparse.Namespace):
    """Root-level argparse flags consumed by ``_resolve_log_level`` / ``_apply_logging``."""

    verbose: int
    trace: bool
    trace_bodies: bool
    log_level: str | None


def _resolve_log_level(ns: argparse.Namespace) -> str | None:
    """Map root logging flags on the parsed namespace to a level name."""
    args = cast("_RootArgs", ns)
    if args.log_level:
        return args.log_level
    if args.trace or args.trace_bodies or args.verbose >= 3:
        return "TRACE"
    if args.verbose == 2:
        return "DEBUG"
    if args.verbose == 1:
        return "INFO"
    return None


def _apply_logging(ns: argparse.Namespace) -> None:
    args = cast("_RootArgs", ns)
    level = _resolve_log_level(ns)
    configure_logging(level=level)
    if args.trace_bodies:
        os.environ["MDD_TRACE_BODIES"] = "1"


def run(parser: argparse.ArgumentParser, argv: list[str] | None = None) -> int:
    """Parse *argv* with *parser*, apply the logging flags, and dispatch.

    The second half of the wrapper seam (spec S44). ``build_dispatcher``
    composes the parser; this runs it. A wrapper needs both, and without
    this it would have to reimplement the logging wiring or reach for a
    private helper.
    """
    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])
    _apply_logging(ns)
    func: Callable[[argparse.Namespace], int] | None = getattr(ns, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(ns)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for mdd CLI."""
    # The open-source core defaults to the generic `git` backend and the
    # built-in command set. A wrapper composes on top by calling
    # `build_dispatcher` itself with its own default_backend and
    # extra_commands (spec S44) rather than by editing this function.
    return run(build_dispatcher(), argv)


if __name__ == "__main__":
    sys.exit(main())
