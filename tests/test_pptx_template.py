"""Structural tests for the bundled simple-presentation.pptx template.

Regression coverage for issue #75: pandoc's pptx writer expects 11 slide
layouts in the reference doc (matching the standard Microsoft layout set).
When the template only had 9, pandoc added slideLayout10/11 as parts in the
rendered archive without wiring them into slideMaster1.xml.rels, producing
orphan layouts that triggered PowerPoint's repair dialog.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from typing import TYPE_CHECKING

from mdd.utils.scaffolding import get_template_path

if TYPE_CHECKING:
    from pathlib import Path

TEMPLATE = get_template_path("simple-presentation.pptx")

EXPECTED_LAYOUT_NAMES = {
    "Title Slide",
    "Title and Content",
    "Section Header",
    "Two Content",
    "Comparison",
    "Title Only",
    "Blank",
    "Content with Caption",
    "Picture with Caption",
    "Title and Vertical Text",
    "Vertical Title and Text",
}


def _layout_numbers(zf: zipfile.ZipFile, member: str) -> set[str]:
    return set(re.findall(r"slideLayout\d+", zf.read(member).decode("utf-8")))


class TestBundledTemplate:
    def test_has_eleven_slide_layouts(self) -> None:
        with zipfile.ZipFile(TEMPLATE) as zf:
            parts = {
                n for n in zf.namelist() if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)
            }
            assert len(parts) == 11, f"expected 11 layout parts, got {len(parts)}: {parts}"

    def test_slide_master_references_all_layouts(self) -> None:
        with zipfile.ZipFile(TEMPLATE) as zf:
            parts = {
                re.search(r"slideLayout\d+", n).group(0)  # type: ignore[union-attr]
                for n in zf.namelist()
                if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)
            }
            master_refs = _layout_numbers(zf, "ppt/slideMasters/_rels/slideMaster1.xml.rels")
            content_types = _layout_numbers(zf, "[Content_Types].xml")
        assert parts == master_refs, "layouts referenced from slideMaster.rels must equal parts"
        assert parts.issubset(content_types), (
            "every layout part must be declared in [Content_Types].xml"
        )

    def test_layout_names_match_pandoc_expectations(self) -> None:
        """Pandoc identifies layouts by name; the set must match its defaults."""
        names: set[str] = set()
        with zipfile.ZipFile(TEMPLATE) as zf:
            for member in zf.namelist():
                if not re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", member):
                    continue
                m = re.search(r'<p:cSld name="([^"]+)"', zf.read(member).decode("utf-8"))
                assert m is not None, f"no cSld name in {member}"
                names.add(m.group(1))
        assert names == EXPECTED_LAYOUT_NAMES


class TestQuartoRender:
    """Full render pipeline check — requires quarto + pandoc on PATH."""

    def test_render_produces_no_orphan_layouts(self, tmp_path: Path) -> None:
        qmd = tmp_path / "smoke.qmd"
        qmd.write_text(
            "---\n"
            'title: "Smoke"\n'
            "format:\n"
            "  pptx:\n"
            "    reference-doc: simple-presentation.pptx\n"
            "---\n\n"
            "## Hello\n\n- one\n- two\n"
        )
        shutil.copy(TEMPLATE, tmp_path / "simple-presentation.pptx")

        subprocess.run(
            ["quarto", "render", str(qmd)],
            check=True,
            cwd=tmp_path,
            capture_output=True,
        )

        rendered = tmp_path / "smoke.pptx"
        assert rendered.exists()

        with zipfile.ZipFile(rendered) as zf:
            parts = {
                re.search(r"slideLayout\d+", n).group(0)  # type: ignore[union-attr]
                for n in zf.namelist()
                if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)
            }
            master_refs = _layout_numbers(zf, "ppt/slideMasters/_rels/slideMaster1.xml.rels")
        assert parts == master_refs, (
            f"rendered pptx has orphan slide layouts. parts={parts} master_refs={master_refs}"
        )
