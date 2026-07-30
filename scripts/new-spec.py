#!/usr/bin/env python3
"""Scaffold a new spec document under docs/spec/.

Usage:
    python3 scripts/new-spec.py <slug>

Determines the next free spec number via new-doc-number.py, reads the
template from docs/spec/spec-template.md, writes docs/spec/S<NN>-<slug>.md,
and prints the path.

`--also PATH` (repeatable) is forwarded to new-doc-number.py verbatim —
see that script's docstring for why a wrapper repo needs it.

Exit codes:
    0  — success.
    1  — argument or filesystem error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def next_spec_number(also: list[Path]) -> str:
    """Return the next free spec number as a zero-padded 2-digit string."""
    argv = [sys.executable, str(Path(__file__).parent / "new-doc-number.py"), "spec"]
    for path in also:
        argv += ["--also", str(path)]
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def find_template() -> Path:
    """Return the path to docs/spec/spec-template.md."""
    template_path = Path("docs") / "spec" / "spec-template.md"
    if not template_path.is_file():
        print(f"ERROR: Template file '{template_path}' not found.", file=sys.stderr)
        sys.exit(1)
    return template_path


def build_spec_content(slug: str, number: str, template_path: Path) -> str:
    """Build the full content for the new spec file by substituting the title in the template."""
    title = slug.replace("-", " ").replace("_", " ").title()
    text = template_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith("# "):
        lines[0] = f"# S{number}: {title}\n"
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new spec document under docs/spec/.")
    parser.add_argument("slug", help="Short kebab-case slug for the spec (e.g. my-feature).")
    parser.add_argument(
        "--also",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="forwarded to new-doc-number.py: dir whose numbers also count as used",
    )
    args = parser.parse_args()

    slug: str = args.slug

    try:
        number = next_spec_number(args.also)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: failed to get next spec number: {exc.stderr}", file=sys.stderr)
        sys.exit(1)

    template_path = find_template()
    content = build_spec_content(slug, number, template_path)

    out_path = Path("docs") / "spec" / f"S{number}-{slug}.md"
    if out_path.exists():
        print(f"ERROR: '{out_path}' already exists.", file=sys.stderr)
        sys.exit(1)

    out_path.write_text(content, encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
