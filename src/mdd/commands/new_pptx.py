"""Create a new Quarto PowerPoint presentation from template."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

from mdd.utils.scaffolding import create_quarto_project

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _NewPptxArgs(argparse.Namespace):
    directory: str


def _run_new_pptx(ns: argparse.Namespace) -> int:
    args = cast("_NewPptxArgs", ns)
    return create_quarto_project(
        dir_name=args.directory,
        qmd_template_name="simple-presentation.qmd",
        output_type="PowerPoint (.pptx)",
        templates={"simple-presentation.pptx": "simple-presentation.pptx"},
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "new-pptx",
        help="Create a new Quarto PowerPoint presentation from template",
        description="Create a new Quarto project that renders a PowerPoint (.pptx) deck.",
    )
    _ = p.add_argument("directory", help="Project directory to create")
    p.set_defaults(func=_run_new_pptx)
