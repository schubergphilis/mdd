"""ANSI color helpers for ``mdd search`` (spec S19).

Mirrors ripgrep's default palette so muscle memory carries over:

* filename: magenta
* line number: green
* matched text: bold red
* metadata labels ("(page N)", "Title:"): dim

``Color.detect`` honours ``--color {auto,always,never}`` plus the
``NO_COLOR`` and ``FORCE_COLOR`` environment variables. ``auto`` enables
color only when the target stream is a TTY.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO


# SGR codes; kept here so callers don't sprinkle magic numbers around.
_SGR_MATCH = "\x1b[1;31m"  # bold red
_SGR_PATH = "\x1b[35m"  # magenta
_SGR_LINE = "\x1b[32m"  # green
_SGR_DIM = "\x1b[2m"  # dim / faint
_SGR_RESET = "\x1b[0m"


@dataclass(frozen=True)
class Color:
    """Apply ANSI color codes when *enabled*; pass-through otherwise."""

    enabled: bool

    @classmethod
    def detect(cls, mode: str, *, stream: IO[str] | None = None) -> Color:
        """Resolve color settings against env vars and TTY status.

        ``mode`` is one of ``always`` / ``never`` / ``auto``.
        ``NO_COLOR`` forces off; ``FORCE_COLOR`` forces on (unless
        ``NO_COLOR`` is also set — NO_COLOR wins).
        """
        if mode == "always":
            return cls(True)
        if mode == "never":
            return cls(False)
        if "NO_COLOR" in os.environ:
            return cls(False)
        if os.environ.get("FORCE_COLOR"):
            return cls(True)
        s = stream if stream is not None else sys.stdout
        isatty = getattr(s, "isatty", None)
        return cls(bool(isatty()) if callable(isatty) else False)

    def match(self, s: str) -> str:
        """Highlight a matched span (bold red)."""
        return f"{_SGR_MATCH}{s}{_SGR_RESET}" if self.enabled else s

    def path(self, s: str) -> str:
        """Colour a file path / mirror header (magenta)."""
        return f"{_SGR_PATH}{s}{_SGR_RESET}" if self.enabled else s

    def line_number(self, s: str) -> str:
        """Colour a line-number cell (green)."""
        return f"{_SGR_LINE}{s}{_SGR_RESET}" if self.enabled else s

    def meta(self, s: str) -> str:
        """Dim metadata labels like ``Title:`` and ``(page N)``."""
        return f"{_SGR_DIM}{s}{_SGR_RESET}" if self.enabled else s


NO_COLOR = Color(False)
