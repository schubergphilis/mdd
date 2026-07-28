"""pdf.py — convert .pdf to .pdf.md using Docling."""

from functools import cache
from typing import TYPE_CHECKING, Any

import yaml

from mdd.utils.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from docling.document_converter import (
        DocumentConverter,  # pyright: ignore[reportMissingModuleSource]
    )


@cache
def _get_converter(*, with_picture_images: bool = False) -> DocumentConverter:
    """Return a module-level singleton DocumentConverter (lazy-initialised).

    With ``with_picture_images=True`` Docling rasterises page regions so that
    ``PictureItem.image.pil_image`` is populated. That is expensive (full-page
    rasterisation at ``images_scale``) and is therefore opt-in.

    ``@functools.cache`` keyed on the kw-only ``with_picture_images`` bool
    gives the same two-instance behaviour as the previous pair of module
    globals.
    """
    if with_picture_images:
        # lazy: docling pulls torch/transformers; loaded only on PDF conversion
        from docling.datamodel.base_models import (  # noqa: PLC0415
            InputFormat,  # pyright: ignore[reportMissingModuleSource]
        )
        from docling.datamodel.pipeline_options import (  # noqa: PLC0415
            PdfPipelineOptions,  # pyright: ignore[reportMissingModuleSource]
        )
        from docling.document_converter import (  # pyright: ignore[reportMissingModuleSource]  # noqa: PLC0415
            DocumentConverter,
            PdfFormatOption,
        )

        opts = PdfPipelineOptions()
        opts.generate_picture_images = True
        opts.images_scale = 2.0
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    # lazy: docling pulls torch/transformers; loaded only on PDF conversion
    from docling.document_converter import (  # noqa: PLC0415
        DocumentConverter,  # pyright: ignore[reportMissingModuleSource]
    )

    return DocumentConverter()


def _extract_title(meta: Any) -> str:  # pyright: ignore[reportAny,reportExplicitAny]
    return str(getattr(meta, "title", "") or "").strip()  # pyright: ignore[reportAny]


def _extract_author(meta: Any) -> str:  # pyright: ignore[reportAny,reportExplicitAny]
    raw_author: Any = getattr(meta, "author", None)  # pyright: ignore[reportAny]
    if isinstance(raw_author, list):
        raw_list: list[Any] = raw_author  # pyright: ignore[reportAny,reportUnknownVariableType]
        return ", ".join(str(a) for a in raw_list)
    if raw_author is not None:
        return str(raw_author).strip()
    return ""


def _extract_page_count(doc: Any) -> int:  # pyright: ignore[reportAny,reportExplicitAny]
    pages_obj: Any = getattr(doc, "pages", None)  # pyright: ignore[reportAny]
    if pages_obj is None:
        return 0
    try:
        return len(pages_obj)  # pyright: ignore[reportAny]
    except TypeError, AttributeError:
        return 0


def _build_frontmatter(src: Path, doc: Any) -> str:  # pyright: ignore[reportAny,reportExplicitAny]
    """Return YAML frontmatter (with delimiters and trailing blank) for ``doc``."""
    title = ""
    author = ""
    meta: Any = getattr(doc, "meta", None)  # pyright: ignore[reportAny]
    if meta is not None:
        title = _extract_title(meta)
        author = _extract_author(meta)
    page_count = _extract_page_count(doc)

    # Always record the resolved absolute path so frontmatter is deterministic
    # regardless of the caller's working directory.
    fm_data: dict[str, object] = {"source_path": str(src.resolve())}
    if title:
        fm_data["title"] = title
    if author:
        fm_data["author"] = author
    if page_count:
        fm_data["page_count"] = page_count
    fm_block = yaml.safe_dump({"pdf": fm_data}, default_flow_style=False, allow_unicode=True)
    return "\n".join(["---", *fm_block.rstrip().splitlines(), "---", ""])


def _extract_pictures(doc: Any, attachments_dir: Path) -> None:  # pyright: ignore[reportAny,reportExplicitAny]
    """Write Docling-detected pictures to ``attachments_dir`` as PNGs.

    Requires the converter to have been built with ``generate_picture_images``;
    otherwise ``pic.image`` is ``None`` and every entry warns.
    """
    pictures: Any = getattr(doc, "pictures", None)  # pyright: ignore[reportAny]
    if not pictures:
        return
    attachments_dir.mkdir(parents=True, exist_ok=True)
    img_failures = 0
    for i, pic in enumerate(pictures, 1):  # pyright: ignore[reportAny]
        try:
            pil_image: Any = pic.image.pil_image  # pyright: ignore[reportAny]
            pil_image.save(attachments_dir / f"image{i}.png", format="PNG")  # pyright: ignore[reportAny]
        except Exception as e:
            img_failures += 1
            log.warning("pdf image %d: %r", i, e)
    if img_failures:
        log.warning("%d image(s) could not be extracted", img_failures)


def convert_pdf(src: Path, dst: Path, *, extract_images: bool = False) -> None:
    """Convert src .pdf to dst .pdf.md using Docling.

    Extracts body text via Docling. PDF metadata (title, author, page count)
    goes into YAML frontmatter under the 'pdf:' key.

    With ``extract_images=True``, images detected by Docling are rasterised
    and written to ``<dst.stem>-attachments/``. This requires Docling to
    rasterise PDF pages and is significantly slower; it is off by default.
    """
    converter: Any = _get_converter(with_picture_images=extract_images)  # pyright: ignore[reportAny]
    result: Any = converter.convert(str(src))  # pyright: ignore[reportAny]
    doc: Any = result.document  # pyright: ignore[reportAny]

    fm = _build_frontmatter(src, doc)
    body: str = str(doc.export_to_markdown())  # pyright: ignore[reportAny]

    if extract_images:
        _extract_pictures(doc, dst.parent / (dst.stem + "-attachments"))

    # Atomic write
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".md.tmp")
    tmp.write_text(fm + body, encoding="utf-8")
    tmp.rename(dst)
