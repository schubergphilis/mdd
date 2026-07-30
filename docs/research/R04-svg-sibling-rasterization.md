# 004 - SVG sibling rasterization

**Status:** Research notes. Not an implementation spec.

> This note was originally written as "SVG sibling rasterization and
> Lucid integration". The Lucid half described a mirror integration
> that is not part of this project; only the SVG-rasterization half
> is reproduced here. Where the text below refers to diagrams
> arriving from a diagramming tool, that is the shape the Lucid half
> assumed.

**Problem brief.** Wherever an `.svg` shows up in mirrored content
(Confluence attachment, embedded image, SharePoint file,
user-committed asset), keep a high-quality `.svg.png` next to it.
The `.svg` is the source of truth; the `.png` is a derived artifact
that gets refreshed automatically. Confluence pages embed the `.png`
(better cross-browser/cross-export fidelity); Quarto renders to
`.docx`/`.pptx` use the `.svg` directly when that works and fall
through to the `.png` when it doesn't.

This document maps the SVG pipeline. It deliberately stops short of
CLI flags, exact frontmatter, or implementation specifics — those
belong in follow-up specs.

## Why a derived `.png` exists alongside the `.svg`

- **Confluence rendering** of SVG attachments is inconsistent across
  the editor, mobile clients, and exported PDFs. PNG renders the same
  everywhere.
- **Office formats** (`.docx`, `.pptx`) have spotty SVG support.
  Pandoc / Quarto's Word and PowerPoint outputs typically rasterize
  SVGs internally, but the result is at the renderer's mercy. A
  controlled, known-good PNG sibling lets us pick the format Office
  handles best on a per-target basis.
- **Email and message previews** of links to SVGs in a git forge
  vary; PNG is universally previewable.
- **Diff legibility.** Diffing two PNGs of the same diagram doesn't
  tell anyone anything; diffing the SVG XML does. Keeping the `.svg`
  as the human-edited / human-diffable source matters.

So: the SVG is the source for git, for review, and for human edits.
The PNG is the lowest-common-denominator render that we automate.

## Filename convention

`Foo.svg` and `Foo.svg.png` as sibling files. The doubled-extension
pattern (`.svg.png`) follows the existing `.docx.md` / `.pptx.md`
shape from spec 010 — it's instantly recognisable as "derived from
the file with the inner extension". It also avoids collisions with
unrelated `Foo.png` source files that someone might commit.

For SVGs *embedded inside* Confluence/SharePoint attachment
directories (via spec 009's `<page-name>-attachments/` convention),
the sibling lives in the same directory:

```
ArchitecturePage-attachments/
  diagram.svg
  diagram.svg.png
```

## Rasterizer choice

Several options, in increasing order of fidelity and weight:

| Renderer | Quality | Speed | Install footprint | Notes |
|---|---|---|---|---|
| `cairosvg` (Python) | OK for simple SVG | Fast | pip install only; no system deps | Misses some modern CSS, web fonts, complex filters |
| `resvg` (via `python-resvg`) | Good | Very fast | Single binary, small | Modern Rust SVG renderer; growing in popularity |
| `rsvg-convert` (librsvg) | Good | Very fast | Requires librsvg system library | Mature, used widely (e.g. Wikimedia) |
| `inkscape --export-png` | Best | Slow | Heavy install (300+ MB) | Highest fidelity for complex / CAD-style SVG |
| Headless Chromium (Playwright) | Best | Slowest | ~300 MB; large dependency surface | Full CSS/font support; overkill for diagrams |

For typical architecture diagrams (exports from a diagramming tool,
draw.io, hand-drawn), cairosvg or resvg covers the common case.
Recommendation:

- **Default**: `cairosvg` (zero system deps; pip-installable).
- **Configurable**: `svg.renderer: cairosvg | resvg | rsvg | inkscape`
  — chosen per-mirror or globally. If the configured renderer is
  unavailable, fall back to cairosvg with a warning and a pointer to
  the install instructions for the preferred renderer.
- **No automatic browser-based fallback**: too heavy a default.

## Rasterization parameters

- **DPI / scale.** Default to **2× the SVG's nominal pixel size**
  (i.e. width and height attributes from the `<svg>` tag, doubled).
  This produces PNGs sharp enough for retina displays and Office
  embeds without ballooning file size. Configurable via
  `svg.png_scale: float` (default 2.0).
- **Maximum dimensions.** Cap at 4096 × 4096 so a pathological SVG
  with `viewBox="0 0 100000 100000"` doesn't try to allocate a 200
  MB raster buffer. On cap, render at the cap and warn.
- **Background.** Default **transparent**. Some Office export paths
  prefer white; a `--bg white` flag (or per-mirror config) covers
  it. Don't bake this into the rasterizer call without a knob.

## Detection: when does the `.png` need refreshing?

Same SHA-256 / mtime pattern as the SharePoint sync model in
research 002:

- Track `mdd.svg.source_sha256` and `mdd.svg.png_scale` in a
  side-car or in the SVG's frontmatter (SVG supports XML metadata
  blocks; mostly we'd use a tiny side-car or a `.mdd-svg-state.yaml`
  per directory — TBD in the impl spec).
- If `current_sha256(svg) != recorded_sha256` *or* the configured
  scale changed, regenerate the `.png`.
- Atomic write: render to `.svg.png.tmp`, then rename.

## Bulk handling and `mdd convert`

The simplest place for the rasterizer is the **converter registry**
proposed in research 002. Treat `.svg → .svg.png` as another
converter:

```python
CONVERTERS[".svg"] = SvgToPngConverter()
```

Then `mdd convert <path>` on a tree containing SVGs produces sibling
PNGs as part of the same walk that handles `.docx`, `.pptx`, `.pdf`.
No new top-level command needed — it falls out of the existing
extension-dispatch model.

## Embedding behaviour

- **Markdown body** references the `.svg`. It's the source; it's
  what a git forge renders inline; it's what diffs cleanly.
- **Confluence storage XHTML** (when the markdown is pushed back via
  spec 009 / 014) rewrites SVG references to point at the `.png`
  attachment. The push pipeline uploads both files as attachments
  and emits `<ac:image><ri:attachment ri:filename="diagram.svg.png"/>
  </ac:image>` instead of `…filename="diagram.svg"`. This is a small
  but necessary tweak to the spec 009 attachment-sync rule for image
  references — currently it's pass-through; for SVGs it becomes
  swap-to-PNG.
- **Office renders via Quarto** can use either format. Quarto/Pandoc
  handle SVG well in HTML output and modestly well in `.docx` (via
  internal rasterization). For `.pptx` Pandoc historically prefers
  rasters. Recommendation: `mdd` renders pass `.png` to Quarto by
  default (most reliable across formats), with a per-mirror knob
  `quarto.prefer_svg: true` for users who have verified their
  pipeline handles SVG well.

## Edge cases

- **External references** in the SVG (linked fonts, `xlink:href` to
  remote images): rasterize will need them resolvable. cairosvg /
  resvg can warn; we don't resolve the network calls. Documented
  caveat.
- **Animated SVG** (SMIL or CSS animation): rasterize to the static
  initial frame. Documented caveat.
- **Multiple SVG roots in one file** (rare; technically invalid):
  fail with a clear error.
- **SVGs containing `<foreignObject>` with HTML inside**: cairosvg
  can't render HTML; fall back to a heavier renderer if configured,
  otherwise warn and skip.
- **SVGs exported from diagramming tools** (draw.io and friends) are
  large but well-formed; they rasterize cleanly with cairosvg in
  practice.

## What is *not* recommended

- **Auto-converting `.png` back to `.svg`.** No round-trip. PNG is
  lossy; SVG is structured. The arrow only goes one way.
- **Running the rasterizer on every sync run regardless of
  changes.** Caching by source hash is non-negotiable; full re-runs
  on a 200-diagram mirror would waste minutes.
- **Embedding rasterizer choice in per-page frontmatter.** Renderer
  is a tooling concern, not a content concern. It belongs in
  `~/.config/mdd/config.yaml` (or per-mirror config), not in the
  page.

## Recommendations

1. **Converter registry entry for `.svg`** (research 002 already
   proposes the registry). The SVG → PNG converter slots in next to
   the docx/pptx/pdf entries; `mdd convert` and the
   Confluence/SharePoint sync flows pick it up automatically.
2. **Confluence storage-XHTML rendering tweak**: when an `<img
   src="…/foo.svg">` is rendered to storage, swap to
   `…/foo.svg.png` and ensure the `.svg.png` is in the attachment
   manifest. Small adjustment to spec 009's md → storage path; the
   same adjustment serves user-authored SVGs and SVGs derived from
   a diagramming-tool mirror.

## Open questions for the implementation specs

1. **SVG renderer default.** cairosvg seems right for the zero-deps
   path; resvg is a serious contender if we're willing to ship a
   binary. Confirm before committing.
2. **PNG scale default.** 2× is the suggested default; some teams
   may want 3× for print fidelity. Per-mirror config or global
   config?
3. **State storage for SVG sibling rasterization.** Side-car
   `.mdd-svg-state.yaml` per attachment dir, or piggyback on
   page-level frontmatter, or per-file
   `Foo.svg.meta.yaml`? Lean toward per-attachment-dir side-car for
   simplicity, but decide explicitly.
4. **SVG / PNG inside Confluence attachment dirs vs. shared
   workspace.** Today every Confluence page has its own
   `<page>-attachments/`. If the same SVG is referenced from many
   pages, do we duplicate the file (and the rasterized PNG) per
   page, or centralise into a `_shared/` dir? Current spec 009
   duplicates; consider whether the SVG story should centralise to
   save space and avoid drift.

## Useful references

- cairosvg: <https://cairosvg.org/>
- resvg: <https://github.com/RazrFalcon/resvg>
- librsvg / rsvg-convert: <https://gitlab.gnome.org/GNOME/librsvg>
- Quarto image / Pandoc image handling for `.docx`/`.pptx`:
  <https://quarto.org/docs/output-formats/ms-word.html>,
  <https://pandoc.org/MANUAL.html#extension-link_attributes>
