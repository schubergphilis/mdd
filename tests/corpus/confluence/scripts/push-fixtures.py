#!/usr/bin/env python3
"""Push the markdown-first corpus fixtures to the test Confluence space.

Walks ``fixtures/`` and ``corpus/`` for ``*.md`` files, skips any
that already carry a ``confluence.page_id`` in their YAML
frontmatter (so the script is idempotent and safe to re-run), and
runs ``mdd confluence create page`` for each remaining file using
the first ``# H1`` line in the file as the page title.

The script intentionally pushes every fixture at the space root.
If you want to organise them into sub-pages in the Confluence UI,
rearrange in the UI after pushing — the page IDs are stable so
the markdown files keep tracking the right page.

Usage:
    python scripts/push-fixtures.py            # actually push
    python scripts/push-fixtures.py --dry-run  # just report
    python scripts/push-fixtures.py path/to/file.md  # push a single file

Exit code: 0 if everything succeeded (or only no-ops); 1 if any
push failed or any fixture had no H1.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parent.parent
SPACE = "MDD"
SCAN_DIRS = ("fixtures", "corpus")


def parse_frontmatter(path: Path) -> dict[str, Any]:
    """Return YAML frontmatter as a dict, or {} if absent or malformed."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    parsed = yaml.safe_load(m.group(1))
    return parsed if isinstance(parsed, dict) else {}


def first_h1(path: Path) -> str | None:
    """Return the first ATX or setext-form h1 title, or None if absent."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip()
        if i + 1 < len(lines) and line.strip() and re.fullmatch(r"=+\s*", lines[i + 1]):
            return line.strip()
    return None


def collect_targets(explicit: list[str]) -> list[Path]:
    """Return the .md files to consider, in deterministic order."""
    if explicit:
        return [Path(p).resolve() for p in explicit]
    paths: list[Path] = []
    for sub in SCAN_DIRS:
        root = REPO_ROOT / sub
        if not root.exists():
            continue
        paths.extend(sorted(root.rglob("*.md")))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help="optional explicit file paths (default: walk fixtures/ and corpus/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would happen without invoking mdd",
    )
    args = parser.parse_args()

    targets = collect_targets(args.files)

    found = 0
    pushed = 0
    skipped = 0
    failed = 0

    for md in targets:
        found += 1
        try:
            rel = md.relative_to(REPO_ROOT)
        except ValueError:
            rel = md

        fm = parse_frontmatter(md)
        page_id = fm.get("confluence", {}).get("page_id")
        if page_id:
            print(f"SKIP    {rel} (page_id={page_id})")
            skipped += 1
            continue

        title = first_h1(md)
        if not title:
            print(f"FAIL    {rel} — no '# H1' line to use as title")
            failed += 1
            continue

        cmd = [
            "mdd",
            "confluence",
            "create",
            "page",
            str(md),
            "--space",
            SPACE,
            "--title",
            title,
        ]

        if args.dry_run:
            print(f"DRY     {rel} → '{title}'")
            continue

        print(f"PUSH    {rel} → '{title}'")
        result = subprocess.run(cmd, cwd=REPO_ROOT)
        if result.returncode == 0:
            pushed += 1
        else:
            print(f"FAIL    {rel} (mdd exit {result.returncode})")
            failed += 1

    print()
    print(f"Found:   {found}")
    print(f"Skipped: {skipped} (already had page_id)")
    if args.dry_run:
        print(f"Would push: {found - skipped - failed}")
    else:
        print(f"Pushed:  {pushed}")
        print(f"Failed:  {failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
