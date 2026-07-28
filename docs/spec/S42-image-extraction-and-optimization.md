# 042 - Embedded image extraction and optimization

**Purpose:** Define how `mdd convert` extracts embedded images from office documents into a content-addressed attachments directory, and the per-format byte-optimization policy applied on write — including lossless PNG re-optimization that keeps whichever of the original/re-encoded bytes is smaller.

**Status:** Implemented (2026-05-29)

## Introduction

`src/mdd/convert/images.py` is the shared image writer used by the `.docx`
and `.pptx` converters (S03, S11) and, transitively, by `mdd sharepoint sync`
(S18). Its single entry point, `write_image`, takes an extracted image blob
plus its declared format and writes a content-addressed file
(`image_<sha1(written_bytes)[:16]>.<ext>`) into the document's attachments
directory, returning a relative path the markdown body links to.

The pipeline already applied a per-format policy that had never been captured
in a spec (it shipped incrementally under a plan):

- **PNG / JPG / GIF** ≤ 4096 px longest edge: written **verbatim**.
- **TIFF**: transcoded to JPEG with pinned, deterministic encoder flags.
- **WMF / EMF**: rasterized to PNG via LibreOffice (or `wmf2svg`+`rsvg-convert`).
- Any source whose longest edge exceeds **4096 px**: resized (LANCZOS) and
  re-encoded before writing.

This spec records that policy as the durable design record and adds one
behaviour: **in-bounds PNGs are now losslessly re-optimized on write**, rather
than passed through verbatim. A measurement of a ~9 GB SharePoint PNG corpus
showed office-extracted PNGs are frequently stored with sub-optimal
compression; re-encoding them losslessly recovers on the order of 10–15 %
of bytes at zero quality cost.

## Requirements

- In-bounds PNGs (≤ 4096 px longest edge) MUST be re-encoded with the pinned
  PNG flags (`optimize=True`) and the **smaller** of `{original, re-encoded}`
  bytes written. The operation MUST NOT ever produce a larger file than the
  input.
- PNG re-optimization MUST be **lossless**: the decoded pixels of the written
  file MUST be identical to the source. (PNG re-encoding is inherently
  lossless; this requirement forbids any future "optimization" that is not.)
- Any decode/encode failure MUST fall back to writing the original blob
  unchanged. Image optimization MUST NEVER lose or corrupt the picture.
- JPEG and GIF pass-through MUST remain **byte-verbatim**. mdd MUST NOT
  re-encode existing JPEGs (that is lossy and compounds generation loss) and
  MUST NOT re-encode GIFs (animation-unsafe).
- Output MUST be deterministic for a given Pillow/zlib version so that
  identical source blobs continue to content-address to the same file
  (cross-document git dedup).
- The optimization applies to the **office-conversion path only**. It MUST NOT
  be applied to Confluence attachments — see Design Approach.

## Design Approach

- A small helper `_optimize_png_lossless(blob) -> bytes` re-encodes the PNG via
  the existing pinned `_PNG_ENCODE_KWARGS` and returns the smaller of the two
  byte strings, falling back to the original on any `OSError`/`ValueError`. It
  is invoked from the under-cap pass-through branch of `_pass_through_or_resize`
  only when `fmt == "png"`.
- **Content-addressing is preserved.** The filename is the SHA1 of the *written*
  bytes, so two identical source PNGs still optimize deterministically to the
  same bytes and therefore the same filename — git dedup holds, just at a
  smaller byte baseline. The previous "verbatim pass-through" rationale (avoid
  byte drift that breaks dedup) is satisfied by determinism, not by skipping
  re-encode.
- **PNG-only, by design.** PNG re-encode is lossless. JPEG re-encode at a fixed
  quality is lossy and one-way (re-running degrades further); GIF re-encode
  risks animation loss. Both are deliberately excluded.
- **Why not Confluence.** Confluence attachments (S16) are mirrored from the
  server and tracked by SHA-256 in a per-page manifest: the pull path
  re-downloads when `manifest.sha256 != hash_file(local)` and the push path
  re-uploads on the same mismatch. Locally re-compressing a Confluence
  attachment would therefore either be clobbered on the next pull or
  re-uploaded to the server (mutating it and bumping page versions). The
  byte-exact mirror invariant makes in-pipeline optimization the wrong tool
  there. SharePoint sync (S18), by contrast, decides re-conversion from the
  office-source and markdown-text hashes — not attachment bytes — so a smaller
  PNG baseline is invisible to it.

## Implementation Notes

- Code: `src/mdd/convert/images.py` (`_optimize_png_lossless`, `_reencode_png`).
  Tests: `tests/convert/test_images.py`.
- The pre-existing tests that asserted verbatim PNG pass-through
  (`test_passthrough_writes_bytes_verbatim`,
  `test_in_spec_png_passes_through_unchanged`) are updated to assert
  pixel-identity and non-inflation instead of byte-identity, reflecting the new
  contract. JPEG/GIF byte-verbatim assertions are unchanged.
- **Determinism caveat.** As with the existing TIFF-transcode and >4k-resize
  paths, `optimize=True` output can differ across Pillow/zlib versions. A
  toolchain upgrade may change the bytes (hence the content-addressed
  filename), causing the file to be rewritten on the next conversion of that
  document. This is the same, accepted trade-off the pipeline already carries.
- **One-off backfill.** Existing mirrors hold PNGs written under the old
  verbatim policy. A standalone script applies `_optimize_png_lossless` to
  on-disk PNGs in place, keeping the smaller bytes and verifying losslessness,
  **without renaming** (so no markdown reference needs updating). The retained
  filename keeps its original content hash — a cosmetic mismatch that is
  invisible to SharePoint sync. The backfill is safe on SharePoint mirrors and
  any office-conversion output; it MUST NOT be run against Confluence mirror
  trees (see Design Approach).

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [S03 - convert command](S03-convert-command.md) — the `.docx` → markdown path that writes images
- [S11 - convert pptx](S11-convert-pptx.md) — the `.pptx` → markdown path; documents the attachments directory layout
- [S15 - Converter registry](S15-converter-registry.md) — how converters are dispatched
- [S18 - sharepoint sync command](S18-sharepoint-sync.md) — sync diff keys off office-source + md-text hashes, not attachment bytes
- [S16 - Confluence attachment conversion](S16-confluence-attachment-conversion.md) — the byte-exact, SHA-tracked attachment mirror this optimization is excluded from

## Open questions

1. Should the WMF/EMF → PNG rasterized output also be routed through
   `_optimize_png_lossless`? It is a small, line-art-heavy population, so the
   expected gain is low and it is left out for now.

## Out of scope

- Lossy JPEG re-encoding of existing JPEGs.
- PNG quantization, palette reduction, or screenshot-PNG → JPEG conversion
  (larger potential savings, but lossy or content-altering).
- Optimization of WMF/EMF rasterized PNG output (see Open questions).
- Optimization of Confluence attachments (byte-exact server mirror).
