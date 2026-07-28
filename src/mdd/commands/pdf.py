"""Unified PDF export command for both PowerPoint and Word documents."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mdd.commands.pdf_docx import run_docx_pipeline
from mdd.commands.pdf_pptx import resolve_directory, run_pptx_pipeline
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

log = get_logger(__name__)


class _PdfArgs(argparse.Namespace):
    directory: Path | None


def _run_pdf(ns: argparse.Namespace) -> int:
    args = cast("_PdfArgs", ns)
    directory = resolve_directory(args.directory)
    if directory is None:
        return 1

    log.info("=== Exporting PowerPoint files ===")
    pptx_result = run_pptx_pipeline(directory)

    log.info("=== Exporting Word documents ===")
    docx_result = run_docx_pipeline(directory)

    if pptx_result == 0 and docx_result == 0:
        log.info("All exports completed successfully")
        return 0
    if pptx_result != 0:
        log.error("PPTX export failed (exit code: %d)", pptx_result)
    if docx_result != 0:
        log.error("DOCX export failed (exit code: %d)", docx_result)
    log.error("Some exports failed")
    return 1


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "pdf",
        help="Export all Office documents (PPTX and DOCX) to PDF",
        description="Run both `pdf-pptx` and `pdf-docx` over DIRECTORY in sequence.",
    )
    _ = p.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=None,
        help="Directory to scan (defaults to current working directory)",
    )
    p.set_defaults(func=_run_pdf)
