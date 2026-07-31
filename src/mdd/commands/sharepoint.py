"""mdd sharepoint — SharePoint OneDrive mirror command."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml  # pyright: ignore[reportMissingModuleSource]
from pydantic import ValidationError

from mdd.mirror.hints import clone_hint
from mdd.sharepoint.mapping import load_mapping, repo_name
from mdd.sharepoint.models import SharepointCliConfig
from mdd.sharepoint.sync import SyncError, SyncRootMissing, list_sites, resolve_sync_root
from mdd.utils.blacklist import BlacklistConfigError, BlacklistError
from mdd.utils.logging import get_logger
from mdd.utils.mddignore import MddIgnore

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers
    from mdd.sharepoint.apply import SyncRunSummary
    from mdd.sharepoint.mapping import MappingEntry
    from mdd.sharepoint.sync import SiteEntry

log = get_logger(__name__)


def _load_config(config_path: Path) -> SharepointCliConfig | None:
    """Load and validate a YAML config file. Returns None on failure (error printed to stderr)."""
    if not config_path.exists():
        log.error("config: file not found: %s", config_path)
        return None
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("config: cannot read %s: %s", config_path, exc)
        return None
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        log.error("config: failed to parse %s: %s", config_path, exc)
        return None
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        log.error("config: %s must be a YAML mapping", config_path)
        return None
    try:
        return SharepointCliConfig.model_validate(parsed)
    except ValidationError as exc:
        log.error("config: %s: %s", config_path, exc)
        return None


def _load_config_or_exit(
    config_path: Path | None,
) -> tuple[SharepointCliConfig | None, int | None]:
    """Resolve --config Path to a validated config. Returns (config, exit_code)."""
    if config_path is None:
        return None, None
    config = _load_config(config_path)
    if config is None:
        return None, 1
    return config, None


# ---------------------------------------------------------------------------
# list-sites
# ---------------------------------------------------------------------------


def _site_blacklist_status(site_name: str) -> str:
    # lazy import: tests patch mdd.utils.blacklist.check_sharepoint; binding here
    # at call time preserves the late-binding contract used by patch(...).
    from mdd.utils.blacklist import check_sharepoint  # noqa: PLC0415

    try:
        check_sharepoint(site_name)
    except BlacklistError:
        return "BLOCKED"
    except BlacklistConfigError:
        return "unknown (blacklist config missing)"
    return "allowed"


def _print_one_site_entry(entry: SiteEntry, mapping: dict[str, MappingEntry]) -> None:
    rn = repo_name(entry.derived_site_name, mapping)
    kind = "library" if entry.is_library_root else "subfolder"
    blacklist_status = _site_blacklist_status(entry.derived_site_name)
    has_mapping = entry.derived_site_name in mapping
    mapping_note = "" if has_mapping else " [no explicit mapping — using default normalize]"
    print(f"  {entry.derived_site_name}")  # noqa: T201  # program output
    print(f"    folder:    {entry.display_name}")  # noqa: T201  # program output
    print(f"    type:      {kind}")  # noqa: T201  # program output
    print(f"    repo:      {rn}{mapping_note}")  # noqa: T201  # program output
    print(f"    blacklist: {blacklist_status}")  # noqa: T201  # program output
    print()  # noqa: T201  # program output


class _SharepointListSitesArgs(argparse.Namespace):
    config: Path | None
    mapping: Path | None


class _SharepointSyncSiteArgs(argparse.Namespace):
    config: Path | None
    site_name: str
    mapping: Path | None
    output: Path | None
    push: bool
    backup: bool
    head: int | None
    message: str | None
    ignore: list[Path] | None
    read_only: bool
    prune_ignored: bool
    dry_run: bool


class _SharepointSyncFolderArgs(argparse.Namespace):
    local_path: Path
    output: Path | None
    push: bool
    backup: bool
    head: int | None
    message: str | None
    ignore: list[Path] | None
    prune_ignored: bool
    dry_run: bool


def _run_list_sites(ns: argparse.Namespace) -> int:
    args = cast("_SharepointListSitesArgs", ns)
    config, exit_code = _load_config_or_exit(args.config)
    if exit_code is not None:
        return exit_code

    try:
        sync_root = resolve_sync_root(config)
    except SyncRootMissing as exc:
        log.error("%s", exc)
        return 1

    sites = list_sites(sync_root)
    mapping = load_mapping(args.mapping)

    if not sites:
        print(f"No sites found under {sync_root}")  # noqa: T201  # program output
        return 0

    print(f"SharePoint sites under {sync_root}:")  # noqa: T201  # program output
    print()  # noqa: T201  # program output
    for entry in sites:
        _print_one_site_entry(entry, mapping)
    return 0


# ---------------------------------------------------------------------------
# sync-site / sync-folder shared
# ---------------------------------------------------------------------------


def _print_sync_summary(summary: SyncRunSummary) -> None:
    # A ``--dry-run`` prune pass increments ``pruned_ignored`` but performs no
    # deletion; surface that distinction in the log.
    pruned_label = (
        "pruned (ignored, dry-run)" if summary.pruned_ignored_dry_run else "pruned (ignored)"
    )
    log.info(
        "Sync complete: "
        "%d first-sync(docx→md), "
        "%d first-sync(md→docx), "
        "%d docx→md, "
        "%d md→docx, "
        "%d diverged, "
        "%d skipped(update_office=False), "
        "%d skipped(--read-only), "
        "%d skipped (ignored), "
        "%d %s, "
        "%d skipped (corrupt), "
        "%d no-op, "
        "%d locked, "
        "%d errors.",
        summary.first_sync_docx,
        summary.first_sync_md,
        summary.docx_to_md,
        summary.md_to_docx,
        summary.diverged,
        summary.skipped_md_update,
        summary.skipped_read_only,
        summary.skipped_ignored,
        summary.pruned_ignored,
        pruned_label,
        summary.skipped_corrupt,
        summary.no_op,
        summary.word_locked,
        len(summary.errors),
    )


def _load_mddignore(dest_root: Path, ignore_paths: list[Path] | None) -> MddIgnore:
    """Build the ignore matcher from *dest_root*/.mddignore plus CLI ``--ignore`` paths."""
    cli_tuple: tuple[Path, ...] = tuple(ignore_paths) if ignore_paths else ()
    return MddIgnore.load(dest_root, cli_tuple)


def _handle_sync_error(exc: Exception, label: str | None = None) -> int:
    """Log one of the sync error types and return exit code 1."""
    if isinstance(exc, BlacklistConfigError):
        log.error("blacklist config: %s", exc)
    elif isinstance(exc, BlacklistError):
        log.error("blacklist: %s", exc)
    elif label:
        log.error("%s: %s", label, exc)
    else:
        log.error("%s", exc)
    return 1


def _resolve_site_output_dir(
    site_name: str, output_dir: Path | None, mapping: dict[str, MappingEntry]
) -> Path | int:
    if output_dir is not None:
        return output_dir
    # lazy import: tests patch mdd.sharepoint.export.default_output_for_site
    from mdd.sharepoint.export import default_output_for_site  # noqa: PLC0415

    detected = default_output_for_site(site_name, mapping)
    if detected is not None:
        return detected
    log.error(
        "Hint: run inside a clone of the site mirror repo, or pass --output <dir>.\n%s",
        clone_hint("sharepoint", repo_name(site_name, mapping)),
    )
    return 1


_PRUNE_READONLY_CONFLICT = "--read-only and --prune-ignored are mutually exclusive"


def _check_prune_readonly(ns: argparse.Namespace, *, read_only: bool, prune_ignored: bool) -> None:
    """Reject ``--read-only`` + ``--prune-ignored`` at parse time.

    Uses the subparser stashed on the namespace via ``set_defaults`` so the
    error path goes through ``argparse``'s standard formatter (exit code 2,
    program-name prefix, ``usage:`` line). The check is centralised so
    sync-site and sync-folder share the same wording.
    """
    if not (read_only and prune_ignored):
        return
    parser = getattr(ns, "_parser", None)
    if parser is None:  # pragma: no cover - defensive
        raise SystemExit(_PRUNE_READONLY_CONFLICT)
    parser.error(_PRUNE_READONLY_CONFLICT)


def _run_sync_site(ns: argparse.Namespace) -> int:
    # lazy import: tests patch mdd.sharepoint.sync.sync_site
    from mdd.sharepoint.sync import sync_site  # noqa: PLC0415

    args = cast("_SharepointSyncSiteArgs", ns)
    _check_prune_readonly(ns, read_only=args.read_only, prune_ignored=args.prune_ignored)
    config, exit_code = _load_config_or_exit(args.config)
    if exit_code is not None:
        return exit_code

    mapping = load_mapping(args.mapping)
    resolved_out = _resolve_site_output_dir(args.site_name, args.output, mapping)
    if isinstance(resolved_out, int):
        return resolved_out

    matcher = _load_mddignore(resolved_out, args.ignore)

    try:
        summary = sync_site(
            args.site_name,
            config=config,
            output_dir=resolved_out,
            dry_run=args.dry_run,
            push=args.push,
            backup=args.backup,
            head=args.head,
            message=args.message,
            read_only=args.read_only,
            mapping_path=args.mapping,
            matcher=matcher,
            prune_ignored=args.prune_ignored,
        )
    except (SyncRootMissing, SyncError, BlacklistError, BlacklistConfigError) as exc:
        return _handle_sync_error(exc)

    _print_sync_summary(summary)
    return 1 if summary.errors else 0


def _run_sync_folder(ns: argparse.Namespace) -> int:
    # lazy import: tests patch mdd.sharepoint.sync.sync_folder
    from mdd.sharepoint.sync import sync_folder  # noqa: PLC0415

    args = cast("_SharepointSyncFolderArgs", ns)
    # ``sync-folder`` has no ``--read-only`` flag today, but the
    # mutual-exclusion check is cheap and futureproof.
    _check_prune_readonly(
        ns,
        read_only=bool(getattr(args, "read_only", False)),
        prune_ignored=args.prune_ignored,
    )
    if args.output is None:
        log.error("Hint: pass --output <dir> to specify the output directory.")
        return 1

    matcher = _load_mddignore(args.output, args.ignore)

    try:
        summary = sync_folder(
            args.local_path,
            output_dir=args.output,
            dry_run=args.dry_run,
            push=args.push,
            backup=args.backup,
            head=args.head,
            message=args.message,
            matcher=matcher,
            prune_ignored=args.prune_ignored,
        )
    except (SyncError, BlacklistError, BlacklistConfigError) as exc:
        return _handle_sync_error(exc)

    _print_sync_summary(summary)
    return 1 if summary.errors else 0


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------


def _add_sync_common(p: argparse.ArgumentParser) -> None:
    _ = p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="DIR",
        help="Output directory (defaults from config/mapping)",
    )
    _ = p.add_argument(
        "--push",
        action="store_true",
        help="Push the output git repo after applying changes",
    )
    _ = p.add_argument(
        "--backup",
        action="store_true",
        help="Back up diverged Word documents before resync",
    )
    _ = p.add_argument(
        "--head",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N files (smoke test)",
    )
    _ = p.add_argument(
        "--message",
        default=None,
        metavar="MSG",
        help="Commit message override",
    )
    _ = p.add_argument(
        "--ignore",
        type=Path,
        action="append",
        default=None,
        metavar="FILE",
        help=(
            "Path to an additional `.mddignore`-style file whose patterns are "
            "unioned with `<output>/.mddignore`. May be supplied multiple "
            "times; with no flag and no dest-root file, nothing is filtered."
        ),
    )
    _ = p.add_argument(
        "--prune-ignored",
        action="store_true",
        help=(
            "Before syncing, delete every file under <output> whose path "
            "matches the loaded `.mddignore` matcher. "
            "One INFO log line per deletion. Combine with "
            "--dry-run to preview without deleting. Mutually exclusive "
            "with --read-only."
        ),
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,
) -> None:
    sp = subparsers.add_parser(
        "sharepoint",
        help="Mirror SharePoint OneDrive folders to Markdown",
        description="Mirror SharePoint OneDrive folders to and from local Markdown.",
    )
    sub = sp.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    p_ls = sub.add_parser(
        "list-sites",
        parents=[parents.config_required],
        help="List SharePoint sites in the local OneDrive sync directory",
        description="List SharePoint sites found in the local OneDrive sync directory.",
    )
    _ = p_ls.add_argument(
        "--mapping",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to sharepoint-mapping.yaml (overrides default search)",
    )
    p_ls.set_defaults(func=_run_list_sites)

    p_ss = sub.add_parser(
        "sync-site",
        parents=[parents.config_required, parents.dry_run],
        help="Bidirectionally sync a SharePoint site with its Markdown mirror",
        description=(
            "Bidirectionally sync a SharePoint site with its Markdown mirror. "
            "--read-only suppresses every mirror → OneDrive/SharePoint write "
            "(no md→office render, no diverged candidate) — local mirror "
            "updates and the optional GitLab push are still performed."
        ),
    )
    _ = p_ss.add_argument("site_name", help="SharePoint site name")
    _ = p_ss.add_argument(
        "--mapping",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to sharepoint-mapping.yaml",
    )
    _add_sync_common(p_ss)
    _ = p_ss.add_argument(
        "--read-only",
        action="store_true",
        help="Suppress every mirror → OneDrive/SharePoint write step",
    )
    p_ss.set_defaults(func=_run_sync_site, _parser=p_ss)

    p_sf = sub.add_parser(
        "sync-folder",
        parents=[parents.dry_run],
        help="Bidirectionally sync an arbitrary local OneDrive folder",
        description="Bidirectionally sync an arbitrary local OneDrive folder.",
    )
    _ = p_sf.add_argument("local_path", type=Path, help="Local OneDrive folder path")
    _add_sync_common(p_sf)
    p_sf.set_defaults(func=_run_sync_folder, _parser=p_sf)
