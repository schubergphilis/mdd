"""converters — converter registry for mdd.

Public API:
    Converter           — forward-converter Protocol
    ReverseConverter    — reverse-converter Protocol
    ConvertResult       — result dataclass for Converter.convert()
    RenderResult        — result dataclass for ReverseConverter.render()
    CONVERTERS          — dict[str, Converter] keyed by lowercased extension
    REVERSE_CONVERTERS  — dict[str, ReverseConverter] keyed by target extension
    converter_for(path) — look up Converter by path extension (case-insensitive)
    reverse_for(ext)    — look up ReverseConverter by target extension
    register(conv)      — register a Converter (raises on duplicate)
    register_reverse(r) — register a ReverseConverter (raises on duplicate)

Adding a new file type: create a converter module under src/mdd/converters/
and call register() here (or in the module itself, imported below).
"""

# ---------------------------------------------------------------------------
# Built-in converter registrations
# ---------------------------------------------------------------------------
from mdd.converters.docx import DocxConverter
from mdd.converters.pdf import PdfConverter
from mdd.converters.pptx import PptxConverter
from mdd.converters.protocol import Converter, ConvertResult, RenderResult, ReverseConverter
from mdd.converters.quarto import QuartoDocxRenderer, QuartoPptxRenderer
from mdd.converters.registry import (
    CONVERTERS,
    REVERSE_CONVERTERS,
    converter_for,
    register,
    register_reverse,
    reverse_for,
)
from mdd.converters.svg import SvgToPngConverter

register(DocxConverter())
register(PptxConverter())
register(PdfConverter())
register(SvgToPngConverter())

register_reverse(QuartoDocxRenderer())
register_reverse(QuartoPptxRenderer())

__all__ = [
    "CONVERTERS",
    "REVERSE_CONVERTERS",
    "ConvertResult",
    "Converter",
    "DocxConverter",
    "PdfConverter",
    "PptxConverter",
    "QuartoDocxRenderer",
    "QuartoPptxRenderer",
    "RenderResult",
    "ReverseConverter",
    "SvgToPngConverter",
    "converter_for",
    "register",
    "register_reverse",
    "reverse_for",
]
