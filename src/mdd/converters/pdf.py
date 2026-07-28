"""pdf.py — PdfConverter: convert .pdf files to Markdown.

Wraps convert.pdf.convert_pdf; behaviour is unchanged.
"""

from typing import TYPE_CHECKING

from mdd.converters.protocol import ConvertResult
from mdd.utils.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path


class PdfConverter:
    """Convert .pdf files to .pdf.md (Docling)."""

    extensions: tuple[str, ...] = (".pdf",)
    output_suffix: str = ".md"

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        # test-seam: re-imported here so monkeypatch on
        # ``mdd.convert.pdf.convert_pdf`` reaches this call site.
        from mdd.convert.pdf import convert_pdf  # noqa: PLC0415

        if dest is None:
            dest = src.parent / (src.name + self.output_suffix)
        try:
            convert_pdf(src, dest)
        except Exception:
            log.exception("error converting %s", src)
            raise
        # Attachments dir follows the same naming convention as convert_pdf uses:
        # dst.parent / (dst.stem + "-attachments")
        attachments_dir = dest.parent / (dest.stem + "-attachments")
        return ConvertResult(
            output_path=dest,
            attachments_dir=attachments_dir if attachments_dir.exists() else None,
            metadata={},
            warnings=[],
        )
