"""Shared regex patterns for the markdown reader."""

from __future__ import annotations

import re

INLINE_MACRO_RE = re.compile(r"\{\{confluence:([A-Za-z0-9_-]+)((?:\s+[^=}]+=\"[^\"]*\")*)\s*\}\}")
INLINE_RAW_RE = re.compile(r"\{\{confluence-raw:([A-Za-z0-9+/=]+)\}\}")
ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="((?:[^"\\]|\\.)*)"')
