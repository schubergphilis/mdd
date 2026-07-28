"""mdd confluence — Confluence Cloud integration (spec S09/014)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

from mdd.confluence.apply import ApplyError
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.config import load as load_config
from mdd.confluence.create import create_page
from mdd.confluence.export import default_output_for_space, export_page
from mdd.confluence.managed import load_managed_config
from mdd.confluence.mutate import (
    MutateOptions,
    archive_page,
    move_page,
    rename_page,
    unarchive_page,
)
from mdd.confluence.sync import SyncOptions, sync_space
from mdd.confluence.update import update_page
from mdd.confluence.url import URLMismatchError
from mdd.confluence.url import parse as parse_url
from mdd.confluence.whoami import cmd_whoami
from mdd.mirror.hints import clone_hint
from mdd.utils.config import ConfigError
from mdd.utils.logging import get_logger
from mdd.utils.mddignore import MddIgnore
from mdd.utils.secrets import SecretError

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers
    from mdd.confluence.config import ConfluenceConfig
    from mdd.confluence.sync import SyncSummary

log = get_logger(__name__)


def _load_config_or_exit(config_path: Path | None) -> ConfluenceConfig | int:
    """Load Confluence config or return exit code with an error message."""
    try:
        return load_config(config_path)
    except ConfigError as exc:
        log.error("config: %s", exc)
        return 1
    except SecretError as exc:
        log.error("secret: %s", exc)
        return 1


# ---------------------------------------------------------------------------
# Namespace subclasses (S35 §"Typed Namespace adapter")
# ---------------------------------------------------------------------------


class _ExportPageArgs(argparse.Namespace):
    config: Path | None
    output: Path | None
    page_ref: str
    include_export_header: bool
    skip_attachments: bool


class _UpdatePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    message: str
    yes: bool
    allow_empty: bool
    allow_shrink: bool
    dry_run: bool


class _CreatePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    space: str | None
    parent: str | None
    title: str | None
    message: str


class _SyncSpaceArgs(argparse.Namespace):
    config: Path | None
    space_key: str
    output: Path | None
    no_delete: bool
    push: bool
    message: str | None
    head: int | None
    max_attachment_size: float | None
    skip_attachments: bool
    read_only: bool
    ignore: list[Path] | None
    prune_ignored: bool
    dry_run: bool


class _RenamePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    new_title: str
    message: str
    yes: bool
    no_commit: bool
    dry_run: bool


class _MovePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    parent: str
    message: str
    yes: bool
    no_commit: bool
    dry_run: bool


class _ArchivePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    message: str
    yes: bool
    no_commit: bool
    dry_run: bool


class _UnarchivePageArgs(argparse.Namespace):
    config: Path | None
    md_path: Path
    message: str
    yes: bool
    no_commit: bool
    dry_run: bool


class _WhoamiArgs(argparse.Namespace):
    config: Path | None


# ---------------------------------------------------------------------------
# export-page
# ---------------------------------------------------------------------------


def _resolve_page_id(
    client: ConfluenceClient, page_ref_str: str, config_host: str | None
) -> str | int:
    """Return the page_id for ``page_ref_str``, following short-URL redirects if needed."""
    try:
        page_ref = parse_url(page_ref_str, expected_host=config_host)
    except URLMismatchError as exc:
        log.error("URL mismatch: %s", exc)
        return 1
    except ValueError as exc:
        log.error("invalid page reference: %s", exc)
        return 1

    if page_ref.page_id != "":
        return page_ref.page_id

    try:
        parsed_ref = urlparse(page_ref_str)
        path_and_query = parsed_ref.path
        if parsed_ref.query:
            path_and_query = f"{path_and_query}?{parsed_ref.query}"
        response = client.head(path_and_query, follow_redirects=True)
        resolved = parse_url(str(response.url), expected_host=config_host)
    except (ConfluenceError, ValueError) as exc:
        log.error("short URL resolution: %s", exc)
        return 1
    return resolved.page_id


def _run_export_page(ns: argparse.Namespace) -> int:
    args = cast("_ExportPageArgs", ns)
    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config

    config_host = urlparse(config.url).hostname or None

    def token_resolver() -> str:
        return config.api_token

    output_dir = args.output if args.output is not None else Path()

    with ConfluenceClient(config.url, config.username, token_resolver) as client:
        page_id = _resolve_page_id(client, args.page_ref, config_host)
        if isinstance(page_id, int):
            return page_id

        try:
            out_path = export_page(
                client,
                page_id,
                output_dir,
                include_export_header=args.include_export_header,
                skip_attachments=args.skip_attachments,
            )
        except ConfluenceError as exc:
            log.error("Confluence API: %s", exc)
            return 1

    log.info("Exported: %s", out_path)
    return 0


# ---------------------------------------------------------------------------
# update-page
# ---------------------------------------------------------------------------


def _run_update_page(ns: argparse.Namespace) -> int:
    args = cast("_UpdatePageArgs", ns)
    if not args.md_path.exists():
        log.error("file not found: %s", args.md_path)
        return 1

    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config

    return update_page(
        args.md_path,
        config,
        dry_run=args.dry_run,
        message=args.message,
        yes=args.yes,
        allow_empty=args.allow_empty,
        allow_shrink=args.allow_shrink,
    )


# ---------------------------------------------------------------------------
# create-page
# ---------------------------------------------------------------------------


def _run_create_page(ns: argparse.Namespace) -> int:
    args = cast("_CreatePageArgs", ns)
    if not args.md_path.exists():
        log.error("file not found: %s", args.md_path)
        return 1

    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config

    return create_page(
        args.md_path,
        config,
        space_key=args.space,
        parent=args.parent,
        title=args.title,
        message=args.message,
    )


# ---------------------------------------------------------------------------
# sync-space
# ---------------------------------------------------------------------------


def _resolve_sync_output_dir(space_key: str, output_dir: Path | None) -> Path | int:
    if output_dir is not None:
        # Resolve to an absolute path: build_mirror_state walks the tree with
        # output_dir.rglob(), so a relative --output (e.g. `company`) yields
        # relative paths carrying the `company/` prefix. git_mv/git_rm then run
        # with cwd=output_dir and double the prefix (git looks for
        # `company/company/...`) → "bad source" / "did not match any files".
        return output_dir.resolve()
    detected = default_output_for_space(space_key)
    if detected is not None:
        return detected.resolve()
    log.error(
        "Hint: run inside a clone of the space mirror repo, or pass --output <dir>.\n%s",
        clone_hint("confluence", space_key),
    )
    return 1


# (SyncSummary attribute, "<n> <label>" template for the recap line).
_SYNC_SUMMARY_FIELDS: list[tuple[str, str]] = [
    ("new_from_confluence", "new"),
    ("renamed", "renamed"),
    ("moved", "moved"),
    ("archived", "archived"),
    ("unarchived", "unarchived"),
    ("content_pulled", "pulled"),
    ("deleted", "deleted"),
    ("new_pushed", "created on Confluence"),
    ("content_pushed", "pushed to Confluence"),
    ("skipped_ignored", "skipped (ignored)"),
]


def _print_sync_summary(summary: SyncSummary) -> None:
    parts: list[str] = [
        f"{n} {label}" for attr, label in _SYNC_SUMMARY_FIELDS if (n := getattr(summary, attr))
    ]
    # Spec S39: ``--prune-ignored`` adds a separate ``N pruned (ignored)``
    # entry — or ``N pruned (ignored, dry-run)`` under ``--dry-run`` — so
    # the user can tell local cleanup from source-side filtering.
    if summary.pruned_ignored:
        pruned_label = (
            "pruned (ignored, dry-run)" if summary.pruned_ignored_dry_run else "pruned (ignored)"
        )
        parts.append(f"{summary.pruned_ignored} {pruned_label}")
    log.info("Sync complete: %s.", ", ".join(parts) if parts else "nothing changed")

    if summary.conflicts:
        log.warning(
            "Conflicts (skipped): %d — resolve manually with 'mdd confluence update-page'",
            len(summary.conflicts),
        )
    if summary.failures:
        log.error("Failures: %d", len(summary.failures))
        for f in summary.failures:
            log.error("  - %s", f)


def _load_mddignore(dest_root: Path, ignore_paths: list[Path] | None) -> MddIgnore:
    """Build the S39 matcher from *dest_root*/.mddignore plus CLI ``--ignore`` paths."""
    cli_tuple: tuple[Path, ...] = tuple(ignore_paths) if ignore_paths else ()
    return MddIgnore.load(dest_root, cli_tuple)


def _do_sync_space(
    args: _SyncSpaceArgs, output_dir: Path, config: ConfluenceConfig
) -> SyncSummary | int:
    """Open a Confluence client and run sync_space; return summary or exit code on failure."""

    def token_resolver() -> str:
        return config.api_token

    max_attachment_size_bytes: int | None = None
    if args.max_attachment_size is not None:
        max_attachment_size_bytes = int(args.max_attachment_size * 1024 * 1024)

    matcher = _load_mddignore(output_dir, args.ignore)

    opts = SyncOptions(
        dry_run=args.dry_run,
        no_delete=args.no_delete,
        push=args.push,
        message=args.message,
        head=args.head,
        max_attachment_size_bytes=max_attachment_size_bytes,
        skip_attachments=args.skip_attachments,
        read_only=args.read_only,
        matcher=matcher,
        prune_ignored=args.prune_ignored,
    )
    with ConfluenceClient(config.url, config.username, token_resolver) as client:
        try:
            return sync_space(
                client,
                args.space_key,
                output_dir,
                config,
                opts=opts,
            )
        except ApplyError as exc:
            log.error("%s", exc)
        except ConfluenceError as exc:
            log.error("Confluence API: %s", exc)
        return 1


_PRUNE_READONLY_CONFLICT = "--read-only and --prune-ignored are mutually exclusive"


def _check_prune_readonly(ns: argparse.Namespace, args: _SyncSpaceArgs) -> None:
    """Reject ``--read-only`` + ``--prune-ignored`` at parse time (spec S39).

    Uses the subparser stashed on the namespace via ``set_defaults`` so the
    error path goes through ``argparse``'s standard formatter (exit code 2,
    program-name prefix, ``usage:`` line).
    """
    if not (args.read_only and args.prune_ignored):
        return
    parser = getattr(ns, "_parser", None)
    if parser is None:  # pragma: no cover - defensive
        raise SystemExit(_PRUNE_READONLY_CONFLICT)
    parser.error(_PRUNE_READONLY_CONFLICT)


def _run_sync_space(ns: argparse.Namespace) -> int:
    args = cast("_SyncSpaceArgs", ns)
    _check_prune_readonly(ns, args)
    resolved_output = _resolve_sync_output_dir(args.space_key, args.output)
    if isinstance(resolved_output, int):
        return resolved_output

    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config

    summary = _do_sync_space(args, resolved_output, config)
    if isinstance(summary, int):
        return summary

    if args.dry_run:
        return 0

    _print_sync_summary(summary)
    return 1 if summary.failures else 0


# ---------------------------------------------------------------------------
# rename-page / move-page / archive-page / unarchive-page (spec S27)
# ---------------------------------------------------------------------------


# Type alias for the four mutate Namespace subclasses — they share the same
# message / yes / no_commit / dry_run / md_path / config field shape that
# ``_build_mutate_opts`` and ``_load_md_path_and_config`` read.
type _MutateArgs = _RenamePageArgs | _MovePageArgs | _ArchivePageArgs | _UnarchivePageArgs


def _build_mutate_opts(args: _MutateArgs, config: ConfluenceConfig) -> MutateOptions:
    """Build :class:`MutateOptions` from the typed argparse namespace."""
    return MutateOptions(
        config=config,
        message=args.message,
        dry_run=args.dry_run,
        no_commit=args.no_commit,
        yes=args.yes,
    )


def _load_md_path_and_config(args: _MutateArgs) -> tuple[Path, ConfluenceConfig] | int:
    """Validate the md_path positional and load the Confluence config."""
    if not args.md_path.exists():
        log.error("file not found: %s", args.md_path)
        return 1
    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config
    return args.md_path, config


def _run_rename_page(ns: argparse.Namespace) -> int:
    args = cast("_RenamePageArgs", ns)
    resolved = _load_md_path_and_config(args)
    if isinstance(resolved, int):
        return resolved
    md_path, config = resolved
    return rename_page(md_path, args.new_title, opts=_build_mutate_opts(args, config))


def _run_move_page(ns: argparse.Namespace) -> int:
    args = cast("_MovePageArgs", ns)
    resolved = _load_md_path_and_config(args)
    if isinstance(resolved, int):
        return resolved
    md_path, config = resolved
    return move_page(md_path, args.parent, opts=_build_mutate_opts(args, config))


def _run_archive_page(ns: argparse.Namespace) -> int:
    args = cast("_ArchivePageArgs", ns)
    resolved = _load_md_path_and_config(args)
    if isinstance(resolved, int):
        return resolved
    md_path, config = resolved
    return archive_page(md_path, opts=_build_mutate_opts(args, config))


def _run_unarchive_page(ns: argparse.Namespace) -> int:
    args = cast("_UnarchivePageArgs", ns)
    resolved = _load_md_path_and_config(args)
    if isinstance(resolved, int):
        return resolved
    md_path, config = resolved
    return unarchive_page(md_path, opts=_build_mutate_opts(args, config))


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------


def _run_whoami(ns: argparse.Namespace) -> int:
    args = cast("_WhoamiArgs", ns)
    config = _load_config_or_exit(args.config)
    if isinstance(config, int):
        return config

    managed_config = load_managed_config()

    def token_resolver() -> str:
        return config.api_token

    with ConfluenceClient(config.url, config.username, token_resolver) as client:
        return cmd_whoami(client, config=managed_config)


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------


def register(
    subparsers: SubParsers,
    parents: CommonParents,
) -> None:
    cf = subparsers.add_parser(
        "confluence",
        help="Confluence Cloud integration (specs S09/S14)",
        description="Bidirectional sync, export, create, and update for Confluence Cloud.",
    )
    sub = cf.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    p_ss = sub.add_parser(
        "sync-space",
        parents=[parents.config_required, parents.dry_run],
        help="Reconcile a Confluence space with a local mirror",
        description=(
            "Bidirectional sync between a Confluence space and a local mirror. "
            "--no-attachments skips all attachment downloads. --read-only "
            "suppresses every mirror → Confluence write step (no page creation, "
            "no content push, no Office publishing) — use for snapshot-style exports."
        ),
    )
    _ = p_ss.add_argument("space_key", help="Confluence space key (e.g. ENGINEERING)")
    _ = p_ss.add_argument(
        "--output", type=Path, default=None, metavar="DIR", help="Output mirror directory"
    )
    _ = p_ss.add_argument(
        "--no-delete",
        action="store_true",
        help="Do not delete local pages even if absent on Confluence",
    )
    _ = p_ss.add_argument(
        "--push",
        action="store_true",
        help="Push the output git repo after applying changes",
    )
    _ = p_ss.add_argument("--message", default=None, metavar="MSG", help="Commit message override")
    _ = p_ss.add_argument(
        "--head", type=int, default=None, metavar="N", help="Process only the first N pages"
    )
    _ = p_ss.add_argument(
        "--max-attachment-size",
        type=float,
        default=None,
        metavar="MB",
        help="Skip attachments larger than this (megabytes)",
    )
    _ = p_ss.add_argument(
        "--no-attachments",
        dest="skip_attachments",
        action="store_true",
        help="Skip all attachment downloads (markdown body only)",
    )
    _ = p_ss.add_argument(
        "--read-only",
        action="store_true",
        help="Suppress every mirror → Confluence write step",
    )
    _ = p_ss.add_argument(
        "--ignore",
        type=Path,
        action="append",
        default=None,
        metavar="FILE",
        help=(
            "Path to an additional `.mddignore`-style file whose patterns are "
            "unioned with `<output>/.mddignore` (spec S39). May be supplied "
            "multiple times; with no flag and no dest-root file, sync "
            "behaviour is identical to the pre-S39 default (no filtering). "
            "Patterns match the page-title chain that produces the on-disk "
            "markdown filename — e.g. `Archive/` skips every page whose "
            "title chain begins with `Archive`."
        ),
    )
    _ = p_ss.add_argument(
        "--prune-ignored",
        action="store_true",
        help=(
            "Before syncing, delete every file under <output> whose path "
            "matches the loaded `.mddignore` matcher (spec S39 opt-in "
            "cleanup). One INFO log line per deletion. Combine with "
            "--dry-run to preview without deleting. Mutually exclusive "
            "with --read-only."
        ),
    )
    p_ss.set_defaults(func=_run_sync_space, _parser=p_ss)

    p_ep = sub.add_parser(
        "export-page",
        parents=[parents.config_required],
        help="Export a single Confluence page to a Markdown file",
        description=(
            "Export a single Confluence page to a Markdown file. --no-header omits "
            'the leading "Confluence export" blockquote. --no-attachments skips '
            "all attachment downloads."
        ),
    )
    _ = p_ep.add_argument("page_ref", metavar="PAGE_ID_OR_URL", help="Page id or full URL")
    _ = p_ep.add_argument(
        "--output", type=Path, default=None, metavar="DIR", help="Output directory"
    )
    _ = p_ep.add_argument(
        "--no-header",
        dest="include_export_header",
        action="store_false",
        help="Omit the leading 'Confluence export' blockquote",
    )
    _ = p_ep.add_argument(
        "--no-attachments",
        dest="skip_attachments",
        action="store_true",
        help="Skip all attachment downloads",
    )
    p_ep.set_defaults(func=_run_export_page)

    p_cp = sub.add_parser(
        "create-page",
        parents=[parents.config_required],
        help="Create a new Confluence page from a local Markdown file",
        description="Create a new Confluence page from a local Markdown file.",
    )
    _ = p_cp.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _ = p_cp.add_argument(
        "--space", default=None, metavar="KEY", help="Target Confluence space key"
    )
    _ = p_cp.add_argument(
        "--parent", default=None, metavar="ID_OR_URL", help="Parent page id or URL"
    )
    _ = p_cp.add_argument("--title", default=None, metavar="TITLE", help="Page title override")
    _ = p_cp.add_argument(
        "--message", default="Created via mdd", metavar="MSG", help="Version message"
    )
    p_cp.set_defaults(func=_run_create_page)

    p_up = sub.add_parser(
        "update-page",
        parents=[parents.config_required, parents.dry_run],
        help="Push local Markdown edits back to Confluence",
        description="Push local Markdown edits back to Confluence.",
    )
    _ = p_up.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _ = p_up.add_argument(
        "--message", default="Updated via mdd", metavar="MSG", help="Version message"
    )
    _ = p_up.add_argument("--yes", action="store_true", help="Skip the interactive confirmation")
    _ = p_up.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow pushing an empty body (would otherwise be a safety check)",
    )
    _ = p_up.add_argument(
        "--allow-shrink",
        action="store_true",
        help="Allow pushing a body that is dramatically smaller than the live page",
    )
    p_up.set_defaults(func=_run_update_page)

    p_wh = sub.add_parser(
        "whoami",
        parents=[parents.config_required],
        help="Print the current Confluence user and managed-page publishers",
        description=("Print the current Confluence user and compare against external publishers."),
    )
    p_wh.set_defaults(func=_run_whoami)

    _register_mutate_subparsers(sub, parents)


def _add_mutate_flags(parser: argparse.ArgumentParser, default_message: str) -> None:
    """Add the ``--message`` / ``--yes`` / ``--no-commit`` flags shared by the
    four S27 mutate subcommands."""
    _ = parser.add_argument(
        "--message", default=default_message, metavar="MSG", help="Version comment"
    )
    _ = parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    _ = parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip the commit step (leave staged changes for the user)",
    )


def _register_mutate_subparsers(
    sub: SubParsers,
    parents: CommonParents,
) -> None:
    """Register the four S27 mutate subcommands under ``mdd confluence``."""
    p_rn = sub.add_parser(
        "rename-page",
        parents=[parents.config_required, parents.dry_run],
        help="Rename a Confluence page (and refresh the local mirror)",
        description="Rename a Confluence page and replay the rename in the mirror.",
    )
    _ = p_rn.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _ = p_rn.add_argument("new_title", metavar="NEW_TITLE", help="New page title")
    _add_mutate_flags(p_rn, default_message="Renamed via mdd")
    p_rn.set_defaults(func=_run_rename_page)

    p_mv = sub.add_parser(
        "move-page",
        parents=[parents.config_required, parents.dry_run],
        help="Move a Confluence page to a new parent (and refresh the mirror)",
        description="Move a Confluence page to a new parent and replay locally.",
    )
    _ = p_mv.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _ = p_mv.add_argument(
        "--parent",
        required=True,
        metavar="ID_OR_URL_OR_FILE",
        help="New parent (page id, Confluence URL, or path to another local .md)",
    )
    _add_mutate_flags(p_mv, default_message="Moved via mdd")
    p_mv.set_defaults(func=_run_move_page)

    p_ar = sub.add_parser(
        "archive-page",
        parents=[parents.config_required, parents.dry_run],
        help="Archive a Confluence page (and flip mirror frontmatter status)",
        description="Archive a Confluence page; mirror frontmatter status flips to ARCHIVED.",
    )
    _ = p_ar.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _add_mutate_flags(p_ar, default_message="Archived via mdd")
    p_ar.set_defaults(func=_run_archive_page)

    p_un = sub.add_parser(
        "unarchive-page",
        parents=[parents.config_required, parents.dry_run],
        help="Unarchive a Confluence page (and flip mirror frontmatter status)",
        description="Unarchive a Confluence page; mirror frontmatter status flips to CURRENT.",
    )
    _ = p_un.add_argument("md_path", type=Path, metavar="MARKDOWN_FILE", help="Markdown source")
    _add_mutate_flags(p_un, default_message="Unarchived via mdd")
    p_un.set_defaults(func=_run_unarchive_page)
