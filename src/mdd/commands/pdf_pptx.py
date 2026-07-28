"""PDF export command for PowerPoint files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mdd.utils.logging import get_logger
from mdd.utils.pdf_export import (
    export_to_pdf_via_applescript,
    find_stale_files,
    process_files,
)

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

log = get_logger(__name__)


class _PdfPptxArgs(argparse.Namespace):
    directory: Path | None


def export_pptx_to_pdf(pptx_path: Path) -> bool:
    """Export a PPTX file to PDF using PowerPoint via AppleScript."""
    pdf_path = Path(str(pptx_path) + ".pdf")
    applescript = f"""
tell application "Microsoft PowerPoint"
    open POSIX file "{pptx_path.resolve()}"
    set theDoc to active presentation
    save theDoc in POSIX file "{pdf_path.resolve()}" as save as PDF
    close theDoc
end tell
"""
    return export_to_pdf_via_applescript(pptx_path, applescript, "PowerPoint")


def resolve_directory(directory: Path | None) -> Path | None:
    """Validate the optional directory argument; default to cwd."""
    if directory is None:
        return Path.cwd()
    if not directory.exists():
        log.error("Directory '%s' does not exist", directory)
        return None
    if not directory.is_dir():
        log.error("'%s' is not a directory", directory)
        return None
    return directory


def run_pptx_pipeline(directory: Path) -> int:
    """Export every stale .pptx in *directory* to PDF; return exit code."""
    stale = find_stale_files(directory, "pptx")
    return process_files(stale, export_pptx_to_pdf, "PPTX")


def _run_pdf_pptx(ns: argparse.Namespace) -> int:
    args = cast("_PdfPptxArgs", ns)
    directory = resolve_directory(args.directory)
    if directory is None:
        return 1
    return run_pptx_pipeline(directory)


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "pdf-pptx",
        help="Export PowerPoint files to PDF (when PPTX is newer)",
        description="Export every .pptx in DIRECTORY to PDF via PowerPoint (macOS).",
    )
    _ = p.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=None,
        help="Directory to scan (defaults to current working directory)",
    )
    p.set_defaults(func=_run_pdf_pptx)
