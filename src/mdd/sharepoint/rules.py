"""rules.py — per-file action decision table for SharePoint export."""

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.utils.mddignore import MddIgnore


class FileAction(StrEnum):
    CONVERT_DOCX = "convert_docx"
    CONVERT_PPTX = "convert_pptx"
    CONVERT_PDF = "convert_pdf"
    COPY_MARKDOWN = "copy_markdown"
    IGNORE = "ignore"
    SKIP_WITH_WARNING = "skip_with_warning"
    SKIP_IGNORED = "skip_ignored"
    """Skipped because the path matches a ``.mddignore`` rule."""


IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".svg"}
)

IGNORED_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls"}) | IMAGE_EXTENSIONS


def _is_ignored_by_matcher(matcher: MddIgnore | None, rel_path: Path | None) -> bool:
    """True if *matcher* is non-None AND *rel_path* is matched as a file."""
    return (
        matcher is not None and rel_path is not None and matcher.is_ignored(rel_path, is_dir=False)
    )


# Extension → converter ``FileAction`` for the convertible-office types
# (rule 1 path). A sibling .md overrides the action to ``COPY_MARKDOWN``;
# the lookup itself only encodes "which converter would otherwise run".
_CONVERTIBLE: dict[str, FileAction] = {
    ".docx": FileAction.CONVERT_DOCX,
    ".doc": FileAction.CONVERT_DOCX,
    ".pptx": FileAction.CONVERT_PPTX,
    ".pdf": FileAction.CONVERT_PDF,
}


def decide(
    file_path: Path,
    *,
    has_sibling_md: bool,
    matcher: MddIgnore | None = None,
    rel_path: Path | None = None,
) -> FileAction:
    """Return the :class:`FileAction` for *file_path*.

    Rules (first match wins):
      0. If *matcher* is supplied and ``is_ignored(rel_path)`` is True →
         :attr:`SKIP_IGNORED` (source-side ``.mddignore`` filter).
      1. If *has_sibling_md*: the caller already found a ``<name>.<ext>.md`` next
         to this file — treat the ``.md`` as the master, copy it through.
      2. ``.docx`` / ``.doc`` → convert with Docling.
      3. ``.pptx`` → convert with python-pptx.
      4. ``.pdf`` → convert with Docling.
      5. ``.md`` (standalone) → copy through.
      6. Standalone images → ignore (likely duplicated inside nearby Office files).
      7. ``.xlsx`` / ``.xls`` → ignore.
      8. Anything else → skip with a warning.

    Note: rule 1 is only applied to *convertible* file types
    (``.docx``, ``.doc``, ``.pptx``, ``.pdf``).  For ``.md`` files the
    sibling-md concept does not apply — they are always :attr:`COPY_MARKDOWN`.

    The optional *matcher* / *rel_path* pair lets callers funnel
    every per-file decision through the same gate. When *matcher* is ``None``
    or *rel_path* is ``None`` the ignore check is silently skipped — backward
    compatible with the original two-argument signature.
    """
    if _is_ignored_by_matcher(matcher, rel_path):
        return FileAction.SKIP_IGNORED
    ext = file_path.suffix.lower()

    # Rule 5: standalone .md — always copy.
    if ext == ".md":
        return FileAction.COPY_MARKDOWN
    # Rules 6 + 7: media + spreadsheet sinks are silently dropped.
    if ext in IGNORED_EXTENSIONS:
        return FileAction.IGNORE
    # Rules 1 + 2/3/4: convertible types (sibling-md wins).
    convert_action = _CONVERTIBLE.get(ext)
    if convert_action is not None:
        return FileAction.COPY_MARKDOWN if has_sibling_md else convert_action
    # Rule 8: everything else.
    return FileAction.SKIP_WITH_WARNING
