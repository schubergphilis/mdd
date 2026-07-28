"""protocol.py — Converter and ReverseConverter protocols plus result dataclasses."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ConvertResult:
    """Result returned by Converter.convert()."""

    output_path: Path
    attachments_dir: Path | None  # e.g. Foo.docx-attachments/, or None
    metadata: dict[str, object]  # frontmatter dict (title, etc.)
    warnings: list[str]


@dataclass
class RenderResult:
    """Result returned by ReverseConverter.render()."""

    output_path: Path
    warnings: list[str] = field(default_factory=list)


class Converter(Protocol):
    """Protocol for forward converters (source format → Markdown)."""

    extensions: tuple[str, ...]
    """Tuple of lowercased extensions with leading dot, e.g. ('.docx',)."""

    output_suffix: str
    """Suffix appended to the full source filename, e.g. '.md' → Foo.docx.md."""

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        """Convert *src* and return a ConvertResult.

        If *dest* is None, the output is placed adjacent to *src*
        (src.parent / (src.name + output_suffix)).  If *dest* is given, the
        converter writes there directly.
        """
        ...


class ReverseConverter(Protocol):
    """Protocol for reverse converters (Markdown → target format).

    Populated by spec S17 (Quarto-based .md → .docx/.pptx).
    No implementations exist in this spec.
    """

    target_extension: str
    """Target file extension, e.g. '.docx'."""

    def render(self, md_path: Path, *, dest: Path) -> RenderResult:
        """Render *md_path* to *dest* and return a RenderResult."""
        ...
