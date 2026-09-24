#!/usr/bin/env python3
"""Derive dark-mode SVG assets, and copy every variant into the site.

The files in SOURCES are the only hand-edited copies. They draw entirely from
the LSD Warm light palette, and every light colour has exactly one dark
counterpart, so a dark variant is a search-and-replace over the source text
rather than a second drawing to keep in step.

The site cannot import from `assets/` (Astro's dev server only serves files
under its own root), so both variants of each asset are also copied into
`site/src/assets/`, the same arrangement the PNG logo already uses.

Every source and every generated file must be well-formed XML with no
scripts, event handlers or script-capable links in it; a file that fails
stops the run before it is written or copied.

Run with `mise run derive-dark-svg-assets`.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree
from xml.parsers import expat

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"
SITE_ASSETS = REPO_ROOT / "site" / "src" / "assets"

# The infographic is the splash hero and sits near the top of README.md; the
# icon is the site header's logo.
SOURCES: tuple[Path, ...] = (
    ASSETS / "mdd-infographic.svg",
    ASSETS / "mdd-icon.svg",
)

# Light hex -> dark hex, taken from the two blocks in site/src/styles/custom.css.
# The slate ink becomes the warm near-white used for headings, the amber
# brightens to the accent-high step so it holds up against a dark background,
# and the panel surfaces invert to sit just above the page background.
RECOLOUR: dict[str, str] = {
    "#333A40": "#FFEBD2",  # ink: slate -> heading near-white
    "#594329": "#B39B80",  # muted body text
    "#C17A23": "#EABB79",  # accent -> accent-high
    "#FDF7EE": "#24130A",  # card surface
    "#DBCBB9": "#3F2E19",  # card edge and hairlines
    "#F6E4C4": "#4A2F08",  # amber wash -> accent-low
}

# Black and white inside a <mask> are luminance, not colour: white keeps a
# pixel and black cuts it out. Recolouring them would punch the knockouts in
# the wrong places, so they pass through untouched in either theme.
PRESERVE = frozenset({"#fff", "#ffffff", "#000", "#000000"})

# Three- and six-digit forms both, so a `#ffffff` written out in full is
# recognised as the mask colour it is instead of slipping past the check below.
HEX = re.compile(r"#(?:[0-9A-Fa-f]{3}){1,2}\b")

# The opening `<svg ...>` tag, which the banner goes after rather than before:
# Astro's image-size probe only scans the first kilobyte of the file to
# recognise an SVG, so anything prepended ahead of that tag eats into a budget
# the source comments already spend.
SVG_OPEN = re.compile(r"<svg\b[^>]*>")


def dark_path(source: Path) -> Path:
    """Return the generated sibling for `source`, e.g. `x.svg` -> `x-dark.svg`."""
    return source.with_name(f"{source.stem}-dark.svg")


def banner(source: Path) -> str:
    """Return the do-not-edit comment naming `source`."""
    return (
        "\n  <!--\n"
        f"    Generated from assets/{source.name} by\n"
        "    `mise run derive-dark-svg-assets`. Do not edit; edit the source\n"
        "    and re-run the task.\n"
        "  -->"
    )


def recolour(svg: str, label: str) -> str:
    """Swap every light hex for its dark counterpart.

    Any colour that is neither in the mapping nor a mask colour is a mistake in
    the source rather than something to pass through silently: it would keep its
    light value and vanish against the dark background.
    """
    found = {match.group() for match in HEX.finditer(svg)}
    unknown = sorted(found - set(RECOLOUR) - PRESERVE)
    if unknown:
        raise SystemExit(
            f"{label} uses colours with no dark counterpart: {', '.join(unknown)}\n"
            "Add them to RECOLOUR in this script, or use an existing palette colour."
        )
    return HEX.sub(lambda match: RECOLOUR.get(match.group(), match.group()), svg)


def parse(svg: str, label: str) -> ElementTree.Element:
    """Parse `svg`, failing with a message naming `label` if it is malformed."""
    try:
        return ElementTree.fromstring(svg)  # noqa: S314  # input is a file in this repository, not untrusted
    except ElementTree.ParseError as error:
        raise SystemExit(f"{label} is not well-formed XML: {error}") from error


def check_well_formed(svg: str, label: str) -> None:
    """Fail on malformed XML, which nothing downstream would catch.

    Astro only probes the first kilobyte of an SVG for its dimensions and never
    parses the rest, so a broken file builds and deploys happily and then draws
    nothing in the browser. A stray `--` inside a comment is enough to do it.
    """
    parse(svg, label)


# Elements that run code or embed a foreign document, compared lower-cased and
# in any namespace: an XHTML `<iframe>` loads even where SVG would not draw it.
ACTIVE_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "handler",
        "listener",
        "iframe",
        "frame",
        "embed",
        "object",
        "applet",
    }
)

# URL schemes no attribute may hold, and the wider set a link may not use.
# Browsers drop whitespace and control characters from a URL before reading
# its scheme, so the check does too.
SCRIPT_SCHEMES = ("javascript:", "vbscript:")
REFUSED_LINK_SCHEMES = (*SCRIPT_SCHEMES, "data:")

# The one `data:` link a drawing may hold: an `<image>` embedding a raster in
# a format that cannot carry markup of its own (so not `image/svg+xml`).
RASTER_DATA_URL = re.compile(r"data:image/(?:png|jpeg|gif|webp)[;,]")

# `onclick`, `onload`, `onmouseover`, ...: an event handler attribute.
EVENT_HANDLER = re.compile(r"on[a-z]+")


def local_name(name: str) -> str:
    """Drop the `{namespace}` prefix ElementTree puts on qualified names."""
    return name.rsplit("}", 1)[-1].lower()


def url_scheme_in(value: str, schemes: tuple[str, ...]) -> bool:
    """Whether `value`, read as a URL, uses one of `schemes`."""
    compact = "".join(char for char in value if char > " ").lower()
    return compact.startswith(schemes)


def animation_problems(tag: str, value: str) -> list[str]:
    """Describe what is wrong with an `attributeName` naming `value`, if anything."""
    target = value.strip().lower().rsplit(":", 1)[-1]
    if target == "href":
        return [f"<{tag}> animates a link target"]
    if EVENT_HANDLER.fullmatch(target):
        return [f"<{tag}> animates the event handler attribute {target}"]
    return []


def is_embedded_raster(tag: str, name: str, value: str) -> bool:
    """Whether this is an `<image>` link to a `data:` PNG, JPEG, GIF or WebP."""
    compact = "".join(char for char in value if char > " ").lower()
    return tag == "image" and name == "href" and RASTER_DATA_URL.match(compact) is not None


def attribute_problems(tag: str, name: str, value: str) -> list[str]:
    """Describe what is wrong with one attribute of a `<tag>` element, if anything."""
    if EVENT_HANDLER.fullmatch(name):
        return [f"<{tag}> has an event handler attribute {name}"]
    if is_embedded_raster(tag, name, value):
        return []
    if url_scheme_in(value, REFUSED_LINK_SCHEMES if name == "href" else SCRIPT_SCHEMES):
        return [f"<{tag}> {name} links to a {value.strip()[:40]!r} URL"]
    if name == "attributename":
        return animation_problems(tag, value)
    return []


def element_problems(element: ElementTree.Element) -> list[str]:
    """Describe the content in `element` itself that runs code, if any."""
    tag = local_name(element.tag)
    problems = [f"contains a <{tag}> element"] if tag in ACTIVE_ELEMENTS else []
    for name, value in element.attrib.items():
        problems.extend(attribute_problems(tag, local_name(name), value))
    return problems


def declaration_problems(svg: str) -> list[str]:
    """Describe the DOCTYPE and processing instructions in `svg`, which ElementTree drops.

    A drawing needs neither. A processing instruction can attach an XSLT
    stylesheet that runs when the file is opened on its own, and a DOCTYPE can
    declare entities that hide markup from a reader of the source.
    """
    problems: list[str] = []

    def on_doctype(name: str, _system_id: str | None, _public_id: str | None, _subset: int) -> None:
        problems.append(f"has a <!DOCTYPE {name}> declaration")

    def on_processing_instruction(target: str, _data: str) -> None:
        problems.append(f"has a <?{target}?> processing instruction")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = on_doctype
    parser.ProcessingInstructionHandler = on_processing_instruction
    parser.Parse(svg, True)
    return problems


def check_no_active_content(svg: str, label: str) -> None:
    """Fail if the SVG could run code when a browser displays it.

    Both variants of every asset are copied into the documentation site, and
    other builds copy them onward from there. A drawing needs none of scripts,
    embedded foreign documents, event handler attributes, `javascript:` URLs,
    `data:` links other than an `<image>` embedding a PNG, JPEG, GIF or WebP
    raster, animations that rewrite a link or an event handler, a
    DOCTYPE or a processing instruction, so any of them is refused outright
    rather than stripped.
    """
    root = parse(svg, label)
    problems = declaration_problems(svg)
    problems.extend(problem for element in root.iter() for problem in element_problems(element))
    if problems:
        raise SystemExit(
            f"{label} contains content that runs code, which an SVG asset must not:\n"
            + "\n".join(f"  {problem}" for problem in problems)
        )


def insert_banner(svg: str, source: Path) -> str:
    """Put the do-not-edit banner just inside the root element."""
    match = SVG_OPEN.search(svg)
    if match is None:
        raise SystemExit(f"no opening <svg> tag found in {source.name}")
    return f"{svg[: match.end()]}{banner(source)}{svg[match.end() :]}"


def derive(source: Path) -> list[Path]:
    """Write `source`'s dark sibling and return both files, in light-dark order."""
    light = source.read_text(encoding="utf-8")
    check_well_formed(light, source.name)
    check_no_active_content(light, source.name)

    target = dark_path(source)
    dark = insert_banner(recolour(light, source.name), source)
    check_well_formed(dark, target.name)
    check_no_active_content(dark, target.name)
    target.write_text(dark, encoding="utf-8")
    return [source, target]


def main() -> int:
    missing = [source for source in SOURCES if not source.exists()]
    if missing:
        for source in missing:
            print(f"source not found: {source}", file=sys.stderr)
        return 1

    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        for path in derive(source):
            shutil.copyfile(path, SITE_ASSETS / path.name)
            print(f"wrote {path.relative_to(REPO_ROOT)}")
            print(f"wrote {(SITE_ASSETS / path.name).relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
