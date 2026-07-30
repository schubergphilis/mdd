"""Filename sanitization and collision handling for Confluence exports."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\n\t\r]')
_MULTI_DASH = re.compile(r"-{2,}")

# Unicode category "Zs" (Separator, space): U+0020 plus its look-alikes —
# NBSP, en/em spaces, ideographic space, etc. Confluence titles copy-pasted
# from some sources use U+00A0 NO-BREAK SPACE between words instead of a
# plain space (issue #140); folding the whole category to a single ASCII
# space keeps the sanitized filename — and thus every path derived from it,
# including the synthetic path the `.mddignore` matcher builds — stable
# regardless of which space variant the source title used.
_UNICODE_SPACE_RUN = re.compile("[\u0020\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")


def sanitize(title: str) -> str:
    """Convert a Confluence page title to a safe filesystem filename (without extension).

    Rules:
    - Normalize to NFC and fold runs of Unicode space-separator characters
      (category Zs — NBSP and friends) to a single ASCII space (issue #140)
    - Replace <>:"/\\|?*\\n\\t\\r with -
    - Strip leading/trailing whitespace and dots
    - Collapse runs of - to a single -
    - Truncate to 200 characters
    - Fall back to 'untitled' if result is empty

    Additionally, any ``..`` path components, leading ``~``, or residual path
    separators are stripped after the regex pass so that a future regex change
    cannot reintroduce path traversal.
    """
    title = unicodedata.normalize("NFC", title)
    title = _UNICODE_SPACE_RUN.sub(" ", title)
    result = _FORBIDDEN.sub("-", title)
    result = result.strip(". \t\n\r")
    result = _MULTI_DASH.sub("-", result)
    result = result[:200]
    result = result or "untitled"

    # Explicit path-traversal guard: remove any separator characters and ~ that
    # survived (belt-and-suspenders; the regex already handles / and \).
    sep = os.sep
    altsep = os.altsep  # None on POSIX, "/" on Windows with pathlib quirks
    for ch in [sep] + ([altsep] if altsep else []):
        result = result.replace(ch, "-")
    # Remove leading ~ (home-dir expansion)
    result = result.lstrip("~") or "untitled"
    # Collapse any new multi-dash sequences introduced by the above replacements
    result = _MULTI_DASH.sub("-", result)
    # Strip leading/trailing dashes left by separator removal
    result = result.strip("-") or "untitled"
    # Reject residual ".." sequences — replace them with a single dash.
    # ".." in a filename component is still a path-traversal risk when joined.
    while ".." in result:
        result = result.replace("..", "-")
    result = _MULTI_DASH.sub("-", result)
    return result.strip("-") or "untitled"


def _read_page_id_from_frontmatter(path: Path) -> str | None:
    """Return the ``confluence.page_id`` from a file's YAML frontmatter, or None."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        rest = text[4:]
        end_idx = rest.find("\n---\n")
        if end_idx == -1:
            return None
        yaml_block = rest[:end_idx]
        parsed: Any = yaml.safe_load(yaml_block)  # pyright: ignore[reportAny]
        if not isinstance(parsed, dict):
            return None
        parsed_dict: dict[str, Any] = dict(parsed.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        conf_raw: Any = parsed_dict.get("confluence")  # pyright: ignore[reportAny]
        if not isinstance(conf_raw, dict):
            return None
        conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        pid: Any = conf.get("page_id")  # pyright: ignore[reportAny]
        return str(pid) if isinstance(pid, str) and pid else None
    except Exception:
        return None


def disambiguate(path: Path, page_id: str) -> Path:
    """If path exists, append (page_id) before the extension.

    E.g. ``Foo.md`` → ``Foo(12345).md``

    If the existing file's frontmatter already contains the same ``page_id``,
    the path is returned unchanged (same-page incremental re-export).

    If the disambiguated name itself already exists (e.g. because another page
    is literally titled ``Foo(12345)``), a numeric counter is appended:
    ``Foo(12345)(2).md``, ``Foo(12345)(3).md``, etc.
    """
    if not path.exists():
        return path
    # Incremental re-export: the existing file belongs to the same page — reuse it
    if _read_page_id_from_frontmatter(path) == page_id:
        return path
    stem = path.stem
    suffix = path.suffix
    candidate = path.with_name(f"{stem}({page_id}){suffix}")
    if not candidate.exists():
        return candidate
    # Also check if the disambiguated candidate already belongs to this page
    if _read_page_id_from_frontmatter(candidate) == page_id:
        return candidate
    # Second-level collision: escalate with a numeric counter.  Bounded so a
    # broken caller cannot loop forever; 9 collisions on a single page-id
    # already indicates something is very wrong.
    for counter in range(2, 11):
        candidate = path.with_name(f"{stem}({page_id})({counter}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"disambiguate({path}, page_id={page_id}): more than 9 collisions — "
        f"refusing to keep escalating filenames"
    )
