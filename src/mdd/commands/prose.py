"""mdd prose — deterministic, model-free prose checks and fixers.

Nothing here reads a token, resolves an ``op://`` reference, opens a socket or
calls a model. That is what makes the group usable as a merge gate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from mdd.prose import config as prose_config
from mdd.prose import report, runner, walk
from mdd.prose.rules import Severity
from mdd.utils.config import ConfigError
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mdd.cli import CommonParents, SubParsers
    from mdd.prose.config import ProseConfig

log = get_logger(__name__)

_ADOPTION_WARNING = (
    "Turning reflow on in an existing repository produces one enormous diff: "
    "effectively every prose file changes. The recommended adoption path is one "
    "commit that does nothing but reflow, recorded in .git-blame-ignore-revs so "
    "git blame skips it."
)


class _ProseArgs(argparse.Namespace):
    paths: list[Path]
    json: bool
    min_severity: Literal["error", "warning"]
    no_excerpt: bool
    ignores: list[Path]
    config: Path | None
    write: bool
    allow_mirror: bool
    width: int | None
    min_line: int | None
    slug_style: str
    max_age: int | None
    as_of: dt.date | None
    only_missing: bool
    only_stale: bool
    prose_parser: argparse.ArgumentParser


def _iso_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"requires an ISO-8601 date (got {raw!r})") from exc


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"requires a positive integer (got {raw!r})") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"requires a positive integer (got {raw!r})")
    return value


def _apply_overrides(loaded: ProseConfig, args: _ProseArgs) -> ProseConfig:
    """Let the command line override the knobs it exposes."""
    reflow = loaded.reflow
    if args.width is not None:
        reflow = replace(reflow, width=args.width)
    if args.min_line is not None:
        reflow = replace(reflow, min_line=args.min_line)
    freshness = loaded.freshness
    if args.max_age is not None:
        freshness = replace(freshness, max_age_days=args.max_age)
    return replace(loaded, reflow=reflow, freshness=freshness)


def _freshness_only(args: _ProseArgs) -> str | None:
    if args.only_missing:
        return "missing"
    return "stale" if args.only_stale else None


def _gating(findings: Sequence[report.Finding], min_severity: str) -> bool:
    if min_severity == "warning":
        return bool(findings)
    return any(f.severity is Severity.ERROR for f in findings)


def _resolve_checks(requested: tuple[str, ...], loaded: ProseConfig) -> tuple[str, ...]:
    """A named subcommand runs its own check; ``check`` runs every enabled one."""
    return tuple(name for name in requested if name in loaded.enabled) or ()


def _execute(ns: argparse.Namespace, requested: tuple[str, ...], *, respect_enabled: bool) -> int:
    args = cast("_ProseArgs", ns)
    if args.write and args.json:
        # The parser is stashed on the namespace so this stays an argparse
        # usage error (exit 2) rather than a finding.
        args.prose_parser.error("--write cannot be combined with --json")
    try:
        loaded = _apply_overrides(prose_config.load(args.config), args)
    except ConfigError as exc:
        log.error("prose config: %s", exc)
        return 1

    for absent in walk.missing(args.paths):
        log.error("path does not exist: %s", absent)
        return 1

    checks = _resolve_checks(requested, loaded) if respect_enabled else requested
    if not checks:
        print(  # noqa: T201  # program output
            f"mdd prose: no enabled checks ({', '.join(requested)} disabled by config)",
            file=sys.stderr,
        )
        return 0

    files = walk.discover(args.paths, extra_ignores=tuple(args.ignores))
    result = runner.run(
        files,
        loaded,
        runner.RunOptions(
            checks=checks,
            write=args.write,
            allow_mirror=args.allow_mirror,
            as_of=args.as_of or dt.date.today(),
            freshness_only=_freshness_only(args),
        ),
    )
    findings = sorted(result.findings, key=report.sort_key)
    report.emit(findings, sys.stdout, json_mode=args.json, show_excerpt=not args.no_excerpt)
    command = "mdd prose " + (requested[0] if len(requested) == 1 else "check")
    print(report.summarise(command, findings, result.file_count), file=sys.stderr)  # noqa: T201  # program output
    if result.failed:
        return 1
    return 1 if _gating(findings, args.min_severity) else 0


def _run_reflow(ns: argparse.Namespace) -> int:
    return _execute(ns, ("reflow",), respect_enabled=False)


def _run_lint(ns: argparse.Namespace) -> int:
    return _execute(ns, ("lint",), respect_enabled=False)


def _run_anchors(ns: argparse.Namespace) -> int:
    return _execute(ns, ("anchors",), respect_enabled=False)


def _run_freshness(ns: argparse.Namespace) -> int:
    return _execute(ns, ("freshness",), respect_enabled=False)


def _run_check(ns: argparse.Namespace) -> int:
    return _execute(ns, ("reflow", "lint", "anchors", "freshness"), respect_enabled=True)


def _common_parent() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    _ = parent.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[],
        metavar="PATH",
        help="Files or directories to check (default: .)",
    )
    _ = parent.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object per finding (line-delimited, not an array)",
    )
    _ = parent.add_argument(
        "--min-severity",
        choices=("error", "warning"),
        default="error",
        help="Which severity makes the exit code non-zero (default: error)",
    )
    _ = parent.add_argument(
        "--no-excerpt",
        action="store_true",
        help="Omit the quoted source fragment, for jobs whose logs are broadly readable",
    )
    _ = parent.add_argument(
        "--ignore",
        dest="ignores",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Extra .mddignore file, unioned with the one at the walk root (repeatable)",
    )
    return parent


def _add_defaults(parser: argparse.ArgumentParser) -> None:
    """Give every subcommand the full namespace, so one handler can read it."""
    parser.set_defaults(
        write=False,
        allow_mirror=False,
        width=None,
        min_line=None,
        slug_style="github",
        max_age=None,
        as_of=None,
        only_missing=False,
        only_stale=False,
        prose_parser=parser,
    )


def _add_write_args(parser: argparse.ArgumentParser, *, what: str) -> None:
    _ = parser.add_argument(
        "--write",
        action="store_true",
        help=f"Apply the {what} in place (opt-in per invocation, never from config)",
    )
    _ = parser.add_argument(
        "--allow-mirror",
        action="store_true",
        help="Rewrite files whose frontmatter marks them as a Confluence/SharePoint mirror",
    )


def _register_reflow(
    sub: SubParsers, parent: argparse.ArgumentParser, config: argparse.ArgumentParser
) -> None:
    p = sub.add_parser(
        "reflow",
        parents=[parent, config],
        help="Check or apply semantic line breaks (one sentence per line)",
        description="Semantic-line-break reflow.\n\n" + _ADOPTION_WARNING,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_write_args(p, what="reflow")
    _ = p.add_argument(
        "--width",
        type=_positive_int,
        default=None,
        metavar="N",
        help=f"Soft target width, not a hard limit (default: {prose_config.DEFAULT_WIDTH})",
    )
    _ = p.add_argument(
        "--min-line",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            "Suppress a break that would leave a fragment shorter than N characters "
            f"(default: {prose_config.DEFAULT_MIN_LINE})"
        ),
    )
    _add_defaults(p)
    p.set_defaults(func=_run_reflow)


def _register_lint(
    sub: SubParsers, parent: argparse.ArgumentParser, config: argparse.ArgumentParser
) -> None:
    p = sub.add_parser(
        "lint",
        parents=[parent, config],
        help="Find mechanical slips a spell checker cannot see",
    )
    _add_write_args(p, what="whitespace fixes")
    _add_defaults(p)
    p.set_defaults(func=_run_lint)


def _register_anchors(
    sub: SubParsers, parent: argparse.ArgumentParser, config: argparse.ArgumentParser
) -> None:
    p = sub.add_parser(
        "anchors",
        parents=[parent, config],
        help="Check that every internal file.md#anchor link resolves",
    )
    _ = p.add_argument(
        "--slug-style",
        choices=("github",),
        default="github",
        help="Heading-slug rule to resolve anchors against (default: github)",
    )
    _add_defaults(p)
    p.set_defaults(func=_run_anchors)


def _register_freshness(
    sub: SubParsers, parent: argparse.ArgumentParser, config: argparse.ArgumentParser
) -> None:
    p = sub.add_parser(
        "freshness",
        parents=[parent, config],
        help="Check that each file carries a recent enough review date",
    )
    _ = p.add_argument(
        "--max-age",
        type=_positive_int,
        default=None,
        metavar="DAYS",
        help=f"Staleness threshold in days (default: {prose_config.DEFAULT_MAX_AGE_DAYS})",
    )
    _ = p.add_argument(
        "--as-of",
        type=_iso_date,
        default=None,
        metavar="DATE",
        help="Override today's date, so the check is reproducible",
    )
    group = p.add_mutually_exclusive_group()
    _ = group.add_argument(
        "--only-missing",
        action="store_true",
        help="Report only files with no review date at all",
    )
    _ = group.add_argument(
        "--only-stale",
        action="store_true",
        help="Report only files whose review date is too old",
    )
    _add_defaults(p)
    p.set_defaults(func=_run_freshness)


def _register_check(
    sub: SubParsers, parent: argparse.ArgumentParser, config: argparse.ArgumentParser
) -> None:
    p = sub.add_parser(
        "check",
        parents=[parent, config],
        help="Run every enabled check in one pass (the CI entry point)",
    )
    _ = p.add_argument(
        "--as-of",
        type=_iso_date,
        default=None,
        metavar="DATE",
        help="Override today's date for the freshness check",
    )
    _add_defaults(p)
    p.set_defaults(func=_run_check)


def register(subparsers: SubParsers, parents: CommonParents) -> None:
    p = subparsers.add_parser(
        "prose",
        help="Deterministic prose checks and semantic-line-break reflow",
        description=(
            "Deterministic, model-free checks over a Markdown corpus. "
            "No network, no credentials, no model — so it is safe as a merge gate."
        ),
    )
    sub = p.add_subparsers(dest="prose_command", metavar="<subcommand>")

    def _show_help(_ns: argparse.Namespace) -> int:
        p.print_help()
        return 0

    p.set_defaults(func=_show_help)
    parent = _common_parent()
    _register_reflow(sub, parent, parents.config_required)
    _register_lint(sub, parent, parents.config_required)
    _register_anchors(sub, parent, parents.config_required)
    _register_freshness(sub, parent, parents.config_required)
    _register_check(sub, parent, parents.config_required)
