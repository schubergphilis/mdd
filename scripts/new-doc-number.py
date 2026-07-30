#!/usr/bin/env python3
"""Print the next free 2-digit document number under docs/<kind>/.

Usage:
    python3 scripts/new-doc-number.py <kind>

Where <kind> is one of: spec, research, plan.

Parses leading prefix-letter + digits from existing filenames and prints
the next free integer, zero-padded to 2 digits.

The prefix letter per kind: S for spec, P for plan, R for research.

A wrapper repo that keeps only some of a shared numbering space (e.g. a
handful of its own specs, citing the rest from this core by URL) can pass
`--also PATH` (repeatable) to fold another directory's numbers into the
"used" set — without that, this script only sees its own thin `docs/spec/`
and would suggest a number the core already owns. A missing `--also`
directory is skipped silently, so it's safe to pass one that doesn't
apply to every `kind` (e.g. a core with no `docs/plan/` at all).

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


def _used_numbers(docs_dir: Path, prefix: str) -> set[int]:
    """Return the set of document numbers already used in *docs_dir*, if it exists."""
    if not docs_dir.is_dir():
        return set()
    pattern = re.compile(rf"^{prefix}(\d+)-")
    used: set[int] = set()
    for path in docs_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            used.add(int(match.group(1)))
    return used


def next_free_number(kind: str, also: tuple[Path, ...] = ()) -> int:
    """Return the next free document number for *kind*, avoiding numbers used in *also* too."""
    docs_dir = Path("docs") / kind
    if not docs_dir.is_dir():
        print(f"ERROR: directory '{docs_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    prefix = PREFIX[kind]
    used = _used_numbers(docs_dir, prefix)
    for other in also:
        used |= _used_numbers(other, prefix)

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
    parser.add_argument(
        "--also",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="additional directory whose numbers also count as used (repeatable)",
    )
    args = parser.parse_args()

    number = next_free_number(args.kind, tuple(args.also))
    print(f"{number:02d}")


if __name__ == "__main__":
    main()
