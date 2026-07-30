#!/usr/bin/env python3
"""Derive the dark-mode site logo from the light-mode one.

The logo is a transparent PNG in two colours: a dark slate for the wordmark
and the document outlines, and an amber that already matches the site's accent
ramp. Only the slate needs to change for a dark background; recolouring it to
the warm near-white the site uses for headings keeps the amber intact and the
two variants identical in shape.

Pixels are mapped by nearest source colour, so antialiased edges -- which are
blends of a source colour and transparency -- follow the colour they came
from. Alpha is preserved untouched.

Run with `mise run derive-dark-logo`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "assets" / "mdd-logo.png"
TARGET = REPO_ROOT / "site" / "src" / "assets" / "mdd-logo-dark.png"

type Rgb = tuple[int, int, int]

# Slate becomes the warm near-white the dark theme uses for headings; amber is
# already the accent colour and maps to itself.
SLATE: Rgb = (51, 58, 64)
AMBER: Rgb = (193, 122, 35)
RECOLOUR: dict[Rgb, Rgb] = {SLATE: (255, 235, 210), AMBER: AMBER}


def nearest(pixel: Rgb, anchors: list[Rgb]) -> Rgb:
    """Return the anchor colour closest to `pixel` in squared RGB distance."""

    def distance(anchor: Rgb) -> int:
        return sum((a - b) ** 2 for a, b in zip(pixel, anchor, strict=True))

    return min(anchors, key=distance)


def recolour(image: Image.Image) -> Image.Image:
    """Map every visible pixel onto its recoloured anchor, keeping alpha."""
    anchors = list(RECOLOUR)
    out = Image.new("RGBA", image.size)
    source = image.load()
    dest = out.load()
    if source is None or dest is None:  # pragma: no cover - Pillow always loads
        raise RuntimeError("could not access pixel data")

    width, height = image.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = source[x, y]
            if a == 0:
                continue
            dest[x, y] = (*RECOLOUR[nearest((r, g, b), anchors)], a)
    return out


def main() -> int:
    if not SOURCE.exists():
        print(f"source logo not found: {SOURCE}", file=sys.stderr)
        return 1

    with Image.open(SOURCE) as image:
        result = recolour(image.convert("RGBA"))

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    result.save(TARGET)
    print(f"wrote {TARGET.relative_to(REPO_ROOT)} ({result.width}x{result.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
