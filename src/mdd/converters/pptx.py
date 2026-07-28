"""pptx.py — PptxConverter: convert .pptx files to Markdown.

Wraps convert.pptx.convert_pptx; behaviour is unchanged.
"""

from typing import TYPE_CHECKING

from mdd.convert import CorruptSourceError
from mdd.converters.protocol import ConvertResult
from mdd.utils.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path


class PptxConverter:
    """Convert .pptx files to .pptx.md (python-pptx)."""

    extensions: tuple[str, ...] = (".pptx",)
    output_suffix: str = ".md"

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        # test-seam: re-imported here so monkeypatch on
        # ``mdd.convert.pptx.convert_pptx`` reaches this call site.
        from mdd.convert.pptx import convert_pptx  # noqa: PLC0415

        if dest is None:
            dest = src.parent / (src.name + self.output_suffix)
        try:
            convert_pptx(src, dest)
        except CorruptSourceError:
            # Caller (sync dispatcher) records this as a soft skip — do not
            # log an ERROR here, that would double-count and confuse users.
            raise
        except Exception:
            log.exception("error converting %s", src)
            raise
        # Attachments dir follows the same naming convention as convert_pptx uses:
        # dst.parent / (dst.stem + "-attachments")
        attachments_dir = dest.parent / (dest.stem + "-attachments")
        return ConvertResult(
            output_path=dest,
            attachments_dir=attachments_dir if attachments_dir.exists() else None,
            metadata={},
            warnings=[],
        )
