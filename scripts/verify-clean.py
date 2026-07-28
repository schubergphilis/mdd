"""verify-clean: exit non-zero if any tracked file contains git conflict markers."""

from __future__ import annotations

import subprocess
import sys

# Match git's actual conflict-marker shapes. The bare ``=======`` form
# is restricted to exactly 7 equals signs so it doesn't trip on setext
# heading underlines (``Title\n=================``), which are typically
# longer. The pattern names are split so this file does not match
# itself.
_EQ7 = "=" * 7
_LT7 = "<" * 7
_GT7 = ">" * 7


def _is_conflict_marker(line: str) -> bool:
    s = line.rstrip("\r\n")
    if s.startswith(_LT7 + " "):  # <<<<<<< HEAD / <<<<<<< branch
        return True
    if s.startswith(_GT7 + " "):  # >>>>>>> branch
        return True
    return s == _EQ7  # exactly seven equals — git's divider


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"error: git ls-files failed: {result.stderr}", file=sys.stderr)
        return 1

    tracked = [f for f in result.stdout.splitlines() if f]
    if not tracked:
        return 0

    found_any = False
    for path in tracked:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:  # noqa: PTH123
                for lineno, line in enumerate(fh, 1):
                    if _is_conflict_marker(line):
                        print(f"{path}:{lineno}: conflict marker found: {line.rstrip()}")
                        found_any = True
        except OSError:
            # Binary or unreadable files: skip silently.
            pass

    if found_any:
        print("error: conflict markers found in tracked files", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
