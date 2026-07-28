"""Tests for the shared content-addressed image writer.

This file grows incrementally with P03 issues: #93 lays down the
content-addressed dedup + pass-through write contract; later commits
add TIFF transcode (#94), >4k resize (#95), and WMF rasterize (#96)
test cases.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _minimal_png() -> bytes:
    """Return minimal valid 1x1 PNG bytes."""
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        b"+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )


def _other_png() -> bytes:
    """A different valid 1x1 PNG (different colour) for distinguish-blob tests."""
    # Minimal 1x1 black PNG, distinct bytes from _minimal_png above.
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADklEQVR42mNk"
        b"YPj/HwADAgH/eL2wRgAAAABJRU5ErkJggg=="
    )


class TestWriteImagePassThrough:
    """Known-format blobs (PNG/JPG/GIF) round-trip unchanged."""

    def test_returns_relative_path(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        cache: dict[str, Path] = {}
        dropped: list[str] = []
        result = write_image(
            tmp_path / "att", _minimal_png(), "png", cache=cache, on_drop=dropped.append
        )
        assert result is not None
        assert not result.dedup_hit
        assert result.rel_path.suffix == ".png"
        # Filename is content-addressed.
        assert result.rel_path.name.startswith("image_")
        assert (tmp_path / "att" / result.rel_path).is_file()
        assert dropped == []

    def test_jpeg_normalises_to_jpg(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        # Reuse the PNG blob — write_image trusts the declared format.
        cache: dict[str, Path] = {}
        result = write_image(
            tmp_path / "att",
            _minimal_png(),
            "jpeg",
            cache=cache,
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".jpg"


class TestWriteImageDedup:
    """Same blob → same on-disk file → second call is a dedup hit."""

    def test_same_blob_returns_same_path(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        cache: dict[str, Path] = {}
        png = _minimal_png()
        r1 = write_image(tmp_path / "att", png, "png", cache=cache, on_drop=lambda _r: None)
        r2 = write_image(tmp_path / "att", png, "png", cache=cache, on_drop=lambda _r: None)
        assert r1 is not None
        assert r2 is not None
        assert r1.rel_path == r2.rel_path
        assert not r1.dedup_hit
        assert r2.dedup_hit
        # Only one file on disk.
        assert len(list((tmp_path / "att").iterdir())) == 1

    def test_different_blobs_different_paths(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        cache: dict[str, Path] = {}
        r1 = write_image(
            tmp_path / "att",
            _minimal_png(),
            "png",
            cache=cache,
            on_drop=lambda _r: None,
        )
        r2 = write_image(
            tmp_path / "att",
            _other_png(),
            "png",
            cache=cache,
            on_drop=lambda _r: None,
        )
        assert r1 is not None
        assert r2 is not None
        assert r1.rel_path != r2.rel_path
        assert len(list((tmp_path / "att").iterdir())) == 2

    def test_png_under_cap_is_losslessly_optimized(self, tmp_path: Path) -> None:
        """In-bounds PNGs are re-optimized (keep-smaller), not written verbatim (S42)."""
        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
            write_image,
        )

        cache: dict[str, Path] = {}
        png = _minimal_png()
        result = write_image(tmp_path / "att", png, "png", cache=cache, on_drop=lambda _r: None)
        assert result is not None
        on_disk = (tmp_path / "att" / result.rel_path).read_bytes()
        # write_image writes exactly what the optimizer chose (keep-smaller).
        assert on_disk == _optimize_png_lossless(png)
        assert len(on_disk) <= len(png)

    def test_jpeg_under_cap_written_verbatim(self, tmp_path: Path) -> None:
        """JPEG pass-through stays byte-verbatim — re-encoding it would be lossy (S42)."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        img = Image.new("RGB", (64, 48), color=(200, 100, 50))
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        jpg = buf.getvalue()
        result = write_image(tmp_path / "att", jpg, "jpg", cache={}, on_drop=lambda _r: None)
        assert result is not None
        on_disk = (tmp_path / "att" / result.rel_path).read_bytes()
        assert on_disk == jpg


class TestWriteImageResize:
    """#95: > 4k longest-edge inputs are resized to 4096 px before encode."""

    def test_in_spec_png_is_reoptimized_not_resized(self, tmp_path: Path) -> None:
        """3000×2000 PNG is under the cap: re-optimized losslessly, dimensions kept (S42)."""
        import io as _io

        from PIL import Image, ImageChops

        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
            write_image,
        )

        img = Image.new("RGB", (3000, 2000), color=(0, 200, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        result = write_image(
            tmp_path / "att",
            png_bytes,
            "png",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        on_disk = (tmp_path / "att" / result.rel_path).read_bytes()
        assert on_disk == _optimize_png_lossless(png_bytes)
        out = Image.open(_io.BytesIO(on_disk))
        assert out.size == (3000, 2000)  # under the cap → not resized
        # Lossless: decoded pixels identical to the source.
        src = Image.open(_io.BytesIO(png_bytes)).convert("RGBA")
        assert ImageChops.difference(src, out.convert("RGBA")).getbbox() is None

    def test_oversize_png_is_resized(self, tmp_path: Path) -> None:
        """5000×3000 PNG → longest edge 4096, re-encoded."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        img = Image.new("RGB", (5000, 3000), color=(255, 0, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        result = write_image(
            tmp_path / "att",
            buf.getvalue(),
            "png",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        out = Image.open(tmp_path / "att" / result.rel_path)
        assert max(out.size) == 4096
        # The 5000:3000 ratio is preserved → 4096:2457.6 → (4096, 2457)
        assert out.size == (4096, 2457)


class TestWriteImageWmfRasterize:
    """#96: WMF/EMF blobs rasterize to PNG, or drop cleanly when no backend."""

    def test_rasterizer_success_writes_png(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a backend returns PNG bytes, we write them and report .png."""
        import io as _io

        from PIL import Image

        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        # Stub PNG payload — a real 16×16 image, valid for the resize probe.
        img = Image.new("RGB", (16, 16), color=(123, 45, 67))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        png_payload = buf.getvalue()

        def _stub_ok(_blob: bytes, _fmt: str) -> bytes:
            return png_payload

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _stub_ok)

        result = write_image(
            tmp_path / "att",
            b"<<fake wmf bytes>>",
            "wmf",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".png"
        on_disk = (tmp_path / "att" / result.rel_path).read_bytes()
        assert on_disk == png_payload

    def test_no_rasterizer_drops_with_wmf_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        def _stub_none(_blob: bytes, _fmt: str) -> bytes | None:
            return None

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _stub_none)
        dropped: list[str] = []
        result = write_image(
            tmp_path / "att",
            b"<<fake wmf bytes>>",
            "wmf",
            cache={},
            on_drop=dropped.append,
        )
        assert result is None
        assert dropped == ["WMF"]

    def test_emf_also_supported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import io as _io

        from PIL import Image

        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        img = Image.new("RGB", (4, 4), color=(0, 0, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        png_payload = buf.getvalue()

        def _stub_ok(_blob: bytes, _fmt: str) -> bytes:
            return png_payload

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _stub_ok)
        result = write_image(
            tmp_path / "att",
            b"<<fake emf>>",
            "emf",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".png"

    def test_wmf_rasterize_skipped_when_no_backend(self, tmp_path: Path) -> None:
        """Live test: skip when neither LibreOffice nor wmf2svg is on PATH."""
        import shutil

        from mdd.convert.images import (
            _rasterize_to_png,  # pyright: ignore[reportPrivateUsage]
        )

        have_soffice = shutil.which("soffice") or shutil.which("libreoffice")
        have_wmf2svg = shutil.which("wmf2svg") and shutil.which("rsvg-convert")
        if not have_soffice and not have_wmf2svg:
            pytest.skip("no WMF rasterizer available (LibreOffice / wmf2svg)")
        # We don't ship a real WMF fixture in this commit, but exercising
        # the helper with garbage bytes must still return None (clean
        # rasterizer failure), not raise.
        out = _rasterize_to_png(b"not really wmf bytes", "wmf")
        assert out is None or isinstance(out, bytes)


class TestWriteImageUnknownFormats:
    """Unknown formats: on_drop is invoked, None is returned, no file written."""

    def test_unknown_format_returns_none(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        dropped: list[str] = []
        result = write_image(
            tmp_path / "att",
            b"<<not really an mpo>>",
            "mpo",
            cache={},
            on_drop=dropped.append,
        )
        assert result is None
        assert dropped == ["MPO"]
        assert not (tmp_path / "att").exists() or list((tmp_path / "att").iterdir()) == []

    def test_broken_tiff_drops(self, tmp_path: Path) -> None:
        """A truly-invalid TIFF blob falls into the drop path, not a crash."""
        from mdd.convert.images import write_image

        dropped: list[str] = []
        result = write_image(
            tmp_path / "att",
            b"fakeTIFFbytes",
            "tiff",
            cache={},
            on_drop=dropped.append,
        )
        assert result is None
        assert dropped == ["TIFF"]


def _tiff_blob(colour: tuple[int, int, int] = (128, 64, 200)) -> bytes:
    """Build a deterministic TIFF blob from a 32×32 solid-colour image."""
    import io as _io

    from PIL import Image

    img = Image.new("RGB", (32, 32), color=colour)
    buf = _io.BytesIO()
    img.save(buf, format="TIFF")
    return buf.getvalue()


class TestWriteImageTiffTranscode:
    """#94: TIFF blobs transcode to JPEG with pinned, deterministic encoder flags."""

    def test_tiff_written_as_jpg(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        result = write_image(
            tmp_path / "att",
            _tiff_blob(),
            "tiff",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".jpg"
        # The written file is a JPEG, not the original TIFF.
        data = (tmp_path / "att" / result.rel_path).read_bytes()
        assert data[:3] == b"\xff\xd8\xff"

    def test_two_runs_produce_byte_identical_jpegs(self, tmp_path: Path) -> None:
        """The whole reason the encoder flags are pinned."""
        from mdd.convert.images import write_image

        tiff = _tiff_blob()
        r1 = write_image(
            tmp_path / "a",
            tiff,
            "tiff",
            cache={},
            on_drop=lambda _r: None,
        )
        r2 = write_image(
            tmp_path / "b",
            tiff,
            "tiff",
            cache={},
            on_drop=lambda _r: None,
        )
        assert r1 is not None
        assert r2 is not None
        a_bytes = (tmp_path / "a" / r1.rel_path).read_bytes()
        b_bytes = (tmp_path / "b" / r2.rel_path).read_bytes()
        assert a_bytes == b_bytes

    def test_tiff_dedup_cache_hit(self, tmp_path: Path) -> None:
        """Repeat TIFF input within a conversion does not re-encode."""
        from mdd.convert.images import write_image

        cache: dict[str, Path] = {}
        tiff = _tiff_blob()
        r1 = write_image(
            tmp_path / "att",
            tiff,
            "tiff",
            cache=cache,
            on_drop=lambda _r: None,
        )
        r2 = write_image(
            tmp_path / "att",
            tiff,
            "tiff",
            cache=cache,
            on_drop=lambda _r: None,
        )
        assert r1 is not None
        assert r2 is not None
        assert r1.rel_path == r2.rel_path
        assert r2.dedup_hit
        assert len(list((tmp_path / "att").iterdir())) == 1

    def test_oversize_tiff_resized_before_encode(self, tmp_path: Path) -> None:
        """5000×3000 TIFF → JPEG with longest edge 4096 px."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        img = Image.new("RGB", (5000, 3000), color=(10, 20, 30))
        buf = _io.BytesIO()
        img.save(buf, format="TIFF")
        result = write_image(
            tmp_path / "att",
            buf.getvalue(),
            "tiff",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        out = Image.open(tmp_path / "att" / result.rel_path)
        assert max(out.size) == 4096
        # Aspect ratio preserved.
        assert out.size[1] < out.size[0]

    def test_palette_mode_tiff_converts_via_rgb(self, tmp_path: Path) -> None:
        """Non-RGB/L modes (e.g. P, RGBA) must be coerced to RGB before JPEG."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        # Build a palette-mode TIFF — JPEG cannot encode this directly.
        img = Image.new("P", (16, 16), color=3)
        buf = _io.BytesIO()
        img.save(buf, format="TIFF")
        result = write_image(
            tmp_path / "att",
            buf.getvalue(),
            "tiff",
            cache={},
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".jpg"


def _gradient_png(compress_level: int) -> bytes:
    """A 256×256 gradient PNG saved at *compress_level* (0 = uncompressed)."""
    import io as _io

    from PIL import Image

    img = Image.linear_gradient("L")  # deterministic 256×256 grayscale ramp
    buf = _io.BytesIO()
    img.save(buf, format="PNG", compress_level=compress_level)
    return buf.getvalue()


class TestOptimizePngLossless:
    """S42: lossless PNG re-optimization that keeps the smaller of the two."""

    def test_shrinks_an_uncompressed_png(self) -> None:
        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
        )

        big = _gradient_png(compress_level=0)
        opt = _optimize_png_lossless(big)
        assert len(opt) < len(big)

    def test_is_lossless(self) -> None:
        import io as _io

        from PIL import Image, ImageChops

        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
        )

        big = _gradient_png(compress_level=0)
        opt = _optimize_png_lossless(big)
        a = Image.open(_io.BytesIO(big)).convert("RGBA")
        b = Image.open(_io.BytesIO(opt)).convert("RGBA")
        assert ImageChops.difference(a, b).getbbox() is None

    def test_never_inflates_already_optimal(self) -> None:
        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
        )

        small = _gradient_png(compress_level=9)
        opt = _optimize_png_lossless(small)
        assert len(opt) <= len(small)

    def test_deterministic(self) -> None:
        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
        )

        big = _gradient_png(compress_level=0)
        assert _optimize_png_lossless(big) == _optimize_png_lossless(big)

    def test_garbage_returns_input_unchanged(self) -> None:
        """A non-decodable blob must come back untouched, not raise."""
        from mdd.convert.images import (
            _optimize_png_lossless,  # pyright: ignore[reportPrivateUsage]
        )

        junk = b"not a real png at all"
        assert _optimize_png_lossless(junk) == junk
