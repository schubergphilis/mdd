"""Create a new Quarto PowerPoint presentation from template."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, cast

from mdd.utils.scaffolding import create_quarto_project

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

# Reference template per heading scale. The default runs 28 / 24 / 20 / 18 pt;
# `--compact` runs 18 / 16 / 14 / 12 pt for slides that carry a table plus
# bullets. Both are bundled under src/mdd/templates/.
DEFAULT_TEMPLATE = "simple-presentation.pptx"
COMPACT_TEMPLATE = "simple-presentation-compact.pptx"
DEFAULT_QMD = "simple-presentation.qmd"
COMPACT_QMD = "simple-presentation-compact.qmd"


class _NewPptxArgs(argparse.Namespace):
    directory: str
    compact: bool


def _run_new_pptx(ns: argparse.Namespace) -> int:
    args = cast("_NewPptxArgs", ns)
    qmd = COMPACT_QMD if args.compact else DEFAULT_QMD
    pptx = COMPACT_TEMPLATE if args.compact else DEFAULT_TEMPLATE
    return create_quarto_project(
        dir_name=args.directory,
        qmd_template_name=qmd,
        output_type="PowerPoint (.pptx)",
        templates={pptx: pptx},
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
    _ = p.add_argument(
        "--compact",
        action="store_true",
        help=(
            "use the compact reference template (18/16/14/12 pt body text) "
            "instead of the default (28/24/20/18 pt)"
        ),
    )
    p.set_defaults(func=_run_new_pptx)
