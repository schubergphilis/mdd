"""Orchestrators for ``mdd confluence rename / move / archive / unarchive``.

Each public function (``rename_page`` / ``move_page`` / ``archive_page`` /
``unarchive_page``) mutates Confluence first, then refreshes the local
mirror via the existing sync apply path
(:mod:`mdd.confluence.sync.renames`), then commits a structured
``chore(mirror):`` summary.

Argument bundling: callers pass a :class:`MutateOptions` dataclass instead
of five flat ``config / dry_run / no_commit / yes / message`` keyword
arguments, keeping these functions under the project's 6-argument ceiling.
Same pattern as :class:`mdd.confluence.client.PutPageOptions`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

from pydantic import ValidationError

from mdd.confluence.apply import (
    ApplyError,
    git_commit,
)
from mdd.confluence.apply import (
    is_dirty as _apply_is_dirty,
)
from mdd.confluence.client import ConfluenceClient, ConfluenceError, PutPageOptions
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.managed import (
    ManagedConfig,
    build_page_info_from_page_data,
    classify_page,
    load_managed_config,
)
from mdd.confluence.materialise import promote_flat_to_dir, pull_single_page
from mdd.confluence.models import ConfluenceBlock, ConfluenceV2PageMinimal
from mdd.confluence.state import LocalPage
from mdd.confluence.sync._types import SyncSummary
from mdd.confluence.sync.renames import apply_archive_unarchive, apply_renames_moves
from mdd.confluence.sync_diff import DesiredPage, EventKind, SyncEvent
from mdd.confluence.tree import AncestorStep, ancestor_chain_for_move
from mdd.confluence.url import URLMismatchError
from mdd.confluence.url import parse as parse_url
from mdd.confluence.version import VersionDriftError, check_version_drift
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.confluence.config import ConfluenceConfig

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Options + state dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MutateOptions:
    """Bundle of flags shared by every mutate orchestrator.

    Bundled so that ``rename_page`` / ``move_page`` stay within the
    6-argument ceiling.  Defaults mirror what the CLI runners pass when a
    flag is omitted.
    """

    config: ConfluenceConfig
    message: str = ""
    dry_run: bool = False
    no_commit: bool = False
    yes: bool = False
    managed_config: ManagedConfig | None = None


@dataclass(frozen=True)
class _PageState:
    """Validated local file state needed to plan a mutation."""

    md_path: Path
    page_id: str
    title: str
    parent_id: str | None
    status: str  # frontmatter form: "CURRENT" / "ARCHIVED"
    version: int
    space_key: str
    space_id: str


class _MutateAbort(Exception):
    """Internal sentinel: a sub-step has decided to terminate the orchestrator."""

    def __init__(self, rc: int) -> None:
        super().__init__(f"mutate abort rc={rc}")
        self.rc = rc


# ---------------------------------------------------------------------------
# Local-file helpers
# ---------------------------------------------------------------------------


def _validate_block(fm: dict[str, Any], md_path: Path) -> ConfluenceBlock | None:
    """Return the typed ``confluence:`` block, or ``None`` when absent/invalid."""
    raw: object = fm.get("confluence")
    if raw is None:
        return None
    try:
        return ConfluenceBlock.model_validate(raw)
    except ValidationError as exc:
        log.warning("%s: invalid confluence frontmatter: %s", md_path, exc)
        return None


def _load_local(md_path: Path) -> _PageState:
    """Read ``md_path``'s frontmatter and return a validated :class:`_PageState`."""
    try:
        fm, _body = read_frontmatter(md_path)
    except OSError as exc:
        log.error("reading %s: %s", md_path, exc)
        raise _MutateAbort(1) from exc

    block = _validate_block(fm, md_path)
    if block is None or not block.page_id:
        log.error(
            "%s is missing 'confluence.page_id' in frontmatter. "
            "This file is not yet published; run 'mdd confluence create-page' first.",
            md_path,
        )
        raise _MutateAbort(1)
    return _PageState(
        md_path=md_path,
        page_id=block.page_id,
        title=block.title or md_path.stem,
        parent_id=block.parent_id or None,
        status=(block.status or "CURRENT").upper(),
        version=block.version,
        space_key=block.space_key,
        space_id=block.space_id,
    )


# ---------------------------------------------------------------------------
# Parent resolution
# ---------------------------------------------------------------------------


def _resolve_parent(parent_ref: str, *, config_host: str | None) -> str:
    """Resolve a ``--parent`` argument into a Confluence page id.

    Accepts a numeric id, a Confluence URL (parsed via
    :mod:`mdd.confluence.url`), or a path to another local ``.md`` whose
    ``confluence.page_id`` frontmatter is the parent.
    """
    if parent_ref.endswith(".md"):
        candidate = Path(parent_ref)
        if not candidate.exists():
            log.error("parent file not found: %s", candidate)
            raise _MutateAbort(1)
        parent_state = _load_local(candidate)
        return parent_state.page_id
    try:
        ref = parse_url(parent_ref, expected_host=config_host)
    except URLMismatchError as exc:
        log.error("URL mismatch: %s", exc)
        raise _MutateAbort(1) from exc
    except ValueError as exc:
        log.error("invalid --parent: %s", exc)
        raise _MutateAbort(1) from exc
    if not ref.page_id:
        log.error(
            "--parent short URLs are not supported; pass the canonical "
            "page URL or the page id directly.",
        )
        raise _MutateAbort(1)
    return ref.page_id


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _check_dirty(repo_dir: Path) -> None:
    """Refuse to mutate when the working tree has uncommitted changes."""
    if _apply_is_dirty(repo_dir):
        log.error(
            "Mirror has uncommitted changes. Commit, stash, or discard before running.",
        )
        raise _MutateAbort(1)


def _check_managed(
    page_data: dict[str, Any],
    client: ConfluenceClient,
    managed_config: ManagedConfig,
) -> None:
    """Refuse the mutation when the remote page is managed-elsewhere."""
    body_storage = _extract_storage_body(page_data)
    page_info = build_page_info_from_page_data(page_data, body_storage)
    classification = classify_page(page_info, managed_config, client)
    if classification.is_managed:
        msg = classification.message or (
            f"This page is managed by {classification.publisher_name!r}. "
            "Edit at the source; do not mutate via mdd."
        )
        log.error("%s", msg)
        raise _MutateAbort(1)


def _check_version(local_version: int, remote_version: int) -> None:
    """Refuse when the remote version is ahead of the local copy."""
    try:
        check_version_drift(local_version, remote_version)
    except VersionDriftError as exc:
        log.error("%s", exc)
        raise _MutateAbort(1) from None


def _check_same_space(page_state: _PageState, parent_data: dict[str, Any]) -> None:
    """Refuse a cross-space move."""
    parent = ConfluenceV2PageMinimal.model_validate(parent_data)
    parent_space = parent.space_id or parent.space_key
    page_space = page_state.space_id or page_state.space_key
    if not parent_space or not page_space:
        return  # missing data — can't compare; defer to API to fail
    # Match either id-id or key-key — the parent payload may only carry one.
    parent_id_match = bool(page_state.space_id and parent.space_id == page_state.space_id)
    parent_key_match = bool(page_state.space_key and parent.space_key == page_state.space_key)
    if not (parent_id_match or parent_key_match):
        log.error(
            "Cross-space moves are not supported. Move via the Confluence "
            "UI, then run 'mdd confluence sync' against both spaces.",
        )
        raise _MutateAbort(1)


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


def _prompt(preview: str, *, yes: bool) -> bool:
    """Print ``preview`` and ask for confirmation.  Returns False on decline."""
    log.info("%s", preview)
    if yes:
        return True
    if not sys.stdin.isatty():
        log.error("stdin is not a TTY. Use --yes to confirm non-interactively.")
        raise _MutateAbort(1)
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except EOFError, KeyboardInterrupt:
        log.info("Aborted.")
        return False
    return answer == "y"


# ---------------------------------------------------------------------------
# API + event helpers
# ---------------------------------------------------------------------------


def _v2_page(page_data: dict[str, Any]) -> ConfluenceV2PageMinimal:
    """Validate a raw v2 page response into the typed model."""
    return ConfluenceV2PageMinimal.model_validate(page_data)


def _extract_storage_body(page_data: dict[str, Any]) -> str:
    """Pull ``body.storage.value`` from a v2 page response."""
    page = _v2_page(page_data)
    if page.body is None or page.body.storage is None:
        return ""
    return page.body.storage.value


def _remote_version(page_data: dict[str, Any]) -> int:
    """Pull the integer ``version.number`` from a page response."""
    page = _v2_page(page_data)
    return page.version.number if page.version is not None else 1


def _remote_status(page_data: dict[str, Any]) -> str:
    """Pull the lowercase ``status`` from a page response (defaults to ``current``)."""
    return _v2_page(page_data).status or "current"


def _remote_title(page_data: dict[str, Any]) -> str:
    return _v2_page(page_data).title


def _build_event(
    kind: EventKind,
    page_state: _PageState,
    *,
    new_title: str | None = None,
    new_parent_id: str | None = None,
    new_status: str | None = None,
) -> SyncEvent:
    """Build a single :class:`SyncEvent` for the rename/move/archive handlers."""
    desired = DesiredPage(
        page_id=page_state.page_id,
        title=new_title if new_title is not None else page_state.title,
        parent_id=new_parent_id if new_parent_id is not None else page_state.parent_id,
        status=new_status if new_status is not None else page_state.status.lower(),
        version_number=page_state.version + 1,
        version_created_at="",
        space_id=page_state.space_id,
    )
    return SyncEvent(
        kind=kind,
        page_id=page_state.page_id,
        desired=desired,
        current_path=str(page_state.md_path),
    )


# ---------------------------------------------------------------------------
# Mirror state and refresh
# ---------------------------------------------------------------------------


@dataclass
class _SingleMirror:
    """Minimal mirror surface for the renames handlers (only ``tracked`` is read)."""

    tracked: dict[str, LocalPage]


def _make_single_mirror(page_state: _PageState) -> _SingleMirror:
    """Return a minimal mirror object satisfying the renames handlers' contract."""

    local = LocalPage(
        path=page_state.md_path,
        page_id=page_state.page_id,
        title=page_state.title,
        parent_id=page_state.parent_id,
        status=page_state.status,
        version_number=page_state.version,
        space_key=page_state.space_key,
        space_id=page_state.space_id,
    )
    return _SingleMirror(tracked={page_state.page_id: local})


def _apply_rename_or_move(
    event: SyncEvent,
    page_state: _PageState,
    output_dir: Path,
    *,
    new_parent_dir: Path | None = None,
) -> Path:
    """Run the per-page rename/move refresh.  Returns the new local path."""
    mirror = _make_single_mirror(page_state)
    summary = SyncSummary()
    page_to_outdir: dict[str, Path] = {}
    if new_parent_dir is not None:
        page_to_outdir[page_state.page_id] = new_parent_dir
    apply_renames_moves(
        [event],
        mirror,
        output_dir,
        page_to_outdir=page_to_outdir,
        used_paths=set(),
        summary=summary,
    )
    if summary.failures:
        raise ApplyError("; ".join(summary.failures))
    return mirror.tracked[page_state.page_id].path


def _apply_archive_refresh(event: SyncEvent, page_state: _PageState) -> None:
    """Flip frontmatter ``confluence.status`` via the archive handler."""
    mirror = _make_single_mirror(page_state)
    summary = SyncSummary()
    apply_archive_unarchive([event], mirror, summary)
    if summary.failures:
        raise ApplyError("; ".join(summary.failures))


def _slug_for_title(title: str) -> str:
    """Slugify ``title`` the same way Confluence builds page URLs.

    Mirrors ``mdd.confluence.export.make_page_url``: percent-encode all
    URL-special characters, then convert ``%20`` to ``+``.
    """
    return quote(title, safe="").replace("%20", "+")


def _replace_url_slug(url: str, new_title: str) -> str:
    """Return ``url`` with its trailing slug component swapped for ``new_title``.

    The Confluence v2 URL format is ``.../pages/<page_id>/<slug>``.  We
    replace just the segment after the last ``/`` so we don't have to
    know which URL shape the tenant uses (``/wiki/spaces/...`` vs
    ``/spaces/...``).  Returns the original URL unchanged when it has
    no trailing segment to rewrite.
    """
    if not url or "/" not in url:
        return url
    prefix, _, _slug = url.rpartition("/")
    if not prefix:
        return url
    return f"{prefix}/{_slug_for_title(new_title)}"


def _resolve_updated_at(api_result: dict[str, Any]) -> str:
    """Pick a current timestamp for ``confluence.updated_at``.

    Prefers the API's ``version.createdAt`` when present (PUT responses
    populate it).  Falls back to ``datetime.now(UTC)`` for endpoints
    that don't (archive / unarchive v2 returns a slimmer payload).
    """
    page = _v2_page(api_result)
    if page.version is not None and page.version.created_at:
        return page.version.created_at
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _refresh_metadata_after_mutate(
    md_path: Path,
    api_result: dict[str, Any],
    *,
    extra_updates: dict[str, Any] | None = None,
    new_title_for_slug: str | None = None,
) -> None:
    """Rewrite ``confluence.version`` / ``updated_at`` / ``url`` from the API response.

    The rename/move/archive handlers only handle the path change or status
    flip; the version + audit + URL fields must be written by the
    orchestrator.

    When ``new_title_for_slug`` is provided, the trailing slug component
    of ``confluence.url`` is rewritten to match.
    """
    try:
        fm, body = read_frontmatter(md_path)
    except OSError as exc:
        raise ApplyError(f"could not re-read frontmatter at {md_path}: {exc}") from exc
    raw_conf: object = fm.get("confluence")
    if not isinstance(raw_conf, dict):
        return
    conf: dict[str, Any] = raw_conf  # pyright: ignore[reportUnknownVariableType]  # raw frontmatter dict — pyright loses value type after isinstance narrowing
    conf["version"] = _remote_version(api_result)
    conf["updated_at"] = _resolve_updated_at(api_result)
    if new_title_for_slug is not None:
        url_existing = conf.get("url")
        if isinstance(url_existing, str) and url_existing:
            conf["url"] = _replace_url_slug(url_existing, new_title_for_slug)
    if extra_updates:
        conf.update(extra_updates)
    fm["confluence"] = conf
    write_frontmatter(md_path, fm, body)


# ---------------------------------------------------------------------------
# Commit + recovery hint
# ---------------------------------------------------------------------------


def _commit(repo_dir: Path, subject: str, *, no_commit: bool) -> None:
    """Stage and commit a single ``chore(mirror): ...`` summary."""
    if no_commit:
        return
    try:
        _ = git_commit(repo_dir, subject)
    except ApplyError as exc:
        log.warning("commit failed: %s", exc)


def _recovery_hint(exc: Exception) -> str:
    """Format the recovery message used when the API call already succeeded."""
    return (
        f"Confluence updated successfully but local refresh failed: {exc}.\n"
        "Run 'mdd confluence sync-space' to bring the mirror back in agreement."
    )


# ---------------------------------------------------------------------------
# Client + remote-page fetch
# ---------------------------------------------------------------------------


def _make_client(opts: MutateOptions) -> ConfluenceClient:
    def token_resolver() -> str:
        return opts.config.api_token

    return ConfluenceClient(opts.config.url, opts.config.username, token_resolver)


def _fetch_page(client: ConfluenceClient, page_id: str) -> dict[str, Any]:
    try:
        return client.get_page(page_id)
    except ConfluenceError as exc:
        log.error("Confluence API: %s", exc)
        raise _MutateAbort(1) from exc


def _preflight(
    client: ConfluenceClient,
    page_state: _PageState,
    opts: MutateOptions,
) -> dict[str, Any]:
    """Run the shared pre-flight gauntlet and return the remote page payload."""
    _check_dirty(page_state.md_path.parent)
    page_data = _fetch_page(client, page_state.page_id)
    managed_cfg = opts.managed_config if opts.managed_config is not None else load_managed_config()
    _check_managed(page_data, client, managed_cfg)
    _check_version(page_state.version, _remote_version(page_data))
    return page_data


# ---------------------------------------------------------------------------
# Subject lines
# ---------------------------------------------------------------------------


def _render_subject(action: str, old: str, new: str | None, *, override: str) -> str:
    if override:
        return override
    if action == "rename":
        return f'chore(mirror): rename "{old}" -> "{new}"'
    if action == "move":
        return f'chore(mirror): move "{old}" to "{new}"'
    if action == "archive":
        return f'chore(mirror): archive "{old}"'
    return f'chore(mirror): unarchive "{old}"'


# ---------------------------------------------------------------------------
# rename_page
# ---------------------------------------------------------------------------


def rename_page(md_path: Path, new_title: str, *, opts: MutateOptions) -> int:
    """Rename the Confluence page backing ``md_path`` to ``new_title``.

    Returns 0 on success or clean dry-run; 1 on any failure.
    """
    try:
        page_state = _load_local(md_path)
        with _make_client(opts) as client:
            page_data = _preflight(client, page_state, opts)
            preview = (
                f'Rename: "{page_state.title}" -> "{new_title}"\n'
                f"        space {page_state.space_key}, page {page_state.page_id}"
            )
            if not _prompt(preview, yes=opts.yes):
                return 0
            if opts.dry_run:
                log.info("(dry-run, no changes made)")
                return 0
            result = client.put_page(
                page_state.page_id,
                new_title,
                _extract_storage_body(page_data),
                page_state.version + 1,
                opts.message or "Renamed via mdd",
                options=PutPageOptions(
                    parent_id=page_state.parent_id,
                    status=_remote_status(page_data),
                ),
            )
            return _finish_rename(page_state, new_title, result, opts)
    except _MutateAbort as abort:
        return abort.rc


def _finish_rename(
    page_state: _PageState,
    new_title: str,
    api_result: dict[str, Any],
    opts: MutateOptions,
) -> int:
    """Apply the local refresh + commit half of ``rename_page``."""
    event = _build_event(EventKind.RENAME, page_state, new_title=new_title)
    try:
        new_path = _apply_rename_or_move(event, page_state, page_state.md_path.parent)
        # No `title` in extra_updates: the body-H1 rewrite in
        # `apply_renames_moves` is the single source of truth for the
        # title-on-disk.  `confluence.title:` in
        # frontmatter is a deprecated audit field no consumer reads.
        # Pass new_title_for_slug so the `confluence.url` trailing slug
        # is refreshed to match the new title.
        _refresh_metadata_after_mutate(new_path, api_result, new_title_for_slug=new_title)
    except (ApplyError, OSError) as exc:
        log.error("%s", _recovery_hint(exc))
        return 1
    subject = _render_subject("rename", page_state.title, new_title, override=opts.message)
    _commit(page_state.md_path.parent, subject, no_commit=opts.no_commit)
    return 0


# ---------------------------------------------------------------------------
# move_page
# ---------------------------------------------------------------------------


def move_page(md_path: Path, parent_ref: str, *, opts: MutateOptions) -> int:
    """Move the Confluence page backing ``md_path`` to a new parent."""
    try:
        page_state = _load_local(md_path)
        config_host = urlparse(opts.config.url).hostname or None
        new_parent_id = _resolve_parent(parent_ref, config_host=config_host)
        with _make_client(opts) as client:
            page_data = _preflight(client, page_state, opts)
            parent_data = _fetch_page(client, new_parent_id)
            _check_same_space(page_state, parent_data)
            preview = (
                f'Move: "{page_state.title}" (page {page_state.page_id})\n'
                f"      to parent {_remote_title(parent_data)!r} (page {new_parent_id})"
            )
            if not _prompt(preview, yes=opts.yes):
                return 0
            if opts.dry_run:
                log.info("(dry-run, no changes made)")
                return 0
            result = client.put_page(
                page_state.page_id,
                page_state.title,
                _extract_storage_body(page_data),
                page_state.version + 1,
                opts.message or "Moved via mdd",
                options=PutPageOptions(
                    parent_id=new_parent_id,
                    status=_remote_status(page_data),
                ),
            )
            return _finish_move(page_state, new_parent_id, result, parent_data, client, opts)
    except _MutateAbort as abort:
        return abort.rc


@dataclass(frozen=True)
class _MaterialisedStep:
    """One materialised ancestor — used to build the commit body."""

    page_id: str
    new_path: Path  # absolute path of the resulting ``_index.md``


def _materialise_chain(
    chain: list[AncestorStep],
    client: ConfluenceClient,
    repo_dir: Path,
) -> list[_MaterialisedStep]:
    """Walk *chain* top-to-bottom, materialising any ``absent`` or ``flat`` step.

    Returns the list of materialised steps so the commit body can list them.
    Raises :class:`ApplyError`, :class:`ConfluenceError`, or :class:`OSError`
    if a step fails — partial materialisation is acceptable, and the
    caller surfaces the recovery hint.
    """
    materialised: list[_MaterialisedStep] = []
    for step in chain:
        if step.state == "dir":
            continue
        if step.state == "flat":
            # ``state == "flat"`` invariant: AncestorStep populates flat_md_path.
            if step.flat_md_path is None:
                raise ApplyError(f"flat ancestor {step.page_id!r} missing flat_md_path")
            new_path = promote_flat_to_dir(step.flat_md_path, step.expected_dir, repo_dir)
        else:  # absent
            result = pull_single_page(client, step.page_id, step.expected_dir)
            new_path = result.written_path
        materialised.append(_MaterialisedStep(page_id=step.page_id, new_path=new_path))
    return materialised


def _build_move_commit_body(
    page_state: _PageState,
    api_result: dict[str, Any],
    materialised: list[_MaterialisedStep],
    old_path: Path,
    new_path: Path,
    repo_dir: Path,
) -> str:
    """Compose the structured body for a ``chore(mirror): move ...`` commit.

    The body lists every materialised ancestor and the moved file in
    repo-relative form.  Returns ``""`` when no materialisation happened —
    the commit then carries the subject only.
    """
    if not materialised:
        return ""

    page = _v2_page(api_result)
    url = page.links.webui if page.links is not None else ""
    lines: list[str] = [
        "",
        "Confluence -> mirror:",
        f"  page_id: {page_state.page_id}",
        f"  space:   {page_state.space_key}",
    ]
    if url:
        lines.append(f"  url:     {url}")
    lines.append("materialised ancestors (pulled from Confluence):")
    for step in materialised:
        try:
            rel = step.new_path.relative_to(repo_dir)
        except ValueError:
            rel = step.new_path
        lines.append(f"  {rel}  (page {step.page_id})")
    try:
        old_rel: Path | str = old_path.relative_to(repo_dir)
    except ValueError:
        old_rel = old_path
    try:
        new_rel: Path | str = new_path.relative_to(repo_dir)
    except ValueError:
        new_rel = new_path
    lines.append("moved:")
    lines.append(f"  {old_rel} -> {new_rel}")
    return "\n".join(lines)


def _finish_move(
    page_state: _PageState,
    new_parent_id: str,
    api_result: dict[str, Any],
    parent_data: dict[str, Any],
    client: ConfluenceClient,
    opts: MutateOptions,
) -> int:
    """Apply the local refresh + commit half of ``move_page``.

    Walks the new parent's ancestor chain (
    :func:`mdd.confluence.tree.ancestor_chain_for_move`), materialises
    any link that is missing (``pull_single_page``) or flat
    (``promote_flat_to_dir``), then ``git_mv``s the moved file into the
    now-present parent directory and refreshes its frontmatter.
    Materialised paths are listed in the commit body.

    Partial materialisation on failure is acceptable: the Confluence
    move is the source of truth and is not rolled back; ``sync-space``
    reconciles half-built state.  The user sees the standard recovery
    hint and the command exits 1.
    """
    repo_dir = page_state.md_path.parent
    try:
        chain = ancestor_chain_for_move(
            client, new_parent_id, page_state.space_id, _move_output_root(page_state.md_path)
        )
        materialised = _materialise_chain(chain, client, repo_dir)
        new_parent_dir = chain[-1].expected_dir
        event = _build_event(EventKind.MOVE, page_state, new_parent_id=new_parent_id)
        old_path = page_state.md_path
        new_path = _apply_rename_or_move(event, page_state, repo_dir, new_parent_dir=new_parent_dir)
        _refresh_metadata_after_mutate(
            new_path,
            api_result,
            extra_updates={"parent_id": new_parent_id},
        )
    except (ApplyError, ConfluenceError, OSError) as exc:
        log.error("%s", _recovery_hint(exc))
        return 1
    subject = _render_subject(
        "move", page_state.title, _remote_title(parent_data), override=opts.message
    )
    body = _build_move_commit_body(
        page_state, api_result, materialised, old_path, new_path, repo_dir
    )
    message = f"{subject}\n{body}" if body else subject
    _commit(repo_dir, message, no_commit=opts.no_commit)
    return 0


def _move_output_root(md_path: Path) -> Path:
    """Return the mirror root for ancestor-walk path resolution.

    For the imperative ``move-page`` path the mirror root is the
    directory containing the moved file — we don't have a full
    :class:`MirrorState`.  This is sufficient for same-space moves
    because every same-space ancestor's expected mirror dir is a
    descendant of (or equal to) this root.
    """
    return md_path.parent


# ---------------------------------------------------------------------------
# archive_page / unarchive_page
# ---------------------------------------------------------------------------


def archive_page(md_path: Path, *, opts: MutateOptions) -> int:
    """Archive the Confluence page backing ``md_path``."""
    return _archive_dispatch(md_path, action="archive", opts=opts)


def unarchive_page(md_path: Path, *, opts: MutateOptions) -> int:
    """Unarchive the Confluence page backing ``md_path``."""
    return _archive_dispatch(md_path, action="unarchive", opts=opts)


def _call_archive_api(
    client: ConfluenceClient, page_id: str, action: str, *, message: str
) -> dict[str, Any]:
    """Dispatch to ``archive_page`` / ``unarchive_page`` with a default message."""
    default_msg = "Archived via mdd" if action == "archive" else "Unarchived via mdd"
    api_msg = message or default_msg
    if action == "archive":
        return client.archive_page(page_id, message=api_msg)
    return client.unarchive_page(page_id, message=api_msg)


def _archive_preview(page_state: _PageState, action: str) -> str:
    verb = "Archive" if action == "archive" else "Unarchive"
    return (
        f'{verb}: "{page_state.title}" (page {page_state.page_id})\n'
        f"        space {page_state.space_key}"
    )


def _archive_dispatch(md_path: Path, *, action: str, opts: MutateOptions) -> int:
    try:
        page_state = _load_local(md_path)
        with _make_client(opts) as client:
            _ = _preflight(client, page_state, opts)
            if not _prompt(_archive_preview(page_state, action), yes=opts.yes):
                return 0
            if opts.dry_run:
                log.info("(dry-run, no changes made)")
                return 0
            result = _call_archive_api(client, page_state.page_id, action, message=opts.message)
            return _finish_archive(page_state, action, result, opts)
    except _MutateAbort as abort:
        return abort.rc


def _finish_archive(
    page_state: _PageState,
    action: str,
    api_result: dict[str, Any],
    opts: MutateOptions,
) -> int:
    kind = EventKind.ARCHIVE if action == "archive" else EventKind.UNARCHIVE
    new_status_lc = "archived" if action == "archive" else "current"
    event = _build_event(kind, page_state, new_status=new_status_lc)
    try:
        _apply_archive_refresh(event, page_state)
        # The archive handler only flips status; we still need to write the
        # bumped version / updated_at from the API response.  Status is
        # lowercase end-to-end.
        _refresh_metadata_after_mutate(
            page_state.md_path,
            api_result,
            extra_updates={"status": new_status_lc},
        )
    except (ApplyError, OSError) as exc:
        log.error("%s", _recovery_hint(exc))
        return 1
    subject = _render_subject(action, page_state.title, None, override=opts.message)
    _commit(page_state.md_path.parent, subject, no_commit=opts.no_commit)
    return 0
