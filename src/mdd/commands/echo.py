"""Echo command — prints arguments back. Useful as a smoke test."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _EchoArgs(argparse.Namespace):
    words: list[str]


def _run_echo(ns: argparse.Namespace) -> int:
    args = cast("_EchoArgs", ns)
    print(" ".join(args.words))  # noqa: T201  # program output
    return 0


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "echo",
        help="Echo arguments (smoke test)",
        description="Print the given words back to stdout. Smoke test for the CLI.",
    )
    _ = p.add_argument("words", nargs="*", help="Words to echo back")
    p.set_defaults(func=_run_echo)
