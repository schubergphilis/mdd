"""images.py — content-addressed image writer shared by pptx/docx converters.

A deterministic image-extraction pipeline for office document converters.
Same blob → same `rel_path`, every run, every Pillow version (later
issues plug TIFF transcode / resize / WMF rasterize into the per-format
branches here; this commit lays the foundation: content-address by
``sha1(blob)[:16]`` and pass-through write).

Behaviour contract:

- ``write_image`` is the single entry point for converter code.
- Caller passes a per-conversion ``cache: dict[str, Path]`` keyed on
  ``sha1(blob)[:16]``; the second call with the same blob skips disk
  I/O and returns the cached path with ``dedup_hit=True``.
- Unknown / unrecognised formats: call ``on_drop(reason)`` and return
  ``None``. Never raise; the deck must survive a single bad image.

Future issues will extend the per-format pipeline (TIFF→JPEG,
WMF→PNG, >4k resize) but the shape of ``write_image`` is stable.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


# Formats we pass through unchanged (lowercased extension == lowercased format,
# with 'jpeg' normalised to 'jpg').
_PASS_THROUGH_FORMATS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "gif"})

# Formats we transcode to JPEG (lossy, deterministic flags).
_TRANSCODE_TO_JPEG_FORMATS: frozenset[str] = frozenset({"tiff", "tif"})

# Formats we rasterize to PNG via an external tool (LibreOffice / wmf2svg).
# PNG is the right target — WMFs are usually line art / clipart where
# JPEG would introduce ringing on sharp edges.
_RASTERIZE_TO_PNG_FORMATS: frozenset[str] = frozenset({"wmf", "emf"})

# DPI for vector → raster conversion (LibreOffice ignores DPI for WMF →
# PNG but uses it for SVG → PNG via the rsvg-convert fallback).
_RASTERIZE_DPI = 150

# Pinned JPEG encoder flags. Reviewers: do not "improve" these without
# re-baselining the byte-compare tests; they exist to keep dedup
# survivable across Pillow versions.
_JPEG_ENCODE_KWARGS: dict[str, object] = {
    "quality": 85,
    "optimize": True,
    "progressive": False,
}

# Pinned PNG encoder flags. Same reasoning as JPEG — output must be
# deterministic across runs / Pillow versions for dedup to hold.
_PNG_ENCODE_KWARGS: dict[str, object] = {"optimize": True}

# Longest-edge cap before encoding. Above this we resize with LANCZOS.
# Markdown viewers don't benefit from above-4k; it's just bloat. See P03 #95.
_MAX_LONGEST_EDGE = 4096


@dataclass(frozen=True)
class ImageWriteResult:
    """Outcome of writing a single image blob.

    ``rel_path`` is relative to the converter's attachments directory;
    callers turn this into a markdown link by joining with the dir name.
    ``dedup_hit`` is ``True`` if the blob had already been written
    earlier in this conversion (and the same file was reused).
    """

    rel_path: Path
    dedup_hit: bool


def _content_hash(blob: bytes) -> str:
    """16 hex chars of the blob's SHA1 — content identity for dedup."""
    return hashlib.sha1(blob, usedforsecurity=False).hexdigest()[:16]


def _normalise_format(declared_format: str) -> str:
    """Lowercased canonical format string; 'jpeg' kept as 'jpeg' (callers map ext)."""
    return declared_format.strip().lower()


def _pass_through_ext(fmt: str) -> str:
    """Map a passed-through declared format to its on-disk extension."""
    return "jpg" if fmt == "jpeg" else fmt


def _maybe_resize(img: Any) -> Any:  # pyright: ignore[reportAny]
    """Resize *img* if its longest edge exceeds the cap; otherwise return as-is.

    Aspect ratio is preserved; LANCZOS resampling. Callers should treat
    the return value as the canonical image to encode.
    """
    # lazy: Pillow ~1.2s cold-import; load only when we actually need to resize
    from PIL import Image  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

    longest = max(img.size)  # pyright: ignore[reportAny]
    if longest <= _MAX_LONGEST_EDGE:
        return img
    ratio = _MAX_LONGEST_EDGE / longest
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))  # pyright: ignore[reportAny]
    return img.resize(new_size, Image.Resampling.LANCZOS)  # pyright: ignore[reportAny]


def _coerce_jpeg_mode(img: Any) -> Any:  # pyright: ignore[reportAny]
    """JPEG can only encode RGB/L. Coerce non-RGB/L inputs to RGB."""
    if img.mode not in {"RGB", "L"}:  # pyright: ignore[reportAny]
        return img.convert("RGB")  # pyright: ignore[reportAny]
    return img


def _encode_tiff_to_jpeg(blob: bytes) -> bytes:
    """Decode *blob* as TIFF, optional resize, encode as JPEG.

    Order matters: resize *before* encode so we don't run already-encoded
    JPEGs through Pillow a second time (which would defeat dedup).
    Mode-coerces non-RGB/L inputs to RGB after resize since JPEG needs it.
    Raises any Pillow decode error to the caller.
    """
    # lazy: Pillow ~1.2s cold-import; load only when we actually transcode TIFF
    from PIL import Image  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

    with Image.open(io.BytesIO(blob)) as img:
        img = _maybe_resize(img)
        img = _coerce_jpeg_mode(img)
        out = io.BytesIO()
        img.save(out, format="JPEG", **_JPEG_ENCODE_KWARGS)  # pyright: ignore[reportAny]
        return out.getvalue()


def _probe_size(blob: bytes) -> tuple[int, int] | None:
    """Return (width, height) for *blob* without fully decoding, or None on failure."""
    # lazy: Pillow ~1.2s cold-import; load only when we actually probe image dims
    from PIL import (  # pyright: ignore[reportMissingImports]  # noqa: PLC0415
        Image,
        UnidentifiedImageError,
    )

    try:
        with Image.open(io.BytesIO(blob)) as img:
            return img.size  # pyright: ignore[reportAny, reportReturnType]
    except OSError, ValueError, UnidentifiedImageError:
        return None


def _resize_passthrough(blob: bytes, pillow_format: str) -> bytes:
    """Decode → resize → re-encode in the SAME format (for oversize PNG/JPG/GIF)."""
    # lazy: Pillow ~1.2s cold-import; load only when we actually resize oversize images
    from PIL import Image  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

    with Image.open(io.BytesIO(blob)) as img:
        img = _maybe_resize(img)
        out = io.BytesIO()
        if pillow_format == "JPEG":
            img = _coerce_jpeg_mode(img)
            img.save(out, format="JPEG", **_JPEG_ENCODE_KWARGS)  # pyright: ignore[reportAny]
        elif pillow_format == "PNG":
            img.save(out, format="PNG", **_PNG_ENCODE_KWARGS)  # pyright: ignore[reportAny]
        else:
            # GIF and the rare other pass-through formats: trust Pillow defaults.
            img.save(out, format=pillow_format)  # pyright: ignore[reportAny]
        return out.getvalue()


def _reencode_png(blob: bytes) -> bytes:
    """Re-encode *blob* as PNG with the pinned, deterministic encoder flags.

    No resize, no mode change — PNG is lossless, so the decoded pixels are
    preserved exactly. Raises any Pillow decode error to the caller.
    """
    # lazy: Pillow ~1.2s cold-import; load only when we actually re-encode a PNG
    from PIL import Image  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

    with Image.open(io.BytesIO(blob)) as img:
        out = io.BytesIO()
        img.save(out, format="PNG", **_PNG_ENCODE_KWARGS)  # pyright: ignore[reportAny]
        return out.getvalue()


def _optimize_png_lossless(blob: bytes) -> bytes:
    """Losslessly re-optimize a PNG, returning the smaller of {original, re-encoded}.

    Office-extracted PNGs are frequently stored with sub-optimal compression;
    re-encoding with ``optimize=True`` recovers bytes at zero quality cost
    (PNG is lossless). Some already-optimal PNGs grow under re-encode, so we
    keep whichever is smaller and never inflate. Any decode/encode failure
    returns the original blob unchanged — optimization must never lose the
    picture.
    """
    try:
        reencoded = _reencode_png(blob)
    except OSError, ValueError:
        return blob
    return reencoded if len(reencoded) < len(blob) else blob


def _rasterize_with_libreoffice(blob: bytes, fmt: str) -> bytes | None:
    """Convert WMF/EMF blob to PNG bytes via LibreOffice. None if unavailable.

    Spawns ``soffice --headless --convert-to png``; the result file is
    read and returned. Any non-zero exit / missing output / timeout
    returns None so the caller can fall back.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / f"in.{fmt}"
        src.write_bytes(blob)
        try:
            proc = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "png",
                    "--outdir",
                    tmpdir,
                    str(src),
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        out = Path(tmpdir) / "in.png"
        if not out.is_file():
            return None
        return out.read_bytes()


def _rasterize_wmf_via_wmf2svg(blob: bytes) -> bytes | None:
    """Convert WMF bytes to PNG via ``wmf2svg`` + ``rsvg-convert``. None if unavailable."""
    wmf2svg = shutil.which("wmf2svg")
    rsvg = shutil.which("rsvg-convert")
    if wmf2svg is None or rsvg is None:
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "in.wmf"
        src.write_bytes(blob)
        svg = Path(tmpdir) / "in.svg"
        try:
            proc = subprocess.run(
                [wmf2svg, "-o", str(svg), str(src)],
                capture_output=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0 or not svg.is_file():
                return None
            png_out = subprocess.run(
                [rsvg, "--dpi-x", str(_RASTERIZE_DPI), "--dpi-y", str(_RASTERIZE_DPI), str(svg)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            return None
        if png_out.returncode != 0:
            return None
        return png_out.stdout


def _rasterize_to_png(blob: bytes, fmt: str) -> bytes | None:
    """Rasterize a WMF/EMF blob to PNG via the first available backend.

    Tries LibreOffice (handles both WMF and EMF), then wmf2svg+rsvg
    (WMF only). Returns None when no backend is available or every
    backend fails — callers should drop the image and log once.
    """
    out = _rasterize_with_libreoffice(blob, fmt)
    if out is not None:
        return out
    if fmt == "wmf":
        return _rasterize_wmf_via_wmf2svg(blob)
    return None


def _resize_png(blob: bytes) -> bytes:
    """Apply the > 4k resize cap to a freshly-rasterized PNG."""
    size = _probe_size(blob)
    if size is None or max(size) <= _MAX_LONGEST_EDGE:
        return blob
    return _resize_passthrough(blob, "PNG")


def _write_blob(
    attachments_dir: Path,
    blob: bytes,
    ext: str,
    cache: dict[str, Path],
) -> ImageWriteResult:
    """Content-addressed write; idempotent on the same conversion + filesystem."""
    digest = _content_hash(blob)
    cached = cache.get(digest)
    if cached is not None:
        return ImageWriteResult(rel_path=cached, dedup_hit=True)

    filename = f"image_{digest}.{ext}"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    dest = attachments_dir / filename
    if not dest.exists():
        dest.write_bytes(blob)

    rel = Path(filename)
    cache[digest] = rel
    return ImageWriteResult(rel_path=rel, dedup_hit=False)


_PASS_THROUGH_PILLOW_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "gif": "GIF",
}


def _pass_through_or_resize(
    attachments_dir: Path,
    blob: bytes,
    fmt: str,
    cache: dict[str, Path],
    on_drop: Callable[[str], None],
) -> ImageWriteResult | None:
    """Write an in-bounds image, resizing only when it exceeds the 4k cap.

    JPG/GIF under the cap are written verbatim — re-encoding them risks
    byte drift that breaks cross-deck git dedup (and a JPEG re-encode is
    lossy). PNGs under the cap are losslessly re-optimized (keep-smaller,
    see :func:`_optimize_png_lossless`); the result is deterministic, so
    dedup still holds at a smaller byte baseline. Oversize sources of any
    format are resized + re-encoded.
    """
    ext = _pass_through_ext(fmt)
    size = _probe_size(blob)
    if size is None or max(size) <= _MAX_LONGEST_EDGE:
        if fmt == "png" and size is not None:
            blob = _optimize_png_lossless(blob)
        return _write_blob(attachments_dir, blob, ext, cache)

    # Cache check on the SOURCE blob — duplicate oversized inputs skip
    # the decode + resize + encode work the second time around.
    digest = _content_hash(blob)
    cached = cache.get(digest)
    if cached is not None:
        return ImageWriteResult(rel_path=cached, dedup_hit=True)
    try:
        resized = _resize_passthrough(blob, _PASS_THROUGH_PILLOW_FORMAT[fmt])
    except OSError, ValueError:
        on_drop(fmt.upper())
        return None
    result = _write_blob(attachments_dir, resized, ext, cache={})
    cache[digest] = result.rel_path
    return result


def _convert_then_write(
    attachments_dir: Path,
    blob: bytes,
    out_ext: str,
    cache: dict[str, Path],
    convert: Callable[[bytes], bytes | None],
) -> ImageWriteResult | None:
    """Source-blob-cached convert + write: ``convert(blob)`` → file.

    Returns ``None`` when *convert* returns ``None`` (the caller is
    responsible for calling ``on_drop`` with an appropriate reason).
    Returns a fresh write result otherwise. The cache key is the
    *source* blob so duplicate references inside a conversion skip
    the convert + write work.
    """
    digest = _content_hash(blob)
    cached = cache.get(digest)
    if cached is not None:
        return ImageWriteResult(rel_path=cached, dedup_hit=True)
    converted = convert(blob)
    if converted is None:
        return None
    result = _write_blob(attachments_dir, converted, out_ext, cache={})
    cache[digest] = result.rel_path
    return result


def _convert_tiff(blob: bytes) -> bytes | None:
    """TIFF → JPEG; returns None on decode failure (caller drops)."""
    try:
        return _encode_tiff_to_jpeg(blob)
    except OSError, ValueError:
        return None


def _convert_wmf_or_emf(blob: bytes, fmt: str) -> bytes | None:
    """WMF/EMF → PNG with the 4k cap applied; returns None on rasterize failure."""
    rasterized = _rasterize_to_png(blob, fmt)
    if rasterized is None:
        return None
    return _resize_png(rasterized)


def write_image(
    attachments_dir: Path,
    blob: bytes,
    declared_format: str,
    *,
    cache: dict[str, Path],
    on_drop: Callable[[str], None],
) -> ImageWriteResult | None:
    """Write *blob* into *attachments_dir* (content-addressed) or skip.

    Returns ``None`` for unknown formats (after calling ``on_drop``).
    Returns an :class:`ImageWriteResult` with ``rel_path`` relative to
    ``attachments_dir`` on success — the second call with the same
    blob hits the cache and skips disk I/O.

    Per-format pipeline:

    - PNG/JPG/GIF: pass through verbatim if under the 4k cap;
      otherwise decode, resize, re-encode with pinned flags.
    - TIFF: transcode to JPEG with pinned flags
      (``quality=85, optimize=True, progressive=False``). Same TIFF
      bytes in → byte-identical JPEG out every run.
    - WMF/EMF: rasterize to PNG via LibreOffice (preferred) or the
      ``wmf2svg``+``rsvg-convert`` fallback. No backend on PATH →
      drop with reason. PNG output is also subject to the 4k cap.
    - Anything else: drop with ``on_drop(declared_format.upper())``.

    The cache is keyed on the SOURCE blob so duplicate references
    inside a conversion always skip decode + encode work even when
    the on-disk format differs.
    """
    fmt = _normalise_format(declared_format)

    if fmt in _PASS_THROUGH_FORMATS:
        return _pass_through_or_resize(attachments_dir, blob, fmt, cache, on_drop)

    if fmt in _TRANSCODE_TO_JPEG_FORMATS:
        result = _convert_then_write(attachments_dir, blob, "jpg", cache, _convert_tiff)
        if result is None:
            on_drop("TIFF")
        return result

    if fmt in _RASTERIZE_TO_PNG_FORMATS:
        result = _convert_then_write(
            attachments_dir,
            blob,
            "png",
            cache,
            lambda b: _convert_wmf_or_emf(b, fmt),
        )
        if result is None:
            on_drop(fmt.upper())
        return result

    on_drop(declared_format.upper())
    return None
