#!/usr/bin/env python3
"""Print the spec index, computed from docs/spec/SNN-*.md files.

Columns: # | Title | Purpose | Status

For each `docs/spec/SNN-<slug>.md` file (excluding `000-*.md`):

- The number is parsed from the filename (as `S<NN>`).
- The title is the first H1; any leading `SNN -` / `SNN:` prefix is stripped.
  The cell is rendered as a markdown link to the spec file.
- The purpose is the first paragraph that begins with `**Purpose:**`,
  flattened to a single line.
- The status is the value of the first `**Status:** <value>` line
  in the file (empty if absent).

Markdown parsing uses the `markdown-it-py` library; run via `uv run`.

Exit codes:
    0  — success.
    1  — no spec files found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from markdown_it import MarkdownIt

SPEC_DIR = Path("docs") / "spec"
FILENAME_RE = re.compile(r"^(S\d+)-(.+)\.md$")
TITLE_PREFIX_RE = re.compile(r"^S?\d+\s*[-:]\s*")
PURPOSE_PREFIX_RE = re.compile(r"^\*\*Purpose:\*\*\s*", re.IGNORECASE)
STATUS_PREFIX_RE = re.compile(r"^\*\*Status:\*\*\s*(.*?)\s*$", re.IGNORECASE)

_md = MarkdownIt("commonmark")


def _flatten(text: str) -> str:
    return " ".join(text.split())


def extract_fields(spec_path: Path) -> tuple[str, str, str]:
    """Return (title, purpose, status) for one spec file."""
    text = spec_path.read_text(encoding="utf-8")
    tokens = _md.parse(text)

    title = ""
    purpose = ""
    status = ""

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == "heading_open" and tok.tag == "h1" and not title:
            inline = tokens[i + 1] if i + 1 < n else None
            heading_text = _flatten(inline.content if inline and inline.type == "inline" else "")
            title = TITLE_PREFIX_RE.sub("", heading_text).strip()
            i += 3
            continue
        if tok.type == "paragraph_open":
            inline = tokens[i + 1] if i + 1 < n else None
            raw = inline.content if inline and inline.type == "inline" else ""
            for raw_line in raw.splitlines():
                line = raw_line.strip()
                if not purpose:
                    m = PURPOSE_PREFIX_RE.match(line)
                    if m:
                        purpose = _flatten(PURPOSE_PREFIX_RE.sub("", line))
                if not status:
                    m = STATUS_PREFIX_RE.match(line)
                    if m:
                        status = m.group(1).strip()
            i += 3
            continue
        i += 1

    return title, purpose, status


def main() -> None:
    files = sorted(SPEC_DIR.glob("S[0-9]*-*.md"))
    if not files:
        print(f"ERROR: No spec files found under '{SPEC_DIR}'.", file=sys.stderr)
        sys.exit(1)

    print("| # | Title | Purpose | Status |")
    print("|---|-------|---------|--------|")
    for spec_path in files:
        m = FILENAME_RE.match(spec_path.name)
        if not m:
            continue
        number = m.group(1)
        title, purpose, status = extract_fields(spec_path)
        if not title:
            title = spec_path.stem
        print(f"| {number} | [{title}]({spec_path.name}) | {purpose} | {status} |")


if __name__ == "__main__":
    main()
