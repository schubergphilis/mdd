"""Structural tests for the bundled simple-presentation*.pptx templates.

Regression coverage for issue #75: pandoc's pptx writer expects 11 slide
layouts in the reference doc (matching the standard Microsoft layout set).
When the template only had 9, pandoc added slideLayout10/11 as parts in the
rendered archive without wiring them into slideMaster1.xml.rels, producing
orphan layouts that triggered PowerPoint's repair dialog.

Also covers issue #19: `simple-presentation-compact.pptx` is the same archive
with a smaller `<p:bodyStyle>` scale, derived by
``scripts/derive-compact-pptx.py``.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mdd.utils.scaffolding import get_template_path

if TYPE_CHECKING:
    from types import ModuleType

TEMPLATE = get_template_path("simple-presentation.pptx")
COMPACT_TEMPLATE = get_template_path("simple-presentation-compact.pptx")

MASTER = "ppt/slideMasters/slideMaster1.xml"

DERIVE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "derive-compact-pptx.py"

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

# `<p:bodyStyle>` sizes, in hundredths of a point, levels 1-9.
DEFAULT_BODY_SIZES = [2800, 2400, 2000, 1800, 1800, 1800, 1800, 1800, 1800]
COMPACT_BODY_SIZES = [1800, 1600, 1400, 1200, 1200, 1200, 1200, 1200, 1200]


def _load_derive() -> ModuleType:
    spec = importlib.util.spec_from_file_location("derive_compact_pptx", DERIVE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["derive_compact_pptx"] = module
    spec.loader.exec_module(module)
    return module


def _layout_numbers(zf: zipfile.ZipFile, member: str) -> set[str]:
    return set(re.findall(r"slideLayout\d+", zf.read(member).decode("utf-8")))


def _body_style_sizes(pptx: Path) -> list[int]:
    """Return the nine `<p:bodyStyle>` `defRPr` sizes from *pptx*'s slide master."""
    with zipfile.ZipFile(pptx) as zf:
        xml = zf.read(MASTER).decode("utf-8")
    body = xml[xml.index("<p:bodyStyle>") : xml.index("</p:bodyStyle>")]
    sizes: list[int] = []
    for level in range(1, 10):
        match = re.search(
            rf'<a:lvl{level}pPr\b[^>]*>.*?<a:defRPr[^>]*?\bsz="(\d+)"',
            body,
            re.DOTALL,
        )
        assert match is not None, f"no sz for <p:bodyStyle> level {level} in {pptx.name}"
        sizes.append(int(match.group(1)))
    return sizes


ALL_TEMPLATES = pytest.mark.parametrize(
    "template",
    [TEMPLATE, COMPACT_TEMPLATE],
    ids=lambda p: p.name,
)


class TestBundledTemplate:
    @ALL_TEMPLATES
    def test_exists(self, template: Path) -> None:
        assert template.is_file()

    @ALL_TEMPLATES
    def test_is_a_readable_archive(self, template: Path) -> None:
        with zipfile.ZipFile(template) as zf:
            assert zf.testzip() is None
            assert zf.namelist()[0] == "[Content_Types].xml"

    @ALL_TEMPLATES
    def test_python_pptx_can_open(self, template: Path) -> None:
        from pptx import Presentation

        prs = Presentation(str(template))
        assert len(prs.slide_masters) == 1
        assert len(prs.slide_masters[0].slide_layouts) == 11

    @ALL_TEMPLATES
    def test_has_eleven_slide_layouts(self, template: Path) -> None:
        with zipfile.ZipFile(template) as zf:
            parts = {
                n for n in zf.namelist() if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)
            }
            assert len(parts) == 11, f"expected 11 layout parts, got {len(parts)}: {parts}"

    @ALL_TEMPLATES
    def test_slide_master_references_all_layouts(self, template: Path) -> None:
        with zipfile.ZipFile(template) as zf:
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

    @ALL_TEMPLATES
    def test_layout_names_match_pandoc_expectations(self, template: Path) -> None:
        """Pandoc identifies layouts by name; the set must match its defaults."""
        names: set[str] = set()
        with zipfile.ZipFile(template) as zf:
            for member in zf.namelist():
                if not re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", member):
                    continue
                m = re.search(r'<p:cSld name="([^"]+)"', zf.read(member).decode("utf-8"))
                assert m is not None, f"no cSld name in {member}"
                names.add(m.group(1))
        assert names == EXPECTED_LAYOUT_NAMES


class TestCompactTemplate:
    """The compact variant differs from the default in exactly one XML part (issue #19)."""

    def test_default_scale_unchanged(self) -> None:
        assert _body_style_sizes(TEMPLATE) == DEFAULT_BODY_SIZES

    def test_compact_scale(self) -> None:
        assert _body_style_sizes(COMPACT_TEMPLATE) == COMPACT_BODY_SIZES

    def test_only_the_slide_master_differs(self) -> None:
        with zipfile.ZipFile(TEMPLATE) as a, zipfile.ZipFile(COMPACT_TEMPLATE) as b:
            assert a.namelist() == b.namelist(), "entry order must be preserved"
            assert [i.compress_type for i in a.infolist()] == [
                i.compress_type for i in b.infolist()
            ]
            differing = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert differing == [MASTER]

    def test_title_and_small_text_sizes_untouched(self) -> None:
        with zipfile.ZipFile(COMPACT_TEMPLATE) as zf:
            xml = zf.read(MASTER).decode("utf-8")
        title = xml[xml.index("<p:titleStyle>") : xml.index("</p:titleStyle>")]
        assert 'sz="4400"' in title
        other = xml[xml.index("<p:otherStyle>") : xml.index("</p:otherStyle>")]
        assert 'sz="4400"' not in other
        assert 'sz="1200"' in xml  # date / footer / slide-number placeholders
        assert 'sz="1000"' in xml  # AI-disclaimer textbox

    def test_matches_the_derivation_script(self, tmp_path: Path) -> None:
        """The committed binary must equal what derive-compact-pptx.py produces."""
        derive = _load_derive()
        produced = tmp_path / "produced.pptx"
        derive.build(TEMPLATE, produced)  # pyright: ignore[reportAny]
        assert produced.read_bytes() == COMPACT_TEMPLATE.read_bytes()


class TestQuartoRender:
    """Full render pipeline check — requires quarto + pandoc on PATH."""

    def _render(self, tmp_path: Path, template: Path) -> Path:
        qmd = tmp_path / "smoke.qmd"
        qmd.write_text(
            "---\n"
            'title: "Smoke"\n'
            "format:\n"
            "  pptx:\n"
            f"    reference-doc: {template.name}\n"
            "---\n\n"
            "## Hello\n\n- one\n- two\n"
        )
        _ = shutil.copy(template, tmp_path / template.name)

        _ = subprocess.run(
            ["quarto", "render", str(qmd)],
            check=True,
            cwd=tmp_path,
            capture_output=True,
        )
        rendered = tmp_path / "smoke.pptx"
        assert rendered.exists()
        return rendered

    def test_render_produces_no_orphan_layouts(self, tmp_path: Path) -> None:
        rendered = self._render(tmp_path, TEMPLATE)

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

    def test_compact_scale_survives_render(self, tmp_path: Path) -> None:
        """Selecting the compact template via front matter needs no converter change."""
        rendered = self._render(tmp_path, COMPACT_TEMPLATE)
        assert _body_style_sizes(rendered) == COMPACT_BODY_SIZES
