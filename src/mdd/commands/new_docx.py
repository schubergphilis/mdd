"""Create a new Quarto Word document from template."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

from mdd.utils.scaffolding import create_quarto_project

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _NewDocxArgs(argparse.Namespace):
    directory: str


def _run_new_docx(ns: argparse.Namespace) -> int:
    args = cast("_NewDocxArgs", ns)
    return create_quarto_project(
        dir_name=args.directory,
        qmd_template_name="simple-document.qmd",
        output_type="Word (.docx)",
        templates={"simple-document.docx": "simple-document.docx"},
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "new-docx",
        help="Create a new Quarto Word document from template",
        description="Create a new Quarto project that renders a Word (.docx) document.",
    )
    _ = p.add_argument("directory", help="Project directory to create")
    p.set_defaults(func=_run_new_docx)
