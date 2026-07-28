"""Exception type for Confluence client failures."""

from __future__ import annotations


class ConfluenceError(Exception):
    """Raised when a Confluence API call fails after all retries."""
