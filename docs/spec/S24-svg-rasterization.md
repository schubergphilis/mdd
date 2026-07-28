# 024 - SVG sibling rasterization

**Purpose:** Keep a high-quality `<name>.svg.png` sibling next to every `.svg` file in a mirror, refreshed automatically when the source changes.

**Status:** Implemented (2026-05-08)

## Introduction

Wherever an `.svg` file appears in a mirror, the SVG is the source of truth and is committed to git; the PNG is a derived render. This is useful for Office exports (`.docx`/`.pptx` via Quarto handle PNG more reliably than SVG) and for environments that don't render SVG well.

This spec adds an `.svg` entry to the converter registry ([S15](S15-converter-registry.md)).
Once landed, `mdd convert`, `mdd confluence sync`, `mdd sharepoint
sync`, and `mdd lucid sync` all gain SVG rasterization automatically.

Originates from research doc 004.

## Requirements

**Sibling output**
- For `Foo.svg`, produce `Foo.svg.png` in the same directory. The
  doubled-extension shape matches `.docx.md` / `.pptx.md`
  conventions.

**Rasterizer choice**
- Default: **`rsvg-convert`** (librsvg). Mature, fast, high
  fidelity. Requires the `librsvg` system library; document
  install (`brew install librsvg`, `apt install librsvg2-bin`).
- Configurable via `svg.renderer: rsvg | cairosvg | resvg | inkscape`
  in user config.
- If the configured renderer isn't available at runtime, exit 1
  with an actionable install hint. Do not auto-fall-back to
  cairosvg silently — silent fallbacks produce inconsistent
  output across machines.
- **Why librsvg over cairosvg as default**: librsvg is faster and
  handles Lucid / draw.io exports more reliably. Cairosvg remains
  available for pure-Python no-system-deps environments.

**Rasterization parameters**
- Default scale: **2× SVG nominal size**. Configurable via
  `svg.png_scale: float`.
- Maximum dimensions: **4096 × 4096**. Cap with warning if exceeded.
- Background: **transparent**. `svg.background: white|transparent`
  config knob.
- Output bit depth: 8-bit RGBA.

**Caching**
- Per-SVG side-car file `Foo.svg.meta.yaml` records source
  sha256, renderer name + version, scale, background, and
  timestamp.
- Skip render when the side-car matches the current SVG +
  current config; re-render otherwise. Writes are atomic (render
  to `.tmp`, rename, update side-car).

Side-car shape:
```yaml
svg:
  source_sha256: 9f86d081...
  renderer: rsvg-convert
  renderer_version: "2.58.0"
  png_scale: 2.0
  background: transparent
  rendered_at: 2026-05-08T10:30:00Z
```

**Edge cases**
- **External references** (linked fonts, `xlink:href` to remote
  images): warn but don't block. Output may differ from the
  editor view.
- **Animated SVG** (SMIL or CSS animation): render to the static
  initial frame.
- **`<foreignObject>` containing HTML**: attempt; warn and skip
  if the renderer fails.
- **Multiple SVG roots**: hard error.
- **Pathological dimensions**: render at the cap and warn.

**Mirror integration**
- The converter registry entry plugs into S15 with
  `extensions=(".svg",)` and `output_suffix=".svg.png"`. Pull-side
  for Confluence ([S16](S16-confluence-attachment-conversion.md)) and
  SharePoint ([S18](S18-sharepoint-sync.md)) picks it up
  automatically; sibling PNGs land in the mirror.
- Push side does **not** swap `<img src=".svg">` for `.svg.png` in
  Confluence storage XHTML. SVGs push as `.svg`; the PNG sibling
  is for Office / external rendering only.
- Lucid sync (S25) downloads PNG
  exports directly from the Lucid API, so it does not invoke
  this rasterizer for Lucid-sourced SVGs.

## Design Approach

**Backend abstraction.** A small `SvgRenderer` protocol wraps each
backend (`rsvg-convert`, `cairosvg`, `resvg`, `inkscape`). All
backends share the same `render(src, dest, *, scale, bg)` contract
so the converter doesn't care which one is configured.

**Renderer detection.** On first use, probe `<binary> --version`
and cache the result. If the binary is missing, raise an actionable
error naming the install command — no silent fallbacks.

## Out of scope

- Vector → vector format conversion (SVG → PDF, SVG → EMF).
- SVG optimisation / minification.
- PNG → SVG vectorisation. PNG is lossy; SVG is structured. No
  reverse path.
- Per-page rasterizer overrides. Renderer is a tooling concern.
