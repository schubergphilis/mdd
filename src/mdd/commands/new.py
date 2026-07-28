"""Unified new command — creates both PowerPoint and Word outputs."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

from mdd.utils.scaffolding import create_quarto_project

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _NewArgs(argparse.Namespace):
    directory: str


def _run_new(ns: argparse.Namespace) -> int:
    args = cast("_NewArgs", ns)
    return create_quarto_project(
        dir_name=args.directory,
        qmd_template_name="combined-document.qmd",
        output_type="Both PowerPoint (.pptx) and Word (.docx)",
        templates={
            "simple-presentation.pptx": "simple-presentation.pptx",
            "simple-document.docx": "simple-document.docx",
        },
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "new",
        help="Create both a PowerPoint and Word document from templates",
        description="Create a new Quarto project that renders both .pptx and .docx outputs.",
    )
    _ = p.add_argument("directory", help="Project directory to create")
    p.set_defaults(func=_run_new)
