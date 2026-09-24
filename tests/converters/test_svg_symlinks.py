"""SVG rasterisation refuses to write through symlinks at the PNG, its temp file or the sidecar."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from mdd.converters.models import SvgConfig
from mdd.converters.svg import SvgToPngConverter
from mdd.utils.safe_write import SymlinkRefusedError

if TYPE_CHECKING:
    from pathlib import Path

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>'


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


def _converter() -> tuple[SvgToPngConverter, MagicMock]:
    renderer = MagicMock()
    renderer.name = "rsvg-convert"
    type(renderer).version = property(lambda _self: "2.58.0")

    def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
        dest.write_bytes(b"\x89PNG")

    renderer.render.side_effect = fake_render
    c = SvgToPngConverter()
    c._renderer = renderer  # pyright: ignore[reportPrivateUsage]
    c._cfg = SvgConfig()  # pyright: ignore[reportPrivateUsage]
    return c, renderer


class TestSvgConvertRefusesSymlinks:
    def test_dangling_png_tmp_symlink(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        svg = tmp_path / "Foo.svg"
        svg.write_text(_SVG)
        _plant_symlink(tmp_path / "Foo.svg.png.tmp", outside / "target")
        c, renderer = _converter()

        with pytest.raises(SymlinkRefusedError):
            c.convert(svg)

        renderer.render.assert_not_called()
        assert not (outside / "target").exists()

    def test_symlinked_png_dest(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim.png"
        victim.write_bytes(b"keep me")
        svg = tmp_path / "Foo.svg"
        svg.write_text(_SVG)
        _plant_symlink(tmp_path / "Foo.svg.png", victim)
        c, renderer = _converter()

        with pytest.raises(SymlinkRefusedError):
            c.convert(svg)

        renderer.render.assert_not_called()
        assert victim.read_bytes() == b"keep me"

    def test_dangling_sidecar_tmp_symlink(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        svg = tmp_path / "Foo.svg"
        svg.write_text(_SVG)
        _plant_symlink(tmp_path / "Foo.svg.meta.yaml.tmp", outside / "target")
        c, _renderer = _converter()

        with pytest.raises(SymlinkRefusedError):
            c.convert(svg)

        assert not (outside / "target").exists()
        assert not (tmp_path / "Foo.svg.meta.yaml").exists()
