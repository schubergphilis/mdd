"""Utilities for exporting Office documents to PDF via AppleScript."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.utils.logging import get_logger
from mdd.utils.safe_write import SymlinkRefusedError, refuse_symlink

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)


def has_control_characters(name: str) -> bool:
    """Return True if *name* contains any control character (including newline)."""
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in name)


def find_stale_files(directory: Path, extension: str) -> list[Path]:
    """Find files that need PDF export.

    A file needs export if no corresponding PDF exists or the source is newer.
    Excludes symlinks and files in the 'templates' directory. Files whose
    name contains control characters, or whose ``.pdf`` sibling is a
    symlink, are skipped with a warning.
    """
    stale_files: list[Path] = []

    for source_path in directory.glob(f"*.{extension}"):
        if source_path.is_symlink():
            continue
        if source_path.parent.name == "templates":
            continue
        if has_control_characters(source_path.name):
            log.warning("Skipping %r: file name contains control characters", source_path.name)
            continue

        pdf_path = Path(str(source_path) + ".pdf")
        if pdf_path.is_symlink():
            log.warning("Skipping %s: %s is a symlink", source_path.name, pdf_path.name)
            continue

        if not pdf_path.exists() or source_path.stat().st_mtime > pdf_path.stat().st_mtime:
            stale_files.append(source_path)

    return stale_files


def export_to_pdf_via_applescript(source_path: Path, applescript: str, app_name: str) -> bool:
    """Export a file to PDF using an Office app via AppleScript.

    *applescript* must define an ``on run argv`` handler; the resolved source
    path and the PDF path are passed as ``argv`` items 1 and 2. The ``--``
    separator stops osascript from reading the paths as options.

    Refuses to export when the ``.pdf`` destination is a symlink. Only the
    destination's directory is resolved, so the Office app writes to the
    ``.pdf`` name itself rather than to wherever a link there points.
    """
    try:
        pdf_path = Path(str(source_path) + ".pdf")
        refuse_symlink(pdf_path)

        _ = subprocess.run(
            [
                "osascript",
                "-e",
                applescript,
                "--",
                str(source_path.resolve()),
                str(pdf_path.parent.resolve() / pdf_path.name),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        if pdf_path.is_symlink() or not pdf_path.is_file():
            log.error("%s did not create PDF for %s", app_name, source_path.name)
            return False

        return True

    except subprocess.CalledProcessError as e:
        log.exception("AppleScript failed for %s", source_path.name)
        if e.stderr:
            log.error("%s", e.stderr.strip())
        return False
    except SymlinkRefusedError as exc:
        log.error("Skipping %s: %s", source_path.name, exc)
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
