"""Confluence page-id-or-URL parser."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class URLMismatchError(Exception):
    """Raised when a URL host does not match the expected host."""


@dataclass(frozen=True)
class PageRef:
    """A parsed reference to a Confluence page.

    - host: the Confluence host (e.g. 'example.atlassian.net'), or None for bare IDs
    - space_key: the space key from the URL, or None if not present
    - page_id: the numeric page ID, or empty string for short URLs (caller resolves redirect)
    """

    host: str | None
    space_key: str | None
    page_id: str


def parse(input: str, *, expected_host: str | None = None) -> PageRef:
    """Parse a page-id-or-URL into a PageRef.

    Accepted forms:
    - Bare numeric ID: '12345'
    - Canonical URL: 'https://host/wiki/spaces/SPACE/pages/12345'
    - Slug URL:      'https://host/wiki/spaces/SPACE/pages/12345/slug'
    - Short URL:     'https://host/wiki/x/<base62>'

    Query strings are stripped before parsing.
    If expected_host is set, a mismatch raises URLMismatchError.
    """
    stripped = input.strip()

    # Bare numeric ID
    if stripped.isdigit():
        return PageRef(host=None, space_key=None, page_id=stripped)

    parsed = urlparse(stripped)
    host = parsed.hostname or ""

    if expected_host is not None and host != expected_host:
        raise URLMismatchError(f"URL host {host!r} does not match expected host {expected_host!r}")

    path = parsed.path  # query already excluded by urlparse

    # Short URL: /wiki/x/<base62>
    if path.startswith("/wiki/x/"):
        return PageRef(host=host, space_key=None, page_id="")

    # Canonical / slug URL: /wiki/spaces/<SPACE>/pages/<id>(/<slug>)?
    parts = [p for p in path.split("/") if p]
    # Expected: ['wiki', 'spaces', '<SPACE>', 'pages', '<id>', ...]
    if (
        len(parts) >= 5
        and parts[0] == "wiki"
        and parts[1] == "spaces"
        and parts[3] == "pages"
        and parts[4].isdigit()
    ):
        return PageRef(host=host, space_key=parts[2], page_id=parts[4])

    # Numeric path segment with query stripped (edge case: /wiki/spaces/SPACE/pages/12345?foo=bar)
    # Already handled above since urlparse splits query out.

    raise ValueError(f"Cannot parse Confluence page reference: {input!r}")
