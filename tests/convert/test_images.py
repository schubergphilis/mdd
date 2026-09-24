"""Tests for the shared content-addressed image writer.

Covers the content-addressed dedup + pass-through write contract, TIFF
transcode, >4k resize, and WMF rasterize.
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


def _jpeg_blob(size: tuple[int, int] = (64, 48)) -> bytes:
    """A real JPEG blob (solid colour) for format-identification tests."""
    import io as _io

    from PIL import Image

    img = Image.new("RGB", size, color=(200, 100, 50))
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# Placeable WMF header followed by filler; enough for signature detection.
_FAKE_WMF = b"\xd7\xcd\xc6\x9a" + b"\x00" * 60
# EMF: EMR_HEADER record type, then the " EMF" signature at byte offset 40.
_FAKE_EMF = b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"\x00" * 40


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

        cache: dict[str, Path] = {}
        result = write_image(
            tmp_path / "att",
            _jpeg_blob(),
            "jpeg",
            cache=cache,
            on_drop=lambda _r: None,
        )
        assert result is not None
        assert result.rel_path.suffix == ".jpg"

    def test_jpeg_declared_as_png_is_written_as_jpg(self, tmp_path: Path) -> None:
        """The bytes decide the extension, not the format the container declared."""
        from mdd.convert.images import write_image

        dropped: list[str] = []
        jpg = _jpeg_blob()
        result = write_image(tmp_path / "att", jpg, "png", cache={}, on_drop=dropped.append)
        assert result is not None
        assert result.rel_path.suffix == ".jpg"
        assert (tmp_path / "att" / result.rel_path).read_bytes() == jpg
        assert dropped == []

    def test_png_declared_as_jpeg_is_written_as_png(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        result = write_image(
            tmp_path / "att", _minimal_png(), "jpeg", cache={}, on_drop=lambda _r: None
        )
        assert result is not None
        assert result.rel_path.suffix == ".png"


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
        """In-bounds PNGs are re-optimized (keep-smaller), not written verbatim."""
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
        """JPEG pass-through stays byte-verbatim — re-encoding it would be lossy."""
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
    """> 4k longest-edge inputs are resized to 4096 px before encode."""

    def test_in_spec_png_is_reoptimized_not_resized(self, tmp_path: Path) -> None:
        """3000×2000 PNG is under the cap: re-optimized losslessly, dimensions kept."""
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
    """WMF/EMF blobs rasterize to PNG, or drop cleanly when no backend."""

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
            _FAKE_WMF,
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
            _FAKE_WMF,
            "wmf",
            cache={},
            on_drop=dropped.append,
        )
        assert result is None
        assert dropped == ["WMF"]

    def test_wmf_without_metafile_signature_never_reaches_rasterizer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bytes declared WMF but lacking a WMF/EMF header are dropped up front."""
        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        def _boom(_blob: bytes, _fmt: str) -> bytes:
            raise AssertionError("rasterizer must not run for unidentified bytes")

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _boom)
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
        assert not (tmp_path / "att").exists()

    @pytest.mark.parametrize(
        "blob",
        [
            # PDF header with " EMF" planted at byte offset 40.
            b"%PDF-1.4\n%" + b"\x00" * 30 + b" EMF" + b"\x00" * 40,
            # Binary EPS header (C5 D0 D3 C6) with " EMF" planted at byte offset 40.
            b"\xc5\xd0\xd3\xc6" + b"\x00" * 36 + b" EMF" + b"%!PS-Adobe-3.0\n",
        ],
    )
    def test_emf_signature_alone_is_not_a_metafile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blob: bytes
    ) -> None:
        """A foreign file with " EMF" at offset 40 lacks the EMR_HEADER type and is dropped."""
        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        def _boom(_blob: bytes, _fmt: str) -> bytes:
            raise AssertionError("rasterizer must not run for a non-metafile")

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _boom)
        dropped: list[str] = []
        result = write_image(tmp_path / "att", blob, "emf", cache={}, on_drop=dropped.append)
        assert result is None
        assert dropped == ["EMF"]
        assert not (tmp_path / "att").exists()

    @pytest.mark.parametrize(
        ("blob", "declared", "expected_ext"),
        [
            (_FAKE_WMF, "wmf", "wmf"),
            (b"\x01\x00\x09\x00\x00\x03" + b"\x00" * 40, "wmf", "wmf"),
            (_FAKE_EMF, "emf", "emf"),
            # Declared/actual mismatch: the signature wins.
            (_FAKE_EMF, "wmf", "emf"),
        ],
    )
    def test_metafile_signature_reaches_libreoffice_backend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        blob: bytes,
        declared: str,
        expected_ext: str,
    ) -> None:
        """Real WMF/EMF headers still go to the external rasterizer (subprocess mocked)."""
        import io as _io
        import subprocess
        from pathlib import Path as _Path

        from PIL import Image

        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        img = Image.new("RGB", (8, 8), color=(1, 2, 3))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        png_payload = buf.getvalue()

        calls: list[list[str]] = []

        def _fake_which(name: str) -> str | None:
            return "/fake/bin/soffice" if name == "soffice" else None

        def _fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            calls.append(argv)
            outdir = _Path(argv[argv.index("--outdir") + 1])
            (outdir / "in.png").write_bytes(png_payload)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        monkeypatch.setattr(images_mod.shutil, "which", _fake_which)
        monkeypatch.setattr(images_mod.subprocess, "run", _fake_run)

        result = write_image(tmp_path / "att", blob, declared, cache={}, on_drop=lambda _r: None)
        assert result is not None
        assert result.rel_path.suffix == ".png"
        assert (tmp_path / "att" / result.rel_path).read_bytes() == png_payload
        assert len(calls) == 1
        assert calls[0][0] == "/fake/bin/soffice"
        assert calls[0][-1].endswith(f"in.{expected_ext}")

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
            _FAKE_EMF,
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


class TestWriteImageIdentifiesByContent:
    """The pipeline is chosen by what the bytes are, not by the declared format."""

    def test_postscript_declared_as_png_is_dropped_without_ghostscript(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An EPS body under a raster label must never reach the EPS decoder."""
        from PIL import EpsImagePlugin

        from mdd.convert.images import write_image

        def _no_ghostscript(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("Ghostscript must not be invoked")

        monkeypatch.setattr(EpsImagePlugin, "Ghostscript", _no_ghostscript)
        eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n0 0 10 10 rectfill\nshowpage\n"
        dropped: list[str] = []
        result = write_image(tmp_path / "att", eps, "png", cache={}, on_drop=dropped.append)
        assert result is None
        assert dropped == ["PNG"]
        assert not (tmp_path / "att").exists()

    def test_random_bytes_declared_as_tiff_are_dropped_and_not_written(
        self, tmp_path: Path
    ) -> None:
        import hashlib

        from mdd.convert.images import write_image

        # Deterministic high-entropy bytes with no recognisable image header.
        junk = b"".join(hashlib.sha256(bytes([i])).digest() for i in range(16))
        dropped: list[str] = []
        result = write_image(tmp_path / "att", junk, "tiff", cache={}, on_drop=dropped.append)
        assert result is None
        assert dropped == ["TIFF"]
        assert not (tmp_path / "att").exists()

    def test_tiff_declared_as_png_is_transcoded_to_jpg(self, tmp_path: Path) -> None:
        from mdd.convert.images import write_image

        result = write_image(
            tmp_path / "att", _tiff_blob(), "png", cache={}, on_drop=lambda _r: None
        )
        assert result is not None
        assert result.rel_path.suffix == ".jpg"
        data = (tmp_path / "att" / result.rel_path).read_bytes()
        assert data[:3] == b"\xff\xd8\xff"

    def test_bmp_is_identified_and_dropped_by_its_real_format(self, tmp_path: Path) -> None:
        """BMP is recognised (so it cannot masquerade as PNG) but not supported."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        buf = _io.BytesIO()
        Image.new("RGB", (4, 4), color=(9, 9, 9)).save(buf, format="BMP")
        dropped: list[str] = []
        result = write_image(
            tmp_path / "att", buf.getvalue(), "png", cache={}, on_drop=dropped.append
        )
        assert result is None
        assert dropped == ["BMP"]
        assert not (tmp_path / "att").exists()

    def test_metafile_signature_is_ignored_under_a_raster_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WMF bytes declared as PNG are dropped; the rasterizer is only for declared WMF/EMF."""
        from mdd.convert import images as images_mod
        from mdd.convert.images import write_image

        def _boom(_blob: bytes, _fmt: str) -> bytes:
            raise AssertionError("rasterizer must not run")

        monkeypatch.setattr(images_mod, "_rasterize_to_png", _boom)
        dropped: list[str] = []
        result = write_image(tmp_path / "att", _FAKE_WMF, "png", cache={}, on_drop=dropped.append)
        assert result is None
        assert dropped == ["PNG"]

    @pytest.mark.parametrize("declared", ["png", "tiff"])
    def test_header_over_pixel_limit_is_dropped_not_raised(
        self, tmp_path: Path, declared: str
    ) -> None:
        """A PNG header claiming 200000x200000 pixels is dropped; Pillow's limit stays on."""
        from PIL import Image

        from mdd.convert.images import write_image

        assert Image.MAX_IMAGE_PIXELS is not None
        bomb = _png_with_header(200_000, 200_000)
        dropped: list[str] = []
        result = write_image(tmp_path / "att", bomb, declared, cache={}, on_drop=dropped.append)
        assert result is None
        assert dropped == [declared.upper()]
        assert not (tmp_path / "att").exists()

    def test_multi_picture_jpeg_passes_through_as_jpg(self, tmp_path: Path) -> None:
        """An MPO (multi-picture JPEG) is a JPEG stream and is written verbatim as .jpg."""
        import io as _io

        from PIL import Image

        from mdd.convert.images import write_image

        first = Image.new("RGB", (8, 8), color=(1, 2, 3))
        second = Image.new("RGB", (8, 8), color=(4, 5, 6))
        buf = _io.BytesIO()
        first.save(buf, format="MPO", save_all=True, append_images=[second])
        mpo = buf.getvalue()
        dropped: list[str] = []
        result = write_image(tmp_path / "att", mpo, "jpeg", cache={}, on_drop=dropped.append)
        assert result is not None
        assert result.rel_path.suffix == ".jpg"
        assert (tmp_path / "att" / result.rel_path).read_bytes() == mpo
        assert dropped == []


def _png_with_header(width: int, height: int) -> bytes:
    """A syntactically valid PNG whose IHDR declares *width* x *height* pixels."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 4))
        + chunk(b"IEND", b"")
    )


def _tiff_blob(colour: tuple[int, int, int] = (128, 64, 200)) -> bytes:
    """Build a deterministic TIFF blob from a 32×32 solid-colour image."""
    import io as _io

    from PIL import Image

    img = Image.new("RGB", (32, 32), color=colour)
    buf = _io.BytesIO()
    img.save(buf, format="TIFF")
    return buf.getvalue()


class TestWriteImageTiffTranscode:
    """TIFF blobs transcode to JPEG with pinned, deterministic encoder flags."""

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
    """Lossless PNG re-optimization that keeps the smaller of the two."""

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
