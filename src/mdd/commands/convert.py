"""convert — recursively convert .docx/.pptx/.pdf files to Markdown.

Uses Docling for body content and python-docx for metadata extraction (.docx).
Uses python-pptx for .pptx conversion. Uses Docling for .pdf conversion.

NOTE: Docling downloads ML models (~500 MB) on first use, cached in
~/.cache/docling/. Subsequent runs reuse the cached models.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast

from mdd.converters import converter_for
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

log = get_logger(__name__)


def dest_path(src: Path, src_root: Path, dest_root: Path | None) -> Path:
    """Compute the output .md path for a source file."""
    rel = src.relative_to(src_root)
    if dest_root is None:
        return src.parent / (src.name + ".md")
    return dest_root / rel.parent / (rel.name + ".md")


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "collect_files",
    "dest_path",
    "register",
]

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx", ".pdf"})


def collect_files(path: Path) -> list[Path]:
    """Collect all supported files under path (or return [path] if a file)."""
    if path.is_file():
        return [path]
    return sorted(f for f in path.rglob("*") if f.suffix.lower() in SUPPORTED_EXTENSIONS)


def _convert_file(
    src: Path,
    src_root: Path,
    dest_root: Path | None,
    force: bool,
    dry_run: bool,
) -> bool:
    """Convert one file. Returns True on success."""
    out = dest_path(src, src_root, dest_root)
    if not force and out.exists() and src.stat().st_mtime <= out.stat().st_mtime:
        return True

    if dry_run:
        log.info("Would convert: %s", src)
        return True

    ext = src.suffix.lower()
    if ext == ".doc":
        log.warning("legacy .doc is not supported; please convert to .docx: %s", src)
        return False

    converter = converter_for(src)
    if converter is None:
        log.warning("unsupported extension %r for %s", ext, src)
        return False

    try:
        converter.convert(src, dest=out)
        return True
    except Exception as e:
        log.exception("converting %s: %s", src, e)
        return False


def _resolve_sources(
    file_arg: str | None,
    path_arg: str | None,
) -> tuple[Path, list[Path]] | None:
    """Resolve --file / positional path into (src_root, files)."""
    if file_arg:
        src = Path(file_arg)
        if not src.exists():
            log.error("path does not exist: %s", src)
            return None
        return src.parent, [src]
    if path_arg:
        path = Path(path_arg)
        if not path.exists():
            log.error("path does not exist: %s", path)
            return None
        src_root = path.parent if path.is_file() else path
        return src_root, collect_files(path)
    return None


class _ConvertArgs(argparse.Namespace):
    path: str | None
    file: str | None
    dest_dir: str | None
    force: bool
    dry_run: bool
    # ``_convert_parser`` is injected via ``p.set_defaults(_convert_parser=p)``
    # so the handler can print the subcommand's help on missing args.
    _convert_parser: argparse.ArgumentParser  # pyright: ignore[reportPrivateUsage]


def _run_convert(ns: argparse.Namespace) -> int:
    args = cast("_ConvertArgs", ns)
    resolved = _resolve_sources(args.file, args.path)
    if resolved is None:
        if args.file is None and args.path is None:
            # No source given — argparse already accepted that, so print help.
            args._convert_parser.print_help()  # pyright: ignore[reportPrivateUsage]
        return 1
    src_root, files = resolved

    dest_root = Path(args.dest_dir) if args.dest_dir else None
    force = args.force
    dry_run = args.dry_run

    total = len(files)
    failures: list[Path] = []

    for n, src in enumerate(files, 1):
        rel = src.relative_to(src_root) if src.is_relative_to(src_root) else src
        log.info("[%d/%d] Converting: %s", n, total, rel)
        ok = _convert_file(src, src_root, dest_root, force=force, dry_run=dry_run)
        if not ok:
            failures.append(src)

    if failures:
        log.error("Failed (%d):", len(failures))
        for f in failures:
            log.error("  %s", f)
        return 1

    return 0


def register(
    subparsers: SubParsers,
    parents: CommonParents,
) -> None:
    p = subparsers.add_parser(
        "convert",
        parents=[parents.dry_run],
        help="Convert .docx/.pptx/.pdf files to Markdown (.md) using Docling",
        description=(
            "Recursively convert .docx/.pptx/.pdf files to Markdown.\n\n"
            "NOTE: Docling downloads ML models (~500 MB) on first use, cached in "
            "~/.cache/docling/. Subsequent runs reuse the cached models."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ = p.add_argument("path", nargs="?", help="Directory or file to convert")
    _ = p.add_argument(
        "--dest-dir", metavar="DIR", help="Write output files here (mirroring source tree)"
    )
    _ = p.add_argument("--force", action="store_true", help="Regenerate even if .md is up to date")
    _ = p.add_argument(
        "--file",
        metavar="PATH",
        help="Convert a single file (bypasses extension check)",
    )
    p.set_defaults(func=_run_convert, _convert_parser=p)
