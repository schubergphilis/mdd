#!/usr/bin/env python3
"""Derive `simple-presentation-compact.pptx` from `simple-presentation.pptx`.

Usage:
    python3 scripts/derive-compact-pptx.py [--check]

The bundled `simple-presentation.pptx` slide master carries a 28 / 24 / 20 / 18 pt
body scale (`<p:bodyStyle>` levels 1-4, with levels 5-9 pinned to level 4). That is
comfortable for sparse decks and overflows dense ones, so `mdd new-pptx --compact`
scaffolds against a second template with an 18 / 16 / 14 / 12 pt scale instead.

The compact template is a byte-for-byte copy of the default apart from the nine
`sz` attributes in `ppt/slideMasters/slideMaster1.xml`'s `<p:bodyStyle>`. Nothing
else moves: the 4400 title in `<p:titleStyle>`, the 1800 `<p:otherStyle>` default,
the 1200 date/footer/slide-number placeholders, the 1000 disclaimer textbox and
every `ppt/slideLayouts/*.xml` override are left exactly as they are. Regenerating
by hand in PowerPoint would rewrite the whole archive and make the binary
unreviewable, so this script does the edit textually and rezips in the original
entry order with the original compression, keeping `[Content_Types].xml` first.

`--check` verifies the committed compact template still matches what this script
would produce, without writing anything.

Exit codes:
    0  — success (or, with --check, the committed template is up to date).
    1  — the source template does not look the way we expect, or --check failed.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "mdd" / "templates"
SOURCE = TEMPLATES / "simple-presentation.pptx"
TARGET = TEMPLATES / "simple-presentation-compact.pptx"

MASTER = "ppt/slideMasters/slideMaster1.xml"

# `<p:bodyStyle>` level -> (expected size in the default template, compact size).
# Hundredths of a point, so 2800 == 28pt. Levels 5-9 follow level 4, which is how
# the default template is already shaped.
BODY_SCALE: dict[int, tuple[int, int]] = {
    1: (2800, 1800),
    2: (2400, 1600),
    3: (2000, 1400),
    4: (1800, 1200),
    5: (1800, 1200),
    6: (1800, 1200),
    7: (1800, 1200),
    8: (1800, 1200),
    9: (1800, 1200),
}


class DeriveError(Exception):
    """The source template does not match this script's expectations."""


def _body_style_span(xml: str) -> tuple[int, int]:
    """Return the (start, end) offsets of the `<p:bodyStyle>` element's content."""
    open_tag, close_tag = "<p:bodyStyle>", "</p:bodyStyle>"
    start = xml.find(open_tag)
    end = xml.find(close_tag)
    if start < 0 or end < 0 or end < start:
        raise DeriveError(f"no <p:bodyStyle> element found in {MASTER}")
    return start + len(open_tag), end


def _rewrite_level(body: str, level: int, expected: int, compact: int) -> str:
    """Return *body* with level *level*'s `defRPr` size changed to *compact*."""
    pattern = re.compile(
        rf'(<a:lvl{level}pPr\b[^>]*>.*?<a:defRPr[^>]*?\bsz=")({expected})(")',
        re.DOTALL,
    )
    body, count = pattern.subn(rf"\g<1>{compact}\g<3>", body, count=1)
    if count != 1:
        raise DeriveError(
            f"<p:bodyStyle> level {level} does not carry the expected sz={expected}; "
            "the default template has changed shape, so re-check the scale by hand"
        )
    return body


def compact_master_xml(xml: str) -> str:
    """Return *xml* (a slideMaster1.xml) with the compact body scale applied."""
    start, end = _body_style_span(xml)
    body = xml[start:end]
    for level, (expected, compact) in BODY_SCALE.items():
        body = _rewrite_level(body, level, expected, compact)
    return xml[:start] + body + xml[end:]


def build(source: Path, target: Path) -> None:
    """Write *target* as *source* with the compact body scale applied to the master."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as out:
        names = src.namelist()
        if names[0] != "[Content_Types].xml":
            raise DeriveError(
                f"{source.name} does not start with [Content_Types].xml "
                f"(first entry is {names[0]!r}); PowerPoint may reject a rezip"
            )
        if MASTER not in names:
            raise DeriveError(f"{source.name} has no {MASTER}")
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == MASTER:
                data = compact_master_xml(data.decode("utf-8")).encode("utf-8")
            # Copy the entry verbatim apart from its (possibly changed) size, so
            # order, timestamps, permissions and compression all survive.
            clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            clone.compress_type = info.compress_type
            clone.external_attr = info.external_attr
            clone.internal_attr = info.internal_attr
            clone.create_system = info.create_system
            out.writestr(clone, data)


def read_sizes(pptx: Path) -> dict[int, int]:
    """Return the `<p:bodyStyle>` level -> sz mapping recorded in *pptx*'s master."""
    with zipfile.ZipFile(pptx) as zf:
        xml = zf.read(MASTER).decode("utf-8")
    start, end = _body_style_span(xml)
    body = xml[start:end]
    sizes: dict[int, int] = {}
    for level in BODY_SCALE:
        match = re.search(
            rf'<a:lvl{level}pPr\b[^>]*>.*?<a:defRPr[^>]*?\bsz="(\d+)"',
            body,
            re.DOTALL,
        )
        if match is None:
            raise DeriveError(f"{pptx.name}: no sz for <p:bodyStyle> level {level}")
        sizes[level] = int(match.group(1))
    return sizes


def _check(tmp: Path) -> int:
    if not TARGET.exists():
        print(f"FAIL: {TARGET} does not exist", file=sys.stderr)
        return 1
    build(SOURCE, tmp)
    if tmp.read_bytes() != TARGET.read_bytes():
        print(
            f"FAIL: {TARGET.name} differs from what this script produces from "
            f"{SOURCE.name}; re-run without --check",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {TARGET.name} matches {SOURCE.name} with the compact scale applied")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive simple-presentation-compact.pptx from simple-presentation.pptx."
    )
    _ = parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed compact template is up to date instead of writing it",
    )
    args = parser.parse_args()

    if not SOURCE.exists():
        print(f"ERROR: {SOURCE} not found", file=sys.stderr)
        return 1

    scratch = TARGET.with_suffix(".pptx.tmp")
    try:
        if args.check:
            return _check(scratch)
        build(SOURCE, scratch)
        shutil.move(str(scratch), str(TARGET))
    except DeriveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        scratch.unlink(missing_ok=True)

    sizes = read_sizes(TARGET)
    pretty = " / ".join(f"{sizes[level] / 100:g}pt" for level in (1, 2, 3, 4))
    print(f"Wrote {TARGET} — body scale {pretty}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
