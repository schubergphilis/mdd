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
    update_fields: bool


# The source and PDF paths arrive as ``argv`` items so the script text never
# depends on a file name and file names can never change the program.
#
# Word's ``open`` hands back a copy it already holds in memory instead of
# re-reading the file, so any open copy of the source is closed unsaved first.
# Word may report ``full name`` as either a POSIX or an HFS path, so both are
# compared. Documents are walked from the last index down because closing one
# renumbers the rest.
_DOCX_SCRIPT_HEAD = """
on run argv
    set srcPath to item 1 of argv
    set srcFile to POSIX file srcPath
    set srcHfsPath to srcFile as text
    set pdfFile to POSIX file (item 2 of argv)
    tell application "Microsoft Word"
        repeat with i from (count of documents) to 1 by -1
            try
                set docName to full name of document i
                if docName is srcPath or docName is srcHfsPath then
                    close document i saving no
                end if
            end try
        end repeat
        open srcFile
        set theDoc to active document
"""

# Word does not evaluate fields on open, so a TOC is empty in the PDF unless
# it is updated here. Tables of contents are updated through their own
# collection because ``fields`` does not enumerate a TOC wrapped in a content
# control. The general field pass is best-effort: Word can fail to enumerate
# ``fields`` at all, and that must not abort the export.
_DOCX_SCRIPT_UPDATE_FIELDS = """
        repeat with theToc in (get tables of contents of theDoc)
            update theToc
        end repeat
        try
            repeat with theField in (get fields of theDoc)
                try
                    update field theField
                end try
            end repeat
        end try
"""

# ``close saving no`` leaves the .docx untouched on disk even after the field
# update dirtied it, so its mtime stays older than the new PDF.
_DOCX_SCRIPT_TAIL = """
        save as theDoc file name pdfFile file format format PDF
        close theDoc saving no
    end tell
end run
"""


def build_docx_applescript(*, update_fields: bool) -> str:
    """Return the AppleScript that exports ``argv`` item 1 to ``argv`` item 2 as PDF."""
    body = _DOCX_SCRIPT_UPDATE_FIELDS if update_fields else ""
    return _DOCX_SCRIPT_HEAD + body + _DOCX_SCRIPT_TAIL


def export_docx_to_pdf(docx_path: Path, *, update_fields: bool = True) -> bool:
    """Export a DOCX file to PDF using Word via AppleScript.

    With *update_fields*, tables of contents and other fields are updated
    before export so the PDF does not show stale or empty field results.
    """
    script = build_docx_applescript(update_fields=update_fields)
    return export_to_pdf_via_applescript(docx_path, script, "Word")


def run_docx_pipeline(directory: Path, *, update_fields: bool = True) -> int:
    """Export every stale .docx in *directory* to PDF; return exit code."""
    stale = find_stale_files(directory, "docx")

    def export(docx_path: Path) -> bool:
        return export_docx_to_pdf(docx_path, update_fields=update_fields)

    return process_files(stale, export, "DOCX")


def _run_pdf_docx(ns: argparse.Namespace) -> int:
    args = cast("_PdfDocxArgs", ns)
    directory = resolve_directory(args.directory)
    if directory is None:
        return 1
    return run_docx_pipeline(directory, update_fields=args.update_fields)


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
    _ = p.add_argument(
        "--no-update-fields",
        dest="update_fields",
        action="store_false",
        help=(
            "Export without first updating tables of contents and other fields "
            "(by default they are updated so the PDF does not show an empty TOC)"
        ),
    )
    p.set_defaults(func=_run_pdf_docx)
