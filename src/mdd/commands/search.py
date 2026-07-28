"""mdd search — ripgrep-backed mirror search command (spec S19).

By default search results are streamed: rg emits matches over stdout, the
streaming formatter writes them straight through to the user's terminal, and
the rg process is terminated as soon as ``--limit`` matches have been seen.

``--sort`` switches to the legacy buffered path: rg is drained fully, matches
are grouped by file, and the bulk formatter prints them in one shot.
"""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from mdd.search.color import Color
from mdd.search.filters import filter_blacklisted
from mdd.search.output import StreamingFormatter, write_output
from mdd.search.roots import MirrorRoot, resolve_roots
from mdd.search.sources import SOURCES, known_types_hint
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

log = get_logger(__name__)

_DEFAULT_TOTAL_LIMIT = 10
_DEFAULT_PER_FILE_LIMIT = 50
_DEFAULT_TYPE = "md"
_TYPE_CHOICES = ("md", "qmd", "all")
_COLOR_CHOICES = ("auto", "always", "never")
_TERMINATE_TIMEOUT_SECS = 2.0

_DESCRIPTION = (
    "Search across all configured mirror roots using ripgrep.\n"
    "Results stream by default — first matches print immediately, "
    "and rg stops as soon as --limit is reached.\n"
    "\nRequires: rg (ripgrep) on PATH.\n"
    "  Install: brew install ripgrep  OR  apt install ripgrep"
)


def _check_rg() -> bool:
    """Return True if ripgrep is available on PATH, else print error and return False."""
    if shutil.which("rg") is not None:
        return True
    log.error(
        "ripgrep (rg) is not installed or not on PATH.\n"
        "Install it with:\n"
        "  macOS:  brew install ripgrep\n"
        "  Debian: apt install ripgrep\n"
        "  Other:  https://github.com/BurntSushi/ripgrep#installation"
    )
    return False


_RG_TYPE_ARGS: dict[str, list[str]] = {
    "md": ["--type", "md"],
    # rg doesn't have a built-in qmd type; use glob
    "qmd": ["--glob", "*.qmd"],
    "all": ["--type", "md", "--glob", "*.qmd"],
}


def _build_rg_type_args(type_filter: str) -> list[str]:
    """Return the rg arguments for the given type filter."""
    return _RG_TYPE_ARGS.get(type_filter, ["--type", "md"])


def _build_rg_cmd(
    query: str,
    roots: list[MirrorRoot],
    *,
    type_filter: str,
    per_file_limit: int,
) -> list[str]:
    """Build the rg invocation."""
    cmd: list[str] = ["rg"]
    cmd.extend(_build_rg_type_args(type_filter))
    cmd.extend(["--max-count", str(per_file_limit)])
    cmd.extend(["-n", "--smart-case", "--with-filename", "--json", "--"])
    cmd.append(query)
    cmd.extend(str(r.path) for r in roots)
    return cmd


def _open_rg(cmd: list[str]) -> subprocess.Popen[str]:
    """Start a ripgrep subprocess with line-buffered text streams."""
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _trace_cmd(cmd: list[str]) -> None:
    """Log the rg invocation (used by --trace)."""
    log.info("[mdd search] %s", shlex.join(cmd))


def _terminate_proc(proc: subprocess.Popen[str]) -> None:
    """Shut down rg cleanly; SIGKILL only if it ignores SIGTERM."""
    if proc.stdout is not None:
        proc.stdout.close()
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_TERMINATE_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _drain_stderr(proc: subprocess.Popen[str]) -> str:
    if proc.stderr is None:
        return ""
    try:
        return proc.stderr.read() or ""
    finally:
        proc.stderr.close()


def _positive_int(raw: str) -> int:
    """argparse type: parse a positive integer; raise ArgumentTypeError otherwise."""
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"requires a positive integer (got {raw!r})") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"requires a positive integer (got {raw!r})")
    return value


def _run_streaming(cmd: list[str], consumer: StreamingFormatter) -> tuple[int, str]:
    """Drive rg in streaming mode; return (returncode, stderr)."""
    proc = _open_rg(cmd)
    assert proc.stdout is not None  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    try:
        for line in proc.stdout:
            if not consumer.consume(line):
                break
    finally:
        _terminate_proc(proc)
    stderr = _drain_stderr(proc)
    return proc.returncode, stderr


def _run_buffered(cmd: list[str]) -> tuple[int, str, str]:
    """Run rg to completion; return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def _source_filter(raw: str) -> tuple[str, str]:
    """argparse type: parse ``TYPE:ID`` into a (source_type, identifier) pair.

    The source type must be registered (see :mod:`mdd.search.sources`), so
    a typo — or a filter for a source this distribution does not ship —
    fails at parse time with the list of types that do exist.
    """
    source_type, sep, identifier = raw.partition(":")
    if not sep or not source_type or not identifier:
        raise argparse.ArgumentTypeError(f"requires TYPE:ID (got {raw!r})")
    if source_type.strip().lower() not in SOURCES:
        raise argparse.ArgumentTypeError(
            f"unknown source type {source_type!r}. {known_types_hint()}"
        )
    return source_type.strip().lower(), identifier


class _SearchArgs(argparse.Namespace):
    query: str
    spaces: list[str]
    sites: list[str]
    sources: list[tuple[str, str]]
    includes: list[Path]
    excludes: list[Path]
    type: Literal["md", "qmd", "all"]
    limit: int
    per_file_limit: int
    sort: bool
    include_frontmatter: bool
    json: bool
    exclude_blacklisted: bool
    blacklist: Path | None
    color: Literal["auto", "always", "never"]
    trace: bool


def _collect_source_filters(args: _SearchArgs) -> dict[str, list[str]]:
    """Fold --space / --site / --source into one source_type → identifiers map."""
    filters: dict[str, list[str]] = {}
    pairs = [
        *(("confluence", space) for space in args.spaces),
        *(("sharepoint", site) for site in args.sites),
        *args.sources,
    ]
    for source_type, identifier in pairs:
        filters.setdefault(source_type, []).append(identifier)
    return filters


def _resolve_search_roots(args: _SearchArgs) -> list[MirrorRoot]:
    """Resolve the mirror roots that match the user's filter/include/exclude flags."""
    roots = resolve_roots(
        extra_paths=args.includes or None,
        exclude_paths=args.excludes or None,
        source_filters=_collect_source_filters(args) or None,
    )

    if args.exclude_blacklisted:
        roots = filter_blacklisted(roots, blacklist_file=args.blacklist)
    return roots


def _run_sort_mode(  # noqa: PLR0913
    cmd: list[str],
    roots: list[MirrorRoot],
    *,
    json_mode: bool,
    include_frontmatter: bool,
    total_limit: int,
    query: str,
    color: Color,
) -> int:
    """Buffered/sorted path: run rg to completion, then format grouped output."""
    returncode, stdout, stderr = _run_buffered(cmd)
    if returncode == 2:
        log.error("ripgrep failed:\n%s", stderr.strip())
        return 1
    count = write_output(
        stdout,
        roots,
        json_mode=json_mode,
        include_frontmatter=include_frontmatter,
        total_limit=total_limit,
        color=color,
    )
    if count == 0 and not json_mode:
        print(f"No matches found for {query!r}")  # noqa: T201  # program output
    return 0 if count > 0 else 1


def _run_stream_mode(  # noqa: PLR0913
    cmd: list[str],
    roots: list[MirrorRoot],
    *,
    json_mode: bool,
    include_frontmatter: bool,
    total_limit: int,
    query: str,
    color: Color,
) -> int:
    """Streaming path: emit matches as rg produces them, stop at total_limit."""
    consumer = StreamingFormatter(
        roots,
        json_mode=json_mode,
        include_frontmatter=include_frontmatter,
        total_limit=total_limit,
        stream=sys.stdout,
        color=color,
    )
    returncode, stderr = _run_streaming(cmd, consumer)
    # returncode == 2 is a real rg error; only report it if we wrote nothing
    # (otherwise the user already saw partial results — the error was probably
    # a per-file decoding hiccup, not a fatal failure).
    if returncode == 2 and consumer.count == 0:
        log.error("ripgrep failed:\n%s", stderr.strip())
        return 1
    if consumer.count == 0 and not json_mode:
        print(f"No matches found for {query!r}")  # noqa: T201  # program output
    return 0 if consumer.count > 0 else 1


def _run_search(ns: argparse.Namespace) -> int:
    args = cast("_SearchArgs", ns)
    if not args.query:
        log.error("Query must not be empty")
        return 1

    if not _check_rg():
        return 1

    roots = _resolve_search_roots(args)
    if not roots:
        if not args.json:
            # program output for piping
            print("No configured mirror roots found. Use --include to add a search path.")  # noqa: T201
        return 0

    cmd = _build_rg_cmd(
        args.query, roots, type_filter=args.type, per_file_limit=args.per_file_limit
    )
    if args.trace:
        _trace_cmd(cmd)
    color = Color.detect(args.color, stream=sys.stdout)

    runner = _run_sort_mode if args.sort else _run_stream_mode
    return runner(
        cmd,
        roots,
        json_mode=args.json,
        include_frontmatter=args.include_frontmatter,
        total_limit=args.limit,
        query=args.query,
        color=color,
    )


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    _ = p.add_argument(
        "--space",
        dest="spaces",
        action="append",
        default=[],
        metavar="SPACE",
        help="Restrict to a Confluence space key (repeatable)",
    )
    _ = p.add_argument(
        "--site",
        dest="sites",
        action="append",
        default=[],
        metavar="SITE",
        help="Restrict to a SharePoint site name (repeatable)",
    )
    _ = p.add_argument(
        "--source",
        dest="sources",
        action="append",
        type=_source_filter,
        default=[],
        metavar="TYPE:ID",
        help=(
            "Restrict to one root of any registered source type, e.g. "
            "docs:my-repo (repeatable). --space and --site are shorthands "
            f"for the two built-ins. {known_types_hint()}"
        ),
    )
    _ = p.add_argument(
        "--include",
        dest="includes",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Add an extra search root for this run (repeatable)",
    )
    _ = p.add_argument(
        "--exclude",
        dest="excludes",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Remove a root from the search for this run (repeatable)",
    )


def _add_output_args(p: argparse.ArgumentParser) -> None:
    _ = p.add_argument(
        "--type",
        choices=_TYPE_CHOICES,
        default=_DEFAULT_TYPE,
        help="File filter: md (default), qmd, or all",
    )
    _ = p.add_argument(
        "--limit",
        type=_positive_int,
        default=_DEFAULT_TOTAL_LIMIT,
        metavar="N",
        help=(
            f"Cap total matches across all roots (default: {_DEFAULT_TOTAL_LIMIT}). "
            "rg is stopped as soon as the cap is reached."
        ),
    )
    _ = p.add_argument(
        "--per-file-limit",
        type=_positive_int,
        default=_DEFAULT_PER_FILE_LIMIT,
        metavar="N",
        help=f"Cap matches per file (default: {_DEFAULT_PER_FILE_LIMIT}; passed to rg --max-count)",
    )
    _ = p.add_argument(
        "--sort",
        action="store_true",
        help="Buffer all results and group by file before printing (no streaming)",
    )
    _ = p.add_argument(
        "--include-frontmatter",
        action="store_true",
        help="Include matches inside YAML frontmatter blocks",
    )
    _ = p.add_argument(
        "--json",
        action="store_true",
        help="Output one JSON record per match",
    )
    _ = p.add_argument(
        "--exclude-blacklisted",
        action="store_true",
        help="Skip blacklisted Confluence spaces / SharePoint sites",
    )
    _ = p.add_argument(
        "--blacklist",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to data-protection.yaml (overrides auto-discovery)",
    )
    _ = p.add_argument(
        "--color",
        choices=_COLOR_CHOICES,
        default="auto",
        help=(
            "Colorize human output (matches in bold red, file path in magenta, "
            "labels dim). 'auto' = on when stdout is a TTY. Honours NO_COLOR / FORCE_COLOR."
        ),
    )
    _ = p.add_argument(
        "--trace",
        action="store_true",
        help="Print the rg command to stderr before running it",
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    p = subparsers.add_parser(
        "search",
        help="Search across all configured mirror roots using ripgrep",
        description=_DESCRIPTION,
    )
    _ = p.add_argument("query", help='Search query (e.g. "laptop provisioning")')
    _add_filter_args(p)
    _add_output_args(p)
    p.set_defaults(func=_run_search)
