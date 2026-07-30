"""check-mdd-commands: verify every `mdd …` string in prose against the real CLI.

The command tree is built by introspecting the argparse parser assembled by
``mdd.cli.build_dispatcher`` — never by shelling out to ``mdd --help`` and
scraping text — so the check tracks the actual code, not a copy of it.

Scanned sources, per file:

1. Inline code spans, e.g. `` `mdd confluence sync-space <space-key>` ``.
2. Fenced code blocks whose language is ``bash``, ``sh``, ``shell``,
   ``console``, or absent. ``$ `` prompts and trailing ``\\`` line
   continuations are handled.

Bare prose outside a code span is never scanned: distinguishing "the `mdd`
tool does X" from a literal invocation in free text is not reliable enough to
justify blocking CI on it, so that class of sentence is left alone entirely.

A candidate string only counts as an invocation when the token following
`mdd` looks like a subcommand (``[a-z][a-z0-9-]*``) or an option (starts with
``-``); a bare `` `mdd` `` reference to the project name is not a command and
is skipped.

Within a candidate invocation, the longest leading run of tokens that are
neither options nor placeholders is walked against the command tree. A
placeholder — ``<...>``, ``[...]``, ``{...}``, ``...``/``…``, an ALL-CAPS
word, or a ``$VAR`` — ends the walk without being validated itself. A
``a|b|c`` alternation (used in prose to mean "one of these subcommands") is
accepted when every alternative names a real child of the current node. Long
options (``--foo``) found after the walk are checked against the resolved
command's own parser; short options are not validated.

Output: one ``file:line: `mdd ...` — reason`` line per violation, with a
``did you mean`` suggestion from the closest real name when one exists.

By default only prose that documents *current* behaviour is scanned — the
top-level docs plus ``docs/guide``, ``docs/articles``, ``docs/reference`` —
and the check exits 1 on any violation. Specs and research notes are excluded
from that default: they record design intent as it stood at the time of
writing, including proposals that were rejected or never built and command
names from before a later rename, so holding that prose to "resolves against
today's CLI" would falsify the historical record rather than correct it.
Pass ``--all`` to additionally scan ``docs/spec`` and ``docs/research`` and
print every hit found there; that run is advisory and always exits 0.
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.cli import build_dispatcher

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

PROSE_FILES = ("README.md", "docs/README.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md")
PROSE_DIRS = ("docs/guide", "docs/articles", "docs/reference")
ADVISORY_DIRS = ("docs/spec", "docs/research")

FENCE_LANGS = frozenset({"bash", "sh", "shell", "console", ""})
FENCE_RE = re.compile(r"^ {0,3}```\s*([A-Za-z0-9_+-]*)\s*$")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
STATEMENT_SPLIT_RE = re.compile(r"&&|\|\||\||;")
PROMPT_PREFIX_RE = re.compile(r"^\$\s*")
RUN_PREFIX_RE = re.compile(r"^(?:uv\s+run\s+|uv\s+tool\s+run\s+)")
SUBCOMMAND_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PLACEHOLDER_LITERALS = frozenset({"...", "…"})
BRACKET_PAIRS = (("<", ">"), ("[", "]"), ("{", "}"))


# ---------------------------------------------------------------------------
# The real command tree, introspected from argparse.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandNode:
    """The valid subcommands and long options at one point in the mdd command tree."""

    children: frozenset[str]
    options: frozenset[str]


def build_command_tree() -> dict[tuple[str, ...], CommandNode]:
    """Introspect ``mdd``'s argparse tree into a path -> (subcommands, options) map."""
    tree: dict[tuple[str, ...], CommandNode] = {}
    _walk_parser(build_dispatcher(), (), tree)
    return tree


def _walk_parser(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...],
    tree: dict[tuple[str, ...], CommandNode],
) -> None:
    sub_action = _subparsers_action(parser)
    children = frozenset(sub_action.choices) if sub_action is not None else frozenset()
    tree[path] = CommandNode(children=children, options=_long_options(parser))
    if sub_action is None:
        return
    for name, subparser in sub_action.choices.items():
        _walk_parser(subparser, (*path, name), tree)


def _subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser] | None:  # pyright: ignore[reportPrivateUsage]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):  # pyright: ignore[reportPrivateUsage]
            return action
    return None


def _long_options(parser: argparse.ArgumentParser) -> frozenset[str]:
    return frozenset(
        opt for action in parser._actions for opt in action.option_strings if opt.startswith("--")
    )


# ---------------------------------------------------------------------------
# Scanning prose for candidate `mdd ...` invocations.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Invocation:
    """A candidate `mdd ...` string found in prose, ready for validation."""

    file: Path
    line: int
    text: str
    tokens: tuple[str, ...]


def discover_files(root: Path, *, include_advisory: bool = False) -> list[Path]:
    """List every prose file the check scans, skipping directories that don't exist yet.

    With *include_advisory*, also lists ``docs/spec`` and ``docs/research`` — the
    design record, scanned only for the advisory ``--all`` run.
    """
    files: list[Path] = [root / name for name in PROSE_FILES if (root / name).is_file()]
    dirs = (*PROSE_DIRS, *ADVISORY_DIRS) if include_advisory else PROSE_DIRS
    for rel in dirs:
        base = root / rel
        if base.is_dir():
            files.extend(sorted(base.rglob("*.md")))
    return files


def scan_file(path: Path) -> list[Invocation]:
    """Find every candidate `mdd ...` invocation in one Markdown file."""
    return list(_scan_text(path, path.read_text(encoding="utf-8")))


def _scan_text(path: Path, text: str) -> Iterator[Invocation]:
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        fence = FENCE_RE.match(lines[idx])
        if fence is not None:
            idx = yield from _scan_fence(path, lines, idx, fence.group(1).lower())
            continue
        yield from _scan_prose_line(path, lines[idx], idx + 1)
        idx += 1


def _scan_fence(
    path: Path, lines: list[str], start_idx: int, lang: str
) -> Generator[Invocation, None, int]:
    idx = start_idx + 1
    content_start_line = idx + 1
    block_lines: list[str] = []
    while idx < len(lines) and not FENCE_RE.match(lines[idx]):
        block_lines.append(lines[idx])
        idx += 1
    if idx < len(lines):
        idx += 1  # skip the closing fence line
    if lang in FENCE_LANGS:
        yield from _scan_shell_block(path, block_lines, content_start_line)
    return idx


def _scan_shell_block(path: Path, block_lines: list[str], start_line: int) -> Iterator[Invocation]:
    for line_no, logical in _join_continuations(block_lines, start_line):
        for statement in STATEMENT_SPLIT_RE.split(logical):
            tokens = _extract_invocation_tokens(statement)
            if tokens is not None:
                yield Invocation(path, line_no, "mdd " + " ".join(tokens), tokens)


def _scan_prose_line(path: Path, line: str, line_no: int) -> Iterator[Invocation]:
    for match in INLINE_CODE_RE.finditer(line):
        tokens = _extract_invocation_tokens(match.group(1))
        if tokens is not None:
            yield Invocation(path, line_no, "mdd " + " ".join(tokens), tokens)


def _join_continuations(block_lines: list[str], start_line: int) -> list[tuple[int, str]]:
    """Join `\\`-continued shell lines, keeping the first physical line number."""
    result: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_start = start_line
    for offset, raw in enumerate(block_lines):
        line_no = start_line + offset
        stripped = raw.rstrip()
        continued = stripped.endswith("\\")
        if not buf:
            buf_start = line_no
        buf.append(stripped[:-1] if continued else stripped)
        if not continued:
            result.append((buf_start, " ".join(buf)))
            buf = []
    if buf:
        result.append((buf_start, " ".join(buf)))
    return result


def _extract_invocation_tokens(raw: str) -> tuple[str, ...] | None:
    """Return the tokens after `mdd` if *raw* looks like an mdd invocation, else None."""
    stripped = RUN_PREFIX_RE.sub("", PROMPT_PREFIX_RE.sub("", raw.strip()))
    tokens = stripped.split()
    if len(tokens) < 2 or tokens[0] != "mdd":
        return None
    nxt = tokens[1]
    looks_like_command = (
        nxt.startswith("-") or SUBCOMMAND_TOKEN_RE.match(nxt) or _is_placeholder(nxt) or "|" in nxt
    )
    return tuple(tokens[1:]) if looks_like_command else None


def _strip_wrapping_quotes(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _is_placeholder(raw_tok: str) -> bool:
    tok = _strip_wrapping_quotes(raw_tok)
    if tok in PLACEHOLDER_LITERALS:
        return True
    if tok.startswith("$") and len(tok) > 1:
        return True
    if any(tok.startswith(open_) and tok.endswith(close) for open_, close in BRACKET_PAIRS):
        return True
    return bool(tok) and tok.isupper() and any(ch.isalpha() for ch in tok)


# ---------------------------------------------------------------------------
# Validating a candidate invocation against the command tree.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkResult:
    """Where an invocation's token walk stopped, and why -- if it failed."""

    path: tuple[str, ...]
    remainder: tuple[str, ...]
    error: str | None
    bad_token: str | None
    candidates: tuple[str, ...]


def validate_invocation(
    tokens: Sequence[str], tree: dict[tuple[str, ...], CommandNode]
) -> WalkResult | None:
    """Validate one invocation's tokens against *tree*. None means it resolves cleanly."""
    walk = _walk_path(tokens, tree)
    if walk.error is not None:
        return walk
    return _check_options(walk.path, walk.remainder, tree)


def _alternatives_valid(tok: str, children: frozenset[str]) -> bool:
    if "|" not in tok:
        return False
    parts = tok.split("|")
    return bool(parts) and all(part in children for part in parts)


def _walk_path(tokens: Sequence[str], tree: dict[tuple[str, ...], CommandNode]) -> WalkResult:
    path: list[str] = []
    node = tree[()]
    idx = 0
    while idx < len(tokens):
        if not node.children:
            # A leaf command has no further subcommands to walk into, so whatever
            # remains is positional argument text (a file path, a quoted title, a
            # bracketed placeholder group, a trailing comment, ...), not a path
            # segment we can validate.
            break
        tok = tokens[idx]
        if tok.startswith("-") or _is_placeholder(tok):
            break
        if _alternatives_valid(tok, node.children):
            idx += 1
            break
        if tok not in node.children:
            return WalkResult(
                path=tuple(path),
                remainder=tuple(tokens[idx:]),
                error="unknown subcommand",
                bad_token=tok,
                candidates=tuple(sorted(node.children)),
            )
        path.append(tok)
        node = tree[tuple(path)]
        idx += 1
    return WalkResult(
        path=tuple(path), remainder=tuple(tokens[idx:]), error=None, bad_token=None, candidates=()
    )


def _check_options(
    path: tuple[str, ...],
    remainder: Sequence[str],
    tree: dict[tuple[str, ...], CommandNode],
) -> WalkResult | None:
    node = tree[path]
    for tok in remainder:
        if not tok.startswith("--") or _is_placeholder(tok):
            continue
        opt = tok.split("=", 1)[0]
        if opt not in node.options:
            return WalkResult(
                path=path,
                remainder=(),
                error="unknown option",
                bad_token=opt,
                candidates=tuple(sorted(node.options)),
            )
    return None


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One `mdd ...` string that failed to resolve against the command tree."""

    file: Path
    line: int
    text: str
    reason: str
    suggestion: str | None


def _closest_suggestion(result: WalkResult) -> str | None:
    if result.bad_token is None or not result.candidates:
        return None
    matches = difflib.get_close_matches(result.bad_token, result.candidates, n=1)
    if not matches:
        return None
    return " ".join((*result.path, matches[0]))


def _violation_for(inv: Invocation, tree: dict[tuple[str, ...], CommandNode]) -> Violation | None:
    result = validate_invocation(inv.tokens, tree)
    if result is None:
        return None
    reason = f"{result.error} `{result.bad_token}`"
    return Violation(inv.file, inv.line, inv.text, reason, _closest_suggestion(result))


def _violation_detail(violation: Violation) -> str:
    hint = f" (did you mean `mdd {violation.suggestion}`?)" if violation.suggestion else ""
    return f"{violation.line}: `{violation.text}` — {violation.reason}{hint}"


def _format_violation(violation: Violation, root: Path) -> str:
    rel = violation.file.relative_to(root)
    return f"{rel}:{_violation_detail(violation)}"


def _print_advisory_report(violations: list[Violation], root: Path) -> None:
    print(
        "ADVISORY — docs/spec/** and docs/research/** record design intent as it stood\n"
        "at the time of writing. These hits are informational only and never fail the build."
    )
    for file, group in itertools.groupby(violations, key=lambda v: v.file):
        print(f"\n{file.relative_to(root)}:")
        for violation in group:
            print(f"  {_violation_detail(violation)}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--all",
        action="store_true",
        help="Also scan docs/spec and docs/research; advisory only, always exits 0",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    tree = build_command_tree()
    files = discover_files(REPO_ROOT, include_advisory=args.all)
    invocations = [inv for file in files for inv in scan_file(file)]
    violations = [v for inv in invocations if (v := _violation_for(inv, tree)) is not None]

    if args.all:
        _print_advisory_report(violations, REPO_ROOT)
        print(
            f"\ncheck-mdd-commands --all: {len(violations)} advisory hit(s) "
            f"across {len(files)} file(s) (not enforced)"
        )
        return 0

    for violation in violations:
        print(_format_violation(violation, REPO_ROOT))
    if violations:
        print(
            f"check-mdd-commands: {len(violations)} invalid `mdd ...` string(s) found",
            file=sys.stderr,
        )
        return 1
    print(
        f"check-mdd-commands: {len(invocations)} `mdd ...` string(s) checked "
        f"across {len(files)} file(s), all resolve"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
