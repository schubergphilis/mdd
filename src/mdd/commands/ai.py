"""mdd ai — AI-powered rewrite / index / review commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.ai.client import Client
    from mdd.cli import CommonParents, SubParsers

log = get_logger(__name__)


def _load_client_or_exit() -> Client | int:
    """Construct the AI client; return the client or an int exit code on error."""
    # lazy import: mdd.ai.client transitively pulls in openai (heavy); keep CLI startup fast
    from mdd.ai.client import Client  # noqa: PLC0415
    from mdd.ai.models import AiError  # noqa: PLC0415

    try:
        return Client()
    except AiError as exc:
        log.error("AI config: %s", exc)
        return 1


# ---------------------------------------------------------------------------
# rewrite subcommand
# ---------------------------------------------------------------------------


class _AiRewriteArgs(argparse.Namespace):
    files: list[Path]
    style: Path | None
    apply: bool
    model: str | None


class _AiIndexArgs(argparse.Namespace):
    directory: Path
    depth: Literal["1", "all"]
    apply: bool
    model: str | None


class _AiReviewArgs(argparse.Namespace):
    directory: Path
    duplicates: bool
    inconsistencies: bool
    stale: bool
    all_modes: bool
    top_k: int
    similarity: float
    age: int
    output: Path | None
    model: str | None


def _run_rewrite(ns: argparse.Namespace) -> int:
    args = cast("_AiRewriteArgs", ns)

    if args.style is not None and not args.style.exists():
        log.error("style file not found: %s", args.style)
        return 1

    for p in args.files:
        if not p.exists():
            log.error("file not found: %s", p)
            return 1

    client = _load_client_or_exit()
    if isinstance(client, int):
        return client

    # lazy import: transitively pulls in openai via mdd.ai.client
    from mdd.ai.rewrite import print_run_summary, rewrite_files  # noqa: PLC0415

    results = rewrite_files(
        args.files,
        client,
        style_path=args.style,
        apply=args.apply,
        model=args.model,
    )
    print_run_summary(results, client)
    return 1 if any(r.status == "error" for r in results) else 0


# ---------------------------------------------------------------------------
# index subcommand
# ---------------------------------------------------------------------------


def _run_index(ns: argparse.Namespace) -> int:
    args = cast("_AiIndexArgs", ns)

    if not args.directory.is_dir():
        log.error("not a directory: %s", args.directory)
        return 1

    client = _load_client_or_exit()
    if isinstance(client, int):
        return client

    # lazy import: transitively pulls in openai via mdd.ai.client
    from mdd.ai.index import index_dir, print_run_summary  # noqa: PLC0415

    result = index_dir(
        args.directory,
        client,
        depth=args.depth,
        apply=args.apply,
        model=args.model,
    )
    print_run_summary(result, client)
    return 0 if result.status == "ok" else 1


# ---------------------------------------------------------------------------
# review subcommand
# ---------------------------------------------------------------------------


def _review_modes(args: _AiReviewArgs) -> set[str]:
    modes: set[str] = set()
    if args.all_modes or args.duplicates:
        modes.add("duplicates")
    if args.all_modes or args.inconsistencies:
        modes.add("inconsistencies")
    if args.all_modes or args.stale:
        modes.add("stale")
    return modes


def _run_review(ns: argparse.Namespace) -> int:
    args = cast("_AiReviewArgs", ns)
    modes = _review_modes(args)
    if not modes:
        log.error(
            "'review' requires at least one mode flag: "
            "--duplicates, --inconsistencies, --stale, or --all"
        )
        return 1

    if not args.directory.is_dir():
        log.error("not a directory: %s", args.directory)
        return 1

    client = _load_client_or_exit()
    if isinstance(client, int):
        return client

    # lazy import: transitively pulls in openai via mdd.ai.client
    from mdd.ai.judges import ReviewSummary  # noqa: PLC0415
    from mdd.ai.review import ReviewConfig, print_run_summary, run_review  # noqa: PLC0415

    cfg = ReviewConfig(
        directory=args.directory,
        modes=modes,
        top_k=args.top_k,
        similarity=args.similarity,
        age_days=args.age,
        output_path=args.output,
        model=args.model,
    )

    try:
        report_path = run_review(cfg, client)
    except Exception as exc:
        log.exception("review: %s", exc)
        return 1

    summary = ReviewSummary(
        api_calls=client.summary.api_calls,
        cached_calls=client.summary.cached_calls,
    )
    print_run_summary(report_path, summary)
    return 0


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    ai = subparsers.add_parser(
        "ai",
        help="AI-powered rewrite / index / review commands (requires LiteLLM token)",
        description=(
            "AI-powered helpers driven by LiteLLM. Requires `ai.api_token` (and "
            "usually `ai.base_url`) in configs/ai.yaml or ~/.config/mdd/ai.yaml; "
            "the token may be an `op://` reference resolved via the 1Password CLI."
        ),
    )
    sub = ai.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    p_rewrite = sub.add_parser(
        "rewrite",
        help="Rewrite markdown file(s) for clarity and tone",
        description=(
            "Rewrite markdown file(s) for clarity and tone. Default output is "
            "<file>.rewrite.md alongside the source; --apply overwrites in place."
        ),
    )
    _ = p_rewrite.add_argument("files", nargs="+", type=Path, help="One or more markdown files")
    _ = p_rewrite.add_argument(
        "--style",
        type=Path,
        default=None,
        metavar="PROMPT_FILE",
        help="Override the default tone-of-voice prompt file",
    )
    _ = p_rewrite.add_argument(
        "--apply",
        action="store_true",
        help="Overwrite the source file in place (atomic rename)",
    )
    _ = p_rewrite.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Override the model (default: ai.models.default)",
    )
    p_rewrite.set_defaults(func=_run_rewrite)

    p_index = sub.add_parser(
        "index",
        help="Walk a directory and generate INDEX.md with per-page summaries",
        description=(
            "Walk a directory recursively and produce INDEX.md. Without --apply, "
            "the proposed INDEX.md is printed to stdout."
        ),
    )
    _ = p_index.add_argument("directory", type=Path, help="Directory to index")
    _ = p_index.add_argument(
        "--depth",
        choices=("1", "all"),
        default="1",
        help="Index depth: 1 (flat page list, default) or all (topic-clustered)",
    )
    _ = p_index.add_argument(
        "--apply",
        action="store_true",
        help="Write INDEX.md and update source frontmatter",
    )
    _ = p_index.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Override the model",
    )
    p_index.set_defaults(func=_run_index)

    p_review = sub.add_parser(
        "review",
        help="Cross-page review: duplicates, inconsistencies, stale content",
        description=(
            "Review a markdown mirror for duplicates, inconsistencies, and stale "
            "content. Writes a markdown report to docs/review/ unless --output is "
            "given. At least one mode flag is required (or --all)."
        ),
    )
    _ = p_review.add_argument("directory", type=Path, help="Directory to review")
    _ = p_review.add_argument(
        "--duplicates",
        action="store_true",
        help="Find pages with substantially overlapping content",
    )
    _ = p_review.add_argument(
        "--inconsistencies",
        action="store_true",
        help="Find pairs with contradictory factual claims",
    )
    _ = p_review.add_argument(
        "--stale",
        action="store_true",
        help="Find pages superseded by newer content",
    )
    _ = p_review.add_argument(
        "--all",
        dest="all_modes",
        action="store_true",
        help="Run all three modes (shares one BM25 index)",
    )
    _ = p_review.add_argument(
        "--top-k",
        type=int,
        default=5,
        metavar="N",
        help="Number of BM25 candidates per page (default: 5)",
    )
    _ = p_review.add_argument(
        "--similarity",
        type=float,
        default=0.85,
        help="Min BM25 score for duplicate shortlist (default: 0.85)",
    )
    _ = p_review.add_argument(
        "--age",
        type=int,
        default=365,
        metavar="DAYS",
        help="Age threshold in days for stale detection (default: 365)",
    )
    _ = p_review.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write report to this path instead of docs/review/",
    )
    _ = p_review.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Override the model",
    )
    p_review.set_defaults(func=_run_review)
