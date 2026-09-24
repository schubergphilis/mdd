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
- The blob's *actual* format decides the pipeline, not the format the
  container declared for it. Every blob is identified from its header
  first; a blob that no supported decoder recognises is dropped, never
  written under an image extension.
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

from mdd.utils.safe_write import atomic_write_bytes, mkdir_no_symlink

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
# Markdown viewers don't benefit from above-4k; it's just bloat.
_MAX_LONGEST_EDGE = 4096

# The only Pillow decoders a blob may be identified with. Passing this
# allow-list to every ``Image.open`` keeps the remaining registered
# plugins (EPS via Ghostscript, PSD, ...) out of the pipeline entirely.
_SNIFF_FORMATS: list[str] = ["PNG", "JPEG", "GIF", "TIFF", "BMP"]

# Pillow format name per effective format, for the ``formats=`` allow-list.
_PILLOW_FORMAT: dict[str, str] = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "gif": "GIF",
    "tiff": "TIFF",
    "tif": "TIFF",
    "bmp": "BMP",
}

# Windows metafile signatures. Pillow does not decode these, so they are
# recognised by hand before the external rasteriser is invoked.
_WMF_PLACEABLE_MAGIC = b"\xd7\xcd\xc6\x9a"
_WMF_HEADER_MAGICS: tuple[bytes, ...] = (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00")
_EMF_HEADER_RECORD_TYPE = b"\x01\x00\x00\x00"
_EMF_SIGNATURE = b" EMF"
_EMF_SIGNATURE_OFFSET = 40

# Pillow reports a multi-picture JPEG (MPO) under its own format name, but
# the bytes are a plain JPEG stream and are handled as one.
_SNIFF_ALIASES: dict[str, str] = {"mpo": "jpeg"}


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

    with Image.open(io.BytesIO(blob), formats=["TIFF"]) as img:
        img = _maybe_resize(img)
        img = _coerce_jpeg_mode(img)
        out = io.BytesIO()
        img.save(out, format="JPEG", **_JPEG_ENCODE_KWARGS)  # pyright: ignore[reportAny]
        return out.getvalue()


def _probe_size(blob: bytes, pillow_format: str) -> tuple[int, int] | None:
    """Return (width, height) for *blob* without fully decoding, or None on failure.

    Only the *pillow_format* decoder is consulted.
    """
    # lazy: Pillow ~1.2s cold-import; load only when we actually probe image dims
    from PIL import (  # pyright: ignore[reportMissingImports]  # noqa: PLC0415
        Image,
        UnidentifiedImageError,
    )

    try:
        with Image.open(io.BytesIO(blob), formats=[pillow_format]) as img:
            return img.size  # pyright: ignore[reportAny, reportReturnType]
    except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
        return None


def _sniff_format(blob: bytes) -> str | None:
    """Identify *blob* from its header using only the supported decoders.

    Returns the lowercased Pillow format name (``png``, ``jpeg``, ``gif``,
    ``tiff``, ``bmp``) or ``None`` when none of them recognises the blob.
    Only the header is parsed; pixel data is not decoded. A header whose
    declared pixel count exceeds Pillow's decompression-bomb limit is
    treated as unidentified.
    """
    # lazy: Pillow ~1.2s cold-import; load only when we actually identify a blob
    from PIL import (  # pyright: ignore[reportMissingImports]  # noqa: PLC0415
        Image,
        UnidentifiedImageError,
    )

    try:
        with Image.open(io.BytesIO(blob), formats=_SNIFF_FORMATS) as img:
            detected: str | None = img.format  # pyright: ignore[reportAny]
    except OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError:
        return None
    if not detected:
        return None
    lowered = detected.lower()
    return _SNIFF_ALIASES.get(lowered, lowered)


def _sniff_metafile_format(blob: bytes) -> str | None:
    """Return ``"wmf"`` / ``"emf"`` when *blob* carries that signature, else None.

    EMF requires both the EMR_HEADER record type at offset 0 and the
    ``" EMF"`` signature at offset 40, so a foreign file that merely has
    those four bytes at offset 40 is not accepted.
    """
    if blob.startswith(_WMF_PLACEABLE_MAGIC) or blob.startswith(_WMF_HEADER_MAGICS):
        return "wmf"
    end = _EMF_SIGNATURE_OFFSET + len(_EMF_SIGNATURE)
    if (
        blob.startswith(_EMF_HEADER_RECORD_TYPE)
        and blob[_EMF_SIGNATURE_OFFSET:end] == _EMF_SIGNATURE
    ):
        return "emf"
    return None


def _effective_format(blob: bytes, declared: str) -> str | None:
    """Decide which pipeline *blob* takes from its bytes, not from *declared*.

    Raster blobs are identified by header. Metafiles (which Pillow does not
    read) are only accepted when the container declared them as WMF/EMF
    *and* the bytes carry a metafile signature. Anything else is ``None``.
    """
    sniffed = _sniff_format(blob)
    if sniffed is not None:
        return sniffed
    if declared in _RASTERIZE_TO_PNG_FORMATS:
        return _sniff_metafile_format(blob)
    return None


def _resize_passthrough(blob: bytes, pillow_format: str) -> bytes:
    """Decode → resize → re-encode in the SAME format (for oversize PNG/JPG/GIF)."""
    # lazy: Pillow ~1.2s cold-import; load only when we actually resize oversize images
    from PIL import Image  # pyright: ignore[reportMissingImports]  # noqa: PLC0415

    with Image.open(io.BytesIO(blob), formats=[pillow_format]) as img:
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

    with Image.open(io.BytesIO(blob), formats=["PNG"]) as img:
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
    size = _probe_size(blob, "PNG")
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
    mkdir_no_symlink(attachments_dir)
    dest = attachments_dir / filename
    if not dest.exists():
        atomic_write_bytes(dest, blob)

    rel = Path(filename)
    cache[digest] = rel
    return ImageWriteResult(rel_path=rel, dedup_hit=False)


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
    pillow_format = _PILLOW_FORMAT[fmt]
    size = _probe_size(blob, pillow_format)
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
        resized = _resize_passthrough(blob, pillow_format)
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

    *declared_format* is what the container claims the blob is. The
    pipeline is chosen by the format the bytes actually have (see
    :func:`_effective_format`); the declared format only matters for
    WMF/EMF, which Pillow cannot identify. A JPEG declared as PNG is
    therefore written as ``.jpg``, and a blob no supported decoder
    recognises is dropped rather than written under an image extension.

    Per-format pipeline:

    - PNG/JPG/GIF: pass through verbatim if under the 4k cap;
      otherwise decode, resize, re-encode with pinned flags.
    - TIFF: transcode to JPEG with pinned flags
      (``quality=85, optimize=True, progressive=False``). Same TIFF
      bytes in → byte-identical JPEG out every run.
    - WMF/EMF: rasterize to PNG via LibreOffice (preferred) or the
      ``wmf2svg``+``rsvg-convert`` fallback. No backend on PATH →
      drop with reason. PNG output is also subject to the 4k cap.
    - Anything else: drop with ``on_drop(<format>.upper())``, where the
      reason is the identified format, or the declared one when the
      blob could not be identified at all.

    The cache is keyed on the SOURCE blob so duplicate references
    inside a conversion always skip decode + encode work even when
    the on-disk format differs.
    """
    declared = _normalise_format(declared_format)
    fmt = _effective_format(blob, declared)
    if fmt is None:
        on_drop(declared_format.upper())
        return None

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

    on_drop(fmt.upper())
    return None
