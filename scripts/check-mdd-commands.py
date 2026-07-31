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

Reuse by a composing distribution
---------------------------------

A distribution that builds a superset CLI on top of this one — its own
subcommands injected through ``extra_commands``, its own backend, the same
``mdd`` command name — documents those extra subcommands in its own prose, and
wants the same gate over it. Two flags make that work; it runs this script
straight out of a sibling checkout of this repository, as it does the other
shared dev scripts here.

``--repo-root PATH``
    The tree to scan. Defaults to the current working directory, so the
    ordinary invocation from a repository root needs no flag. Paths in the
    violation output stay relative to this root, so ``file:line:`` prefixes
    remain clickable from that repository. Directories in the scanned set that
    do not exist are skipped silently — a consuming repository is not expected
    to have all of ``docs/guide``, ``docs/articles`` and ``docs/reference``.
    Finding no prose files at all is an error, not a vacuous pass.

``--dispatcher MODULE:CALLABLE``
    The parser factory to introspect, defaulting to
    ``mdd.cli:build_dispatcher``. A composing distribution points this at its
    own factory; without it the check knows only this distribution's command
    tree and would report every one of the consumer's own subcommands as
    invalid. The callable must take no arguments and return an
    ``argparse.ArgumentParser``. Note what this flag is: an import and call of
    code named on the command line. That is deliberate and it is the only way
    to keep introspecting a real parser rather than scraping ``--help`` text,
    but it means the value must come from the repository being checked — this
    is a development gate a repository runs over itself, not a tool to point at
    input you do not trust.

Exit codes: 0 — clean (or an advisory ``--all`` run); 1 — violations found;
2 — usage error (bad ``--dispatcher``, or a root with no prose in it).
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import itertools
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Sequence

DEFAULT_DISPATCHER = "mdd.cli:build_dispatcher"

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


class DispatcherError(Exception):
    """A ``--dispatcher`` value that could not be turned into a parser."""


def load_dispatcher(spec: str) -> argparse.ArgumentParser:
    """Import ``MODULE:CALLABLE`` and call it to get the parser to introspect.

    The callable takes no arguments and returns an ``argparse.ArgumentParser``.
    This imports and executes the named code: the value is expected to name the
    parser factory of the repository being checked.
    """
    module_name, sep, attr = spec.partition(":")
    if not module_name or not sep or not attr:
        raise DispatcherError(f"expected MODULE:CALLABLE, got {spec!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DispatcherError(f"cannot import module {module_name!r}: {exc}") from exc
    factory: object = getattr(module, attr, None)
    if factory is None:
        raise DispatcherError(f"module {module_name!r} has no attribute {attr!r}")
    if not callable(factory):
        raise DispatcherError(f"{spec} is not callable")
    parser: object = factory()
    if not isinstance(parser, argparse.ArgumentParser):
        raise DispatcherError(f"{spec}() returned {type(parser).__name__}, not an ArgumentParser")
    return parser


@dataclass(frozen=True)
class CommandNode:
    """The valid subcommands and long options at one point in the mdd command tree."""

    children: frozenset[str]
    options: frozenset[str]


def build_command_tree(dispatcher: argparse.ArgumentParser) -> dict[tuple[str, ...], CommandNode]:
    """Introspect *dispatcher*'s argparse tree into a path -> (subcommands, options) map."""
    tree: dict[tuple[str, ...], CommandNode] = {}
    _walk_parser(dispatcher, (), tree)
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
    parser = argparse.ArgumentParser(
        description="Verify every `mdd ...` string in prose against the real CLI."
    )
    _ = parser.add_argument(
        "--all",
        action="store_true",
        help="Also scan docs/spec and docs/research; advisory only, always exits 0",
    )
    _ = parser.add_argument(
        "--repo-root",
        type=Path,
        metavar="PATH",
        help="Tree to scan, and the root output paths are relative to (default: cwd)",
    )
    _ = parser.add_argument(
        "--dispatcher",
        default=DEFAULT_DISPATCHER,
        metavar="MODULE:CALLABLE",
        help=(
            "No-argument factory returning the argparse parser to check against "
            f"(default: {DEFAULT_DISPATCHER}). Imports and calls the named code, so "
            "it must name the parser factory of the repository being checked."
        ),
    )
    return parser.parse_args(argv)


def _report(violations: list[Violation], invocations_seen: int, files_seen: int, root: Path) -> int:
    for violation in violations:
        print(_format_violation(violation, root))
    if violations:
        print(
            f"check-mdd-commands: {len(violations)} invalid `mdd ...` string(s) found",
            file=sys.stderr,
        )
        return 1
    print(
        f"check-mdd-commands: {invocations_seen} `mdd ...` string(s) checked "
        f"across {files_seen} file(s), all resolve"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root: Path = (args.repo_root if args.repo_root is not None else Path.cwd()).resolve()
    try:
        tree = build_command_tree(load_dispatcher(args.dispatcher))
    except DispatcherError as exc:
        print(f"check-mdd-commands: --dispatcher: {exc}", file=sys.stderr)
        return 2

    files = discover_files(root, include_advisory=args.all)
    if not files:
        print(
            f"check-mdd-commands: no prose files found under {root} — "
            "run from a repository root, or pass --repo-root PATH",
            file=sys.stderr,
        )
        return 2
    invocations = [inv for file in files for inv in scan_file(file)]
    violations = [v for inv in invocations if (v := _violation_for(inv, tree)) is not None]

    if args.all:
        _print_advisory_report(violations, root)
        print(
            f"\ncheck-mdd-commands --all: {len(violations)} advisory hit(s) "
            f"across {len(files)} file(s) (not enforced)"
        )
        return 0
    return _report(violations, len(invocations), len(files), root)


if __name__ == "__main__":
    sys.exit(main())
