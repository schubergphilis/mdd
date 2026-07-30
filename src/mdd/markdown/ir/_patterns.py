"""Shared regex patterns for the Confluence markdown flavour.

Single source of truth for the ``{{confluence:...}}`` marker grammar. Both
the markdown-it inline rule (``inline_macros.py``, which tokenises the
markers) and the reader (``reader.macros``, which turns token content into
IR) match against these, so the two must agree exactly. They used to be
duplicated per module, which is how one regex bug became two CodeQL alerts.

``INLINE_MACRO_RE``'s attribute-key class is deliberately the same as
``ATTR_RE``'s: ``ATTR_RE`` is what actually extracts the key/value pairs out
of group 2, so a key shape the recogniser accepted but ``ATTR_RE`` could not
parse would be silently mangled. It must also stay disjoint from the ``\\s+``
separator ahead of it — a key class that can itself match whitespace (the
old ``[^=}]+``) makes the number of ways to split a whitespace run between
``\\s+`` and the key grow exponentially with the repetition count, so a
non-matching input backtracks exponentially (ReDoS).
"""

from __future__ import annotations

import re

# Attribute/macro name shape. Must not overlap ``\s`` — see module docstring.
_KEY = r"[A-Za-z0-9_-]+"

INLINE_MACRO_RE = re.compile(rf'\{{\{{confluence:({_KEY})((?:\s+{_KEY}="[^"]*")*)\s*\}}\}}')
INLINE_RAW_RE = re.compile(r"\{\{confluence-raw:([A-Za-z0-9+/=]+)\}\}")
ATTR_RE = re.compile(rf'({_KEY})="((?:[^"\\]|\\.)*)"')
