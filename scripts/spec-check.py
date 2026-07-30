"""spec-check: validate docs/spec/*.md files for hygiene issues.

Checks (per spec file, excluding 000-*.md):
1. Markdown well-formedness — unclosed code fences (odd triple-backtick count).
2. Broken sibling links — [text](NNN-foo.md) or [text](./NNN-foo.md) must exist.
3. Broken core-spec links — absolute GitHub URLs into the core's docs/spec/
   must name a spec file that exists in a reachable checkout of the core.
4. Presence of a `**Status:**` line.
5. Implemented-status format — `**Status:** Implemented` must be followed by a
   single `(YYYY-MM-DD)` parenthetical with no commit shas or extra prose.
6. API endpoint citation rule — bare REST API URLs outside code fences must be
   clickable Markdown links or have TBD: on the same line.

Run from a repo root; `docs/spec/` is resolved relative to the current working
directory, so downstream repos that vendor the `mdd` core can invoke this
script against their own specs.

Output: <file>:<line>: <category>: <detail>   (one line per violation)
Exit:   0 if clean, 1 if any violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SPEC_DIR = Path("docs/spec")

# Where a checkout of the open-source `mdd` core's specs may live. The first
# entry covers running inside the core itself; the second covers a wrapper repo
# that keeps the core as a sibling checkout and links into it by URL.
CORE_SPEC_DIRS = (SPEC_DIR, Path("../mdd/docs/spec"))

# Matches triple-backtick fence lines (optionally with a language tag).
FENCE_RE = re.compile(r"^```")

# Matches sibling-spec links: [text](SNN-foo.md) or [text](./SNN-foo.md)
# Excludes external URLs (http/https).
SIBLING_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\((\./)?(S\d{2}-[^)]+\.md)\)")

# Absolute links into the core repo's specs, as used by wrapper repos that no
# longer keep a mirrored copy of the spec they are citing. The ref is not
# pinned to `main` — a tag or sha is equally valid.
CORE_SPEC_URL_RE = re.compile(
    r"https://github\.com/schubergphilis/mdd/blob/[^/\s)]+/docs/spec/([^/\s)#]+\.md)"
)

# External API URL pattern: REST/API path on known hosts.
# Matches https://<host>/<api-segment>/v?<digit>... outside code fences.
# Also matches graph.microsoft.com at any path depth.
API_URL_RE = re.compile(
    r"https://[^\s\")>]+"
    r"(?:"
    r"/(?:wiki/api|rest/api|api/v\d|api/\d)"
    r"|graph\.microsoft\.com/(?:v\d+|beta)"
    r")[^\s\")>]*"
)

# Clickable link containing the URL: [text](URL)
LINKED_URL_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")

# Status-line shape. Captures the value after `**Status:**`.
STATUS_LINE_RE = re.compile(r"^\*\*Status:\*\*\s*(.*?)\s*$")

# Valid Implemented status: `Implemented (YYYY-MM-DD)` — date only, no shas.
IMPLEMENTED_OK_RE = re.compile(r"^Implemented \(\d{4}-\d{2}-\d{2}\)$")


def core_spec_names(spec_dirs: tuple[Path, ...] = CORE_SPEC_DIRS) -> set[str]:
    """Spec filenames reachable in any checkout of the core, for link resolution."""
    return {p.name for d in spec_dirs if d.is_dir() for p in d.glob("*.md")}


def link_violations(
    path: Path, lineno: int, line: str, sibling_names: set[str], core_names: set[str]
) -> list[str]:
    violations: list[str] = []

    for m in SIBLING_LINK_RE.finditer(line):
        target = m.group(2)
        if target not in sibling_names:
            violations.append(f"{path}:{lineno}: link: broken sibling link → {target}")

    for m in CORE_SPEC_URL_RE.finditer(line):
        target = m.group(1)
        if target not in core_names:
            violations.append(
                f"{path}:{lineno}: link: broken core spec link → {target}"
                f" (not found in {' or '.join(str(d) for d in CORE_SPEC_DIRS)})"
            )

    return violations


def api_cite_violations(path: Path, lineno: int, line: str) -> list[str]:
    # Collect all linked URLs on this line so we can exempt them.
    linked_on_line = {m.group(1) for m in LINKED_URL_RE.finditer(line)}

    violations: list[str] = []
    for m in API_URL_RE.finditer(line):
        url = m.group(0)
        if url in linked_on_line:
            # It is the href of a clickable link — OK.
            continue
        if "TBD:" in line[: m.start()]:
            # TBD: marker precedes the URL on this line — OK.
            continue
        violations.append(
            f"{path}:{lineno}: api-cite: bare API URL without link or TBD: marker: {url}"
        )

    return violations


def collect_violations(path: Path, sibling_names: set[str], core_names: set[str]) -> list[str]:
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"{path}: read: cannot read file: {e}"]

    lines = text.splitlines()
    in_fence = False
    fence_open_line = 0
    has_status = False
    fence_count = 0  # number of fence-open lines seen so far

    for lineno, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            if not in_fence:
                in_fence = True
                fence_open_line = lineno
                fence_count += 1
            else:
                in_fence = False

        # Status line check: `**Status:** <value>` per the new template.
        status_match = STATUS_LINE_RE.match(line.lstrip())
        if status_match:
            has_status = True
            value = status_match.group(1)
            if value.lower().startswith("implemented") and not IMPLEMENTED_OK_RE.match(value):
                violations.append(
                    f"{path}:{lineno}: status: Implemented status must be"
                    f' "Implemented (YYYY-MM-DD)" — got: {value!r}'
                )

        # Skip checks that don't apply inside fences.
        if in_fence:
            continue

        violations.extend(link_violations(path, lineno, line, sibling_names, core_names))
        violations.extend(api_cite_violations(path, lineno, line))

    # After scanning all lines: check for unclosed fence.
    if in_fence:
        violations.append(
            f"{path}:{fence_open_line}: fence: unclosed code fence"
            f" (opened at line {fence_open_line})"
        )

    # Status line check.
    if not has_status:
        violations.append(f"{path}: status: missing `**Status:**` line")

    return violations


def main() -> int:
    if not SPEC_DIR.is_dir():
        print(f"error: {SPEC_DIR} not found (run from repo root)", file=sys.stderr)
        return 1

    spec_files = sorted(SPEC_DIR.glob("*.md"))
    # Skip 000-* files (overview/shared-patterns — different conventions).
    targets = [p for p in spec_files if not p.name.startswith("000-")]

    # Build the set of existing spec filenames for sibling-link resolution.
    sibling_names = {p.name for p in spec_files}
    core_names = core_spec_names()

    all_violations: list[str] = []
    for path in targets:
        all_violations.extend(collect_violations(path, sibling_names, core_names))

    for v in all_violations:
        print(v)

    if all_violations:
        print(
            f"error: {len(all_violations)} violation(s) found in {len(targets)} spec files",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
