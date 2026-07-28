"""Tests for mdd.converters.svg (SvgToPngConverter) and mdd.utils.svg_runner."""

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mdd.converters.models import SvgConfig
from mdd.converters.svg import (
    MAX_DIMENSION,
    SvgToPngConverter,
    _cache_hit,  # pyright: ignore[reportPrivateUsage]
    _compute_effective_scale,  # pyright: ignore[reportPrivateUsage]
    _file_sha256,  # pyright: ignore[reportPrivateUsage]
    _load_svg_config_from,  # pyright: ignore[reportPrivateUsage]
    _parse_svg_dimensions,  # pyright: ignore[reportPrivateUsage]
    _read_sidecar,  # pyright: ignore[reportPrivateUsage]
    _sidecar_path,  # pyright: ignore[reportPrivateUsage]
    _write_sidecar,  # pyright: ignore[reportPrivateUsage]
)
from mdd.utils.svg_runner import (
    RENDERERS,
    RendererUnavailableError,
    RsvgRenderer,
    _probe_version,  # pyright: ignore[reportPrivateUsage]
    get_renderer,
)

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# svg_runner — renderer registry
# ---------------------------------------------------------------------------


class TestGetRenderer:
    def test_known_renderer_returns_instance(self) -> None:
        r = get_renderer("rsvg-convert")
        assert r.name == "rsvg-convert"

    def test_unknown_renderer_raises(self) -> None:
        with pytest.raises(RendererUnavailableError, match="Unknown SVG renderer"):
            get_renderer("nonexistent-tool")

    def test_all_known_renderers_present(self) -> None:
        for name in ("rsvg-convert", "cairosvg", "resvg", "inkscape"):
            assert name in RENDERERS


class TestProbeVersion:
    def test_returns_first_line_of_stdout(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="rsvg-convert 2.58.0\n", stderr="")
            version = _probe_version("rsvg-convert", ["rsvg-convert", "--version"], "hint")
        assert version == "rsvg-convert 2.58.0"

    def test_falls_back_to_stderr(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", stderr="inkscape 1.2.0\n")
            version = _probe_version("inkscape", ["inkscape", "--version"], "hint")
        assert version == "inkscape 1.2.0"

    def test_raises_on_file_not_found(self) -> None:
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("not found")),
            pytest.raises(RendererUnavailableError, match="not found on PATH"),
        ):
            _probe_version("missing-tool", ["missing-tool", "--version"], "install hint")


# ---------------------------------------------------------------------------
# svg_runner — RsvgRenderer command construction
# ---------------------------------------------------------------------------


class TestRsvgRenderer:
    def test_render_invokes_correct_command(self, tmp_path: Path) -> None:
        src = tmp_path / "test.svg"
        src.write_text("<svg/>")
        dest = tmp_path / "test.svg.png"

        renderer = RsvgRenderer()
        # Pre-set version to avoid subprocess probe
        renderer._version_cache = "rsvg-convert 2.58.0"  # pyright: ignore[reportPrivateUsage]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            renderer.render(src, dest, scale=2.0, bg="transparent")

        mock_run.assert_called_once_with(
            [
                "rsvg-convert",
                "-z",
                "2.0",
                "--background-color",
                "transparent",
                "-o",
                str(dest),
                str(src),
            ],
            check=True,
        )

    def test_render_white_background(self, tmp_path: Path) -> None:
        src = tmp_path / "test.svg"
        src.write_text("<svg/>")
        dest = tmp_path / "test.svg.png"

        renderer = RsvgRenderer()
        renderer._version_cache = "rsvg-convert 2.58.0"  # pyright: ignore[reportPrivateUsage]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            renderer.render(src, dest, scale=1.5, bg="white")

        args: list[str] = mock_run.call_args[0][0]  # pyright: ignore[reportUnknownMemberType]
        assert "--background-color" in args
        idx = args.index("--background-color")
        assert args[idx + 1] == "white"


# ---------------------------------------------------------------------------
# svg.py — _parse_svg_dimensions
# ---------------------------------------------------------------------------


class TestParseSvgDimensions:
    def test_parses_width_height_attributes(self) -> None:
        svg = FIXTURES / "simple.svg"
        w, h = _parse_svg_dimensions(svg)
        assert w == 100.0
        assert h == 100.0

    def test_parses_viewbox_fallback(self, tmp_path: Path) -> None:
        svg = tmp_path / "vb.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150"/>')
        w, h = _parse_svg_dimensions(svg)
        assert w == 200.0
        assert h == 150.0

    def test_defaults_to_100_for_no_dimensions(self, tmp_path: Path) -> None:
        svg = tmp_path / "no-dims.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        w, h = _parse_svg_dimensions(svg)
        assert w == 100.0
        assert h == 100.0

    def test_pathological_svg_parses(self) -> None:
        svg = FIXTURES / "pathological.svg"
        w, h = _parse_svg_dimensions(svg)
        assert w == 10000.0
        assert h == 10000.0

    def test_handles_px_unit_suffix(self, tmp_path: Path) -> None:
        svg = tmp_path / "px.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300px" height="200px"/>')
        w, h = _parse_svg_dimensions(svg)
        assert w == 300.0
        assert h == 200.0

    def test_invalid_xml_fallback(self, tmp_path: Path) -> None:
        svg = tmp_path / "bad.svg"
        svg.write_text("not xml at all <><")
        w, h = _parse_svg_dimensions(svg)
        # Should fall back rather than raise
        assert w == 100.0
        assert h == 100.0


# ---------------------------------------------------------------------------
# svg.py — _compute_effective_scale (cap logic)
# ---------------------------------------------------------------------------


class TestComputeEffectiveScale:
    def test_no_cap_when_under_limit(self) -> None:
        warnings: list[str] = []
        s = _compute_effective_scale(100, 100, 2.0, warnings=warnings)
        assert math.isclose(s, 2.0)
        assert warnings == []

    def test_caps_at_max_dimension(self) -> None:
        warnings: list[str] = []
        # 10000 × 2.0 = 20000 >> 4096
        s = _compute_effective_scale(10000, 10000, 2.0, warnings=warnings)
        expected = MAX_DIMENSION / 10000
        assert math.isclose(s, expected)
        assert len(warnings) == 1
        assert "cap" in warnings[0].lower()

    def test_cap_honours_narrower_dimension(self) -> None:
        warnings: list[str] = []
        # 3000 × 2 = 6000 wide, 2000 × 2 = 4000 tall → only width needs cap
        s = _compute_effective_scale(3000, 2000, 2.0, warnings=warnings)
        expected = MAX_DIMENSION / 3000
        assert math.isclose(s, expected)
        assert len(warnings) == 1

    def test_exactly_at_limit_no_warning(self) -> None:
        warnings: list[str] = []
        s = _compute_effective_scale(2048, 2048, 2.0, warnings=warnings)
        assert math.isclose(s, 2.0)
        assert warnings == []


# ---------------------------------------------------------------------------
# svg.py — sidecar read / write
# ---------------------------------------------------------------------------


class TestSidecar:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text("<svg/>")
        _write_sidecar(
            svg,
            source_sha256="abc123",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="transparent",
        )
        sc = _read_sidecar(svg)
        assert sc["source_sha256"] == "abc123"
        assert sc["renderer"] == "rsvg-convert"
        assert sc["renderer_version"] == "2.58.0"
        assert sc["png_scale"] == 2.0
        assert sc["background"] == "transparent"
        assert "rendered_at" in sc

    def test_sidecar_path(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        expected = tmp_path / "Foo.svg.meta.yaml"
        assert _sidecar_path(svg) == expected

    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        assert _read_sidecar(svg) == {}

    def test_read_malformed_returns_empty(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        sc = tmp_path / "Foo.svg.meta.yaml"
        sc.write_text("not: valid: yaml: {{{")
        result = _read_sidecar(svg)
        assert result == {}


# ---------------------------------------------------------------------------
# svg.py — _cache_hit
# ---------------------------------------------------------------------------


class TestCacheHit:
    def _make_setup(  # noqa: PLR0913
        self,
        tmp_path: Path,
        *,
        png_exists: bool = True,
        sha: str = "deadbeef",
        renderer: str = "rsvg-convert",
        version: str = "2.58.0",
        scale: float = 2.0,
        bg: str = "transparent",
    ) -> Path:
        svg = tmp_path / "Foo.svg"
        svg.write_text("<svg/>")
        if png_exists:
            (tmp_path / "Foo.svg.png").write_bytes(b"\x89PNG")
        _write_sidecar(
            svg,
            source_sha256=sha,
            renderer_name=renderer,
            renderer_version=version,
            png_scale=scale,
            background=bg,
        )
        return svg

    def test_cache_hit_when_all_match(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path)
        assert _cache_hit(
            svg,
            source_sha256="deadbeef",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="transparent",
        )

    def test_miss_when_sha_differs(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path)
        assert not _cache_hit(
            svg,
            source_sha256="different",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="transparent",
        )

    def test_miss_when_png_absent(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path, png_exists=False)
        assert not _cache_hit(
            svg,
            source_sha256="deadbeef",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="transparent",
        )

    def test_miss_when_scale_differs(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path)
        assert not _cache_hit(
            svg,
            source_sha256="deadbeef",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=3.0,
            background="transparent",
        )

    def test_miss_when_renderer_version_differs(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path)
        assert not _cache_hit(
            svg,
            source_sha256="deadbeef",
            renderer_name="rsvg-convert",
            renderer_version="2.59.0",
            png_scale=2.0,
            background="transparent",
        )

    def test_miss_when_background_differs(self, tmp_path: Path) -> None:
        svg = self._make_setup(tmp_path)
        assert not _cache_hit(
            svg,
            source_sha256="deadbeef",
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="white",
        )


# ---------------------------------------------------------------------------
# svg.py — SvgToPngConverter.convert() (mocked renderer)
# ---------------------------------------------------------------------------


def _make_mock_renderer(name: str = "rsvg-convert", version: str = "2.58.0") -> MagicMock:
    r = MagicMock()
    r.name = name
    type(r).version = property(lambda self: version)
    return r


class TestSvgToPngConverter:
    def _converter(self, renderer: MagicMock) -> SvgToPngConverter:
        """Return a converter with the mocked renderer pre-installed."""
        c = SvgToPngConverter()
        c._renderer = renderer  # pyright: ignore[reportPrivateUsage]
        c._cfg = SvgConfig()  # pyright: ignore[reportPrivateUsage]
        return c

    def test_convert_produces_png_sibling(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>')

        mock_renderer = _make_mock_renderer()

        def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            dest.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_renderer.render.side_effect = fake_render

        c = self._converter(mock_renderer)
        result = c.convert(svg)

        assert result.output_path == tmp_path / "Foo.svg.png"
        assert result.output_path.exists()

    def test_convert_writes_sidecar(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>')

        mock_renderer = _make_mock_renderer()

        def fake_render(src: Path, dest: Path, *, scale: float, bg: float) -> None:
            dest.write_bytes(b"\x89PNG")

        mock_renderer.render.side_effect = fake_render

        c = self._converter(mock_renderer)
        c.convert(svg)

        sc = _read_sidecar(svg)
        assert sc["renderer"] == "rsvg-convert"
        assert sc["png_scale"] == 2.0
        assert sc["background"] == "transparent"
        assert len(sc["source_sha256"]) == 64  # sha256 hex

    def test_convert_cache_hit_skips_render(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>')
        sha = _file_sha256(svg)

        # Seed the cache
        (tmp_path / "Foo.svg.png").write_bytes(b"\x89PNG")
        _write_sidecar(
            svg,
            source_sha256=sha,
            renderer_name="rsvg-convert",
            renderer_version="2.58.0",
            png_scale=2.0,
            background="transparent",
        )

        mock_renderer = _make_mock_renderer()
        c = self._converter(mock_renderer)
        c.convert(svg)

        mock_renderer.render.assert_not_called()

    def test_convert_respects_dest_parameter(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"/>')

        mock_renderer = _make_mock_renderer()

        def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\x89PNG")

        mock_renderer.render.side_effect = fake_render

        dest = tmp_path / "out" / "custom.png"
        c = self._converter(mock_renderer)
        result = c.convert(svg, dest=dest)

        assert result.output_path == dest
        assert dest.exists()

    def test_convert_caps_pathological_svg(self, tmp_path: Path) -> None:
        import shutil

        # Copy fixture to tmp_path so sidecar is written there, not in the repo
        svg = tmp_path / "pathological.svg"
        shutil.copy(FIXTURES / "pathological.svg", svg)

        mock_renderer = _make_mock_renderer()

        captured_scale: list[float] = []

        def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            captured_scale.append(scale)
            dest.write_bytes(b"\x89PNG")

        mock_renderer.render.side_effect = fake_render

        c = SvgToPngConverter()
        c._renderer = mock_renderer  # pyright: ignore[reportPrivateUsage]
        c._cfg = SvgConfig()  # pyright: ignore[reportPrivateUsage]
        result = c.convert(svg, dest=tmp_path / "pathological.svg.png")

        assert len(result.warnings) >= 1
        assert any("cap" in w.lower() for w in result.warnings)
        # Captured scale should be capped
        assert captured_scale[0] < 2.0
        expected_cap = MAX_DIMENSION / 10000
        assert math.isclose(captured_scale[0], expected_cap)

    def test_convert_with_fonts_does_not_raise(self, tmp_path: Path) -> None:
        """with-fonts.svg has an external @import; renderer still attempts render."""
        import shutil

        # Copy fixture to tmp_path so sidecar is written there, not in the repo
        svg = tmp_path / "with-fonts.svg"
        shutil.copy(FIXTURES / "with-fonts.svg", svg)

        mock_renderer = _make_mock_renderer()

        def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            dest.write_bytes(b"\x89PNG")

        mock_renderer.render.side_effect = fake_render

        c = SvgToPngConverter()
        c._renderer = mock_renderer  # pyright: ignore[reportPrivateUsage]
        c._cfg = SvgConfig()  # pyright: ignore[reportPrivateUsage]
        # Should not raise; renderer is called regardless of external refs
        result = c.convert(svg, dest=tmp_path / "with-fonts.svg.png")
        assert result.output_path.exists()

    def test_convert_default_scale_is_2x(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')

        mock_renderer = _make_mock_renderer()
        called_with: list[float] = []

        def fake_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            called_with.append(scale)
            dest.write_bytes(b"\x89PNG")

        mock_renderer.render.side_effect = fake_render

        c = self._converter(mock_renderer)
        c.convert(svg)

        assert called_with == [2.0]

    def test_converter_extensions(self) -> None:
        c = SvgToPngConverter()
        assert ".svg" in c.extensions

    def test_converter_output_suffix(self) -> None:
        c = SvgToPngConverter()
        assert c.output_suffix == ".png"

    def test_convert_renderer_failure_raises(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')

        mock_renderer = _make_mock_renderer()
        mock_renderer.render.side_effect = RuntimeError("render failed")

        c = self._converter(mock_renderer)
        with pytest.raises(RuntimeError, match="SVG rasterization failed"):
            c.convert(svg)

    def test_convert_removes_tmp_on_failure(self, tmp_path: Path) -> None:
        svg = tmp_path / "Foo.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')

        mock_renderer = _make_mock_renderer()

        def bad_render(src: Path, dest: Path, *, scale: float, bg: str) -> None:
            dest.write_bytes(b"partial")
            raise RuntimeError("boom")

        mock_renderer.render.side_effect = bad_render

        c = self._converter(mock_renderer)
        with pytest.raises(RuntimeError):
            c.convert(svg)

        # The .tmp file should be cleaned up
        tmp_candidates = list(tmp_path.glob("*.tmp"))
        assert tmp_candidates == []


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_svg_registered_in_converters(self) -> None:
        from mdd.converters import CONVERTERS

        assert ".svg" in CONVERTERS

    def test_svg_converter_for_lookup(self) -> None:
        from mdd.converters import converter_for

        svg_path = Path("Foo.svg")
        c = converter_for(svg_path)
        assert c is not None
        assert isinstance(c, SvgToPngConverter)

    def test_svg_case_insensitive(self) -> None:
        from mdd.converters import converter_for

        assert converter_for(Path("logo.SVG")) is not None
        assert converter_for(Path("logo.Svg")) is not None


# ---------------------------------------------------------------------------
# Typed config loader (_load_svg_config_from + SvgConfig)
# ---------------------------------------------------------------------------


class TestSvgConfigLoader:
    def test_valid_config_round_trip(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("svg:\n  renderer: resvg\n  png_scale: 3.0\n  background: white\n")
        cfg = _load_svg_config_from(cfg_path)
        assert cfg is not None
        assert cfg.renderer == "resvg"
        assert cfg.png_scale == 3.0
        assert cfg.background == "white"

    def test_quoted_scalar_coerces(self, tmp_path: Path) -> None:
        # Flexible-type coercion — quoted "3.0" still decodes into float.
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text('svg:\n  png_scale: "3.0"\n')
        cfg = _load_svg_config_from(cfg_path)
        assert cfg is not None
        assert cfg.png_scale == 3.0

    def test_empty_block_yields_defaults(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("svg: {}\n")
        cfg = _load_svg_config_from(cfg_path)
        assert cfg is not None
        assert cfg.renderer == "rsvg-convert"
        assert cfg.png_scale == 2.0
        assert cfg.background == "transparent"

    def test_no_svg_block_returns_none(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("confluence:\n  base_url: https://x\n")
        assert _load_svg_config_from(cfg_path) is None

    def test_unknown_key_in_block_returns_none_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Typo'd key — strict extras at the SvgConfig level.  Loader logs
        # and falls through (returns None) rather than raising, so the
        # converter still runs with defaults.
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("svg:\n  pngscale: 4.0\n")  # 'pngscale' typo for 'png_scale'
        import logging

        with caplog.at_level(logging.WARNING):
            result = _load_svg_config_from(cfg_path)
        assert result is None
        assert any("pngscale" in r.message or "Extra" in r.message for r in caplog.records)

    def test_direct_unknown_key_on_svg_config_raises(self) -> None:
        # Mirror tests/confluence/test_models.py: strict extras on the
        # user-edited inner model.
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            _ = SvgConfig.model_validate({"renderer": "resvg", "pngscale": 4.0})
        assert "pngscale" in str(exc.value)

    def test_non_yaml_file_returns_none(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("not: valid: yaml: {{{")
        assert _load_svg_config_from(cfg_path) is None

    def test_yaml_scalar_returns_none(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("just-a-string")
        assert _load_svg_config_from(cfg_path) is None


# ---------------------------------------------------------------------------
# End-to-end tests (require rsvg-convert on PATH)
# ---------------------------------------------------------------------------


class TestSvgToPngConverterEndToEnd:
    def test_rasterize_simple_svg(self, tmp_path: Path) -> None:
        """Render simple.svg with the real rsvg-convert (requires librsvg)."""
        svg = FIXTURES / "simple.svg"
        dest = tmp_path / "simple.svg.png"
        c = SvgToPngConverter()
        result = c.convert(svg, dest=dest)
        assert dest.exists()
        assert dest.stat().st_size > 0
        # Verify it is a PNG (magic bytes)
        assert dest.read_bytes()[:4] == b"\x89PNG"
        assert result.warnings == []

    def test_rasterize_pathological_warns_and_caps(self, tmp_path: Path) -> None:
        svg = FIXTURES / "pathological.svg"
        dest = tmp_path / "pathological.svg.png"
        c = SvgToPngConverter()
        result = c.convert(svg, dest=dest)
        assert dest.exists()
        assert len(result.warnings) >= 1
        assert any("cap" in w.lower() for w in result.warnings)

    def test_cache_hit_skips_rerasterize(self, tmp_path: Path) -> None:
        # Copy SVG into tmp_path so the sidecar lands in the test sandbox,
        # not in the shared fixtures dir.
        import shutil

        svg = tmp_path / "simple.svg"
        shutil.copy(FIXTURES / "simple.svg", svg)
        dest = tmp_path / "simple.svg.png"

        c = SvgToPngConverter()
        c.convert(svg, dest=dest)
        mtime1 = dest.stat().st_mtime

        # Second run: must be cache hit
        c2 = SvgToPngConverter()
        c2.convert(svg, dest=dest)
        mtime2 = dest.stat().st_mtime

        assert mtime1 == mtime2, "PNG was re-rendered on a cache hit"
