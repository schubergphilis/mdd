"""Help command — thin alias for ``mdd --help``."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _HelpArgs(argparse.Namespace):
    # ``_root_parser`` is injected via ``root.set_defaults(_root_parser=root)`` in
    # ``mdd.cli.build_dispatcher`` and is the only namespace attribute this handler reads.
    _root_parser: argparse.ArgumentParser  # pyright: ignore[reportPrivateUsage]


def _run_help(ns: argparse.Namespace) -> int:
    args = cast("_HelpArgs", ns)
    args._root_parser.print_help()  # pyright: ignore[reportPrivateUsage]
    return 0


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "help",
        help="Show top-level usage (alias for --help)",
        description=(
            "Print the top-level mdd usage. For per-subcommand help, run `mdd <subcommand> --help`."
        ),
    )
    p.set_defaults(func=_run_help)
