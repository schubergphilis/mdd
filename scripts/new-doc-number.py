#!/usr/bin/env python3
"""Print the next free 2-digit document number under docs/<kind>/.

Usage:
    python3 scripts/new-doc-number.py <kind>

Where <kind> is one of: spec, research, plan.

Parses leading prefix-letter + digits from existing filenames and prints
the next free integer, zero-padded to 2 digits.

The prefix letter per kind: S for spec, P for plan, R for research.

Exit codes:
    0  — success.
    1  — argument or filesystem error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PREFIX = {"spec": "S", "plan": "P", "research": "R"}


def next_free_number(kind: str) -> int:
    """Return the next free document number for the given kind."""
    docs_dir = Path("docs") / kind
    if not docs_dir.is_dir():
        print(f"ERROR: directory '{docs_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    prefix = PREFIX[kind]
    pattern = re.compile(rf"^{prefix}(\d+)-")
    used: set[int] = set()
    for path in docs_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            used.add(int(match.group(1)))

    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the next free 2-digit document number under docs/<kind>/."
    )
    parser.add_argument(
        "kind",
        choices=list(PREFIX),
        help="Document kind: spec, research, or plan.",
    )
    args = parser.parse_args()

    number = next_free_number(args.kind)
    print(f"{number:02d}")


if __name__ == "__main__":
    main()
