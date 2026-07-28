"""PDF export command for Word documents."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mdd.commands.pdf_pptx import resolve_directory
from mdd.utils.pdf_export import (
    export_to_pdf_via_applescript,
    find_stale_files,
    process_files,
)

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers


class _PdfDocxArgs(argparse.Namespace):
    directory: Path | None


def export_docx_to_pdf(docx_path: Path) -> bool:
    """Export a DOCX file to PDF using Word via AppleScript."""
    pdf_path = Path(str(docx_path) + ".pdf")
    applescript = f"""
tell application "Microsoft Word"
    open POSIX file "{docx_path.resolve()}"
    set theDoc to active document
    save as theDoc file name POSIX file "{pdf_path.resolve()}" file format format PDF
    close theDoc saving no
end tell
"""
    return export_to_pdf_via_applescript(docx_path, applescript, "Word")


def run_docx_pipeline(directory: Path) -> int:
    """Export every stale .docx in *directory* to PDF; return exit code."""
    stale = find_stale_files(directory, "docx")
    return process_files(stale, export_docx_to_pdf, "DOCX")


def _run_pdf_docx(ns: argparse.Namespace) -> int:
    args = cast("_PdfDocxArgs", ns)
    directory = resolve_directory(args.directory)
    if directory is None:
        return 1
    return run_docx_pipeline(directory)


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "pdf-docx",
        help="Export Word documents to PDF (when DOCX is newer)",
        description="Export every .docx in DIRECTORY to PDF via Word (macOS).",
    )
    _ = p.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=None,
        help="Directory to scan (defaults to current working directory)",
    )
    p.set_defaults(func=_run_pdf_docx)
