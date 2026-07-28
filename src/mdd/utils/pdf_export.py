"""Utilities for exporting Office documents to PDF via AppleScript."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)


def find_stale_files(directory: Path, extension: str) -> list[Path]:
    """Find files that need PDF export.

    A file needs export if no corresponding PDF exists or the source is newer.
    Excludes symlinks and files in the 'templates' directory.
    """
    stale_files: list[Path] = []

    for source_path in directory.glob(f"*.{extension}"):
        if source_path.is_symlink():
            continue
        if source_path.parent.name == "templates":
            continue

        pdf_path = Path(str(source_path) + ".pdf")

        if not pdf_path.exists() or source_path.stat().st_mtime > pdf_path.stat().st_mtime:
            stale_files.append(source_path)

    return stale_files


def export_to_pdf_via_applescript(source_path: Path, applescript: str, app_name: str) -> bool:
    """Export a file to PDF using an Office app via AppleScript."""
    try:
        pdf_path = Path(str(source_path) + ".pdf")

        _ = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True,
        )

        if not pdf_path.exists():
            log.error("%s did not create PDF for %s", app_name, source_path.name)
            return False

        return True

    except subprocess.CalledProcessError as e:
        log.exception("AppleScript failed for %s", source_path.name)
        if e.stderr:
            log.error("%s", e.stderr.strip())
        return False
    except OSError:
        log.exception("File operation failed for %s", source_path.name)
        return False


def validate_directory(args: list[str]) -> Path | None:
    """Validate and return the target directory from command arguments."""
    if args:
        directory = Path(args[0])
        if not directory.exists():
            log.error("Directory '%s' does not exist", directory)
            return None
        if not directory.is_dir():
            log.error("'%s' is not a directory", directory)
            return None
        return directory
    return Path.cwd()


def process_files(
    stale_files: list[Path], export_func: Callable[[Path], bool], file_type: str
) -> int:
    """Process a list of files for PDF export."""
    if not stale_files:
        log.info("No %s files need exporting", file_type)
        return 0

    log.info("Found %d file(s) to export:", len(stale_files))
    for file_path in stale_files:
        log.info("  - %s", file_path.name)

    exported_count = 0
    skipped_count = 0

    for file_path in stale_files:
        log.info("Exporting: %s -> %s.pdf", file_path.name, file_path.name)
        if export_func(file_path):
            exported_count += 1
        else:
            skipped_count += 1

    log.info("Exported %d file(s), skipped %d file(s)", exported_count, skipped_count)
    return 1 if skipped_count > 0 else 0
