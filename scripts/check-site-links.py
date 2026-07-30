#!/usr/bin/env python3
"""Check that every internal link in the built site resolves to something served.

The sync step validates that a link's *target file exists in the repository*.
That is a different question from whether the URL it emits matches what the
site actually serves, and only the second one matters to a reader. A case
mismatch between a filename and the slug derived from it satisfies the first
check and 404s on the second.

This runs over `site/dist/` after a build and resolves every internal `href`
and `src` against the pages and assets that were emitted. Fragments are
stripped rather than verified: checking that an anchor exists on the target
page is a larger job and is not attempted here.

Run with `mise run docs-links`, which builds the site first.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "site" / "dist"
BASE = "/mdd/"

# `href="..."` and `src="..."`, single or double quoted.
LINK_RE = re.compile(r"""\b(?:href|src)=["']([^"']+)["']""")
EXTERNAL_SCHEMES = ("http://", "https://", "//", "mailto:", "tel:", "data:")

# Documentation quotes HTML at itself — `<a href="...">` in a spec table, an
# `<img src=".svg">` in a research note. Inside <code> and <pre> the angle
# brackets are escaped but the quotes are not, so the attribute text survives
# verbatim and looks exactly like a real link to a regex. Drop those regions
# before scanning.
CODE_RE = re.compile(r"<(code|pre)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)


def is_internal(url: str) -> bool:
    """True for a link this site is responsible for serving."""
    if not url or url.startswith(("#", "?")):
        return False
    return not url.startswith(EXTERNAL_SCHEMES)


def target_path(url: str) -> str | None:
    """Strip the deploy base, the fragment and any query from an internal URL.

    Returns None for a link that is not under the deploy base, which a
    correctly built page should never contain.
    """
    path = url.partition("#")[0].partition("?")[0]
    if not path.startswith(BASE):
        return None
    return path[len(BASE) :].strip("/")


def is_served(target: str, pages: set[str], dist: Path) -> bool:
    """True if `target` resolves to a rendered page or an emitted asset."""
    if not target:
        return True  # the site root
    return target in pages or (dist / target).is_file()


def collect_pages(dist: Path) -> set[str]:
    """Every directory that has an index.html, as a base-relative path."""
    return {p.parent.relative_to(dist).as_posix().strip(".") for p in dist.rglob("index.html")}


def find_broken(dist: Path) -> dict[str, set[str]]:
    """Map each unresolvable URL to the pages that link to it."""
    pages = collect_pages(dist)
    broken: dict[str, set[str]] = defaultdict(set)
    for html in dist.rglob("*.html"):
        source = html.relative_to(dist).as_posix()
        markup = CODE_RE.sub("", html.read_text(encoding="utf-8"))
        for url in LINK_RE.findall(markup):
            if not is_internal(url):
                continue
            # A None target is a root-relative link that missed the deploy
            # base, which 404s on a project site just as surely as a typo.
            target = target_path(url)
            if target is None or not is_served(target, pages, dist):
                broken[url].add(source)
    return broken


def report(broken: dict[str, set[str]]) -> None:
    for url in sorted(broken):
        sources = sorted(broken[url])
        shown = ", ".join(sources[:3])
        more = f" (+{len(sources) - 3} more)" if len(sources) > 3 else ""
        print(f"broken link: {url}\n  linked from: {shown}{more}", file=sys.stderr)


def main() -> int:
    if not DIST.is_dir():
        print(f"no build found at {DIST}; run `mise run docs-build` first", file=sys.stderr)
        return 1

    pages = collect_pages(DIST)
    broken = find_broken(DIST)
    if broken:
        report(broken)
        print(
            f"check-site-links: {len(broken)} broken internal link target(s)",
            file=sys.stderr,
        )
        return 1

    print(f"check-site-links: all internal links resolve across {len(pages)} page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
