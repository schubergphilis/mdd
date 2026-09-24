"""Update a Confluence page from a local Markdown file."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from mdd.confluence.attachments import (
    AttachmentCollisionError,
    AttachmentManifestEntry,
    sync_attachments_for_update,
)
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.diff import unified_xhtml_diff
from mdd.confluence.frontmatter import pin_mtime_to_exported_at
from mdd.confluence.frontmatter import read as read_frontmatter
from mdd.confluence.frontmatter import write as write_frontmatter
from mdd.confluence.header import (
    get_mirror_url,
    insert_mdd_footer,
    strip_export_header,
    strip_export_title_h1,
)
from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.confluence.managed import (
    ManagedCheckError,
    ManagedConfig,
    classify_page,
    load_managed_config,
    resolve_page_info,
)
from mdd.confluence.mermaid import render_mermaid_fences
from mdd.confluence.page_links import resolve_page_links
from mdd.confluence.remote_space import RemotePage, describe_remote_page, space_mismatch
from mdd.confluence.title import resolve_page_title
from mdd.confluence.version import VersionDriftError, check_version_drift
from mdd.ir import reattach
from mdd.markdown.ir import parse_markdown
from mdd.utils.logging import get_logger
from mdd.utils.terminal import neutralise_lines

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.config import ConfluenceConfig

log = get_logger(__name__)


def _get_page_id(fm: dict[str, Any]) -> str | None:
    """Extract page_id from frontmatter."""
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return None
    conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    pid: Any = conf.get("page_id")  # pyright: ignore[reportAny]
    return str(pid) if pid else None


def _get_conf_str(fm: dict[str, Any], key: str) -> str:
    """Extract a string field of the ``confluence:`` block, or ``""``."""
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return ""
    conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    value: Any = conf.get(key)  # pyright: ignore[reportAny]
    return str(value) if isinstance(value, (str, int)) and value != "" else ""


def _get_version(fm: dict[str, Any]) -> int | None:
    """Extract version number from frontmatter."""
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return None
    conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    v: Any = conf.get("version")  # pyright: ignore[reportAny]
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


def _get_attachments(fm: dict[str, Any]) -> list[AttachmentManifestEntry]:
    """Extract attachment manifest from frontmatter."""
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return []
    conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    raw: Any = conf.get("attachments")  # pyright: ignore[reportAny]
    if not isinstance(raw, list):
        return []
    result: list[AttachmentManifestEntry] = []
    for item in raw:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(item, dict):
            continue
        item_d: dict[str, Any] = dict(item.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        fn: Any = item_d.get("filename")  # pyright: ignore[reportAny]
        sh: Any = item_d.get("sha256")  # pyright: ignore[reportAny]
        vn: Any = item_d.get("version")  # pyright: ignore[reportAny]
        if not fn or not sh:
            continue
        result.append(
            AttachmentManifestEntry(
                filename=str(fn),
                sha256=str(sh),
                version=int(vn) if isinstance(vn, int) else (str(vn) if vn else 1),
            )
        )
    return result


def _get_remote_storage(page_data: dict[str, Any]) -> str:
    """Extract storage XHTML value from a page API response."""
    body_raw: Any = page_data.get("body")  # pyright: ignore[reportAny]
    if not isinstance(body_raw, dict):
        return ""
    body_dict: dict[str, Any] = body_raw  # pyright: ignore[reportUnknownVariableType]
    storage_raw: Any = body_dict.get("storage")  # pyright: ignore[reportAny]
    if not isinstance(storage_raw, dict):
        return ""
    storage_dict: dict[str, Any] = storage_raw  # pyright: ignore[reportUnknownVariableType]
    val: Any = storage_dict.get("value")  # pyright: ignore[reportAny]
    return str(val) if isinstance(val, str) else ""


def _get_remote_version(page_data: dict[str, Any]) -> int:
    """Extract version number from a page API response."""
    v_raw: Any = page_data.get("version")  # pyright: ignore[reportAny]
    if isinstance(v_raw, dict):
        v_dict: dict[str, Any] = v_raw  # pyright: ignore[reportUnknownVariableType]
        n: Any = v_dict.get("number")  # pyright: ignore[reportAny]
        return int(n) if isinstance(n, int) else 1
    return 1


def _resolve_user(client: ConfluenceClient, account_id: str) -> str:
    try:
        user = client.get_user(account_id)
        dn: Any = user.get("displayName", "")  # pyright: ignore[reportAny]
        return str(dn) if dn else ""
    except ConfluenceError as exc:
        log.warning("could not resolve display name for account %r: %s", account_id, exc)
        return ""


_SHRINK_THRESHOLD = 0.10  # body must retain at least 10 % of remote length
_STALE_CONF_FIELDS = ("title", "version_message", "created_at", "created_by", "source_format")


def _rewrite_frontmatter(  # noqa: PLR0913
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    *,
    result: dict[str, Any],
    new_version: int,
    updated_manifest: list[AttachmentManifestEntry],
    client: ConfluenceClient,
) -> None:
    """Update the ``confluence:`` frontmatter block after a successful PUT."""
    exported_at = datetime.now(UTC).isoformat()

    result_version_raw: Any = result.get("version")  # pyright: ignore[reportAny]
    actual_version: int = new_version
    updater_id: str | None = None
    actual_updated_at: str = exported_at

    if isinstance(result_version_raw, dict):
        rv_dict: dict[str, Any] = result_version_raw  # pyright: ignore[reportUnknownVariableType]
        n: Any = rv_dict.get("number")  # pyright: ignore[reportAny]
        actual_version = int(n) if isinstance(n, int) else new_version
        aid: Any = rv_dict.get("authorId")  # pyright: ignore[reportAny]
        updater_id = str(aid) if isinstance(aid, str) and aid else None
        uat: Any = rv_dict.get("createdAt")  # pyright: ignore[reportAny]
        actual_updated_at = str(uat) if isinstance(uat, str) and uat else exported_at

    updated_by = _resolve_user(client, updater_id) if updater_id else ""

    conf_block = _confluence_block(frontmatter)
    if conf_block is None:
        return
    conf_block["version"] = actual_version
    conf_block["updated_at"] = actual_updated_at
    conf_block["updated_by"] = updated_by
    conf_block["exported_at"] = exported_at
    for _stale in _STALE_CONF_FIELDS:
        conf_block.pop(_stale, None)
    _set_attachment_manifest(conf_block, updated_manifest)

    write_frontmatter(md_path, frontmatter, body_md)


def _confluence_block(frontmatter: dict[str, Any]) -> dict[str, Any] | None:
    """Return the mutable ``confluence:`` mapping of *frontmatter*, if any."""
    conf_fm: Any = frontmatter.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_fm, dict):
        return None
    conf_block: dict[str, Any] = conf_fm  # pyright: ignore[reportUnknownVariableType]
    return conf_block


def _set_attachment_manifest(
    conf_block: dict[str, Any], manifest: list[AttachmentManifestEntry]
) -> None:
    """Store *manifest* as ``attachments`` in *conf_block*, dropping the key when empty."""
    attachments_list: list[dict[str, Any]] = [
        {"filename": e.filename, "sha256": e.sha256, "version": e.version} for e in manifest
    ]
    if attachments_list:
        conf_block["attachments"] = attachments_list
    else:
        conf_block.pop("attachments", None)


def _record_attachment_manifest(
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    manifest: list[AttachmentManifestEntry],
) -> None:
    """Persist *manifest* after an attachment-only push.

    The page body got no new version, so the version, ``updated_at`` and
    ``updated_by`` fields stay as they are.
    """
    conf_block = _confluence_block(frontmatter)
    if conf_block is None:
        return
    _set_attachment_manifest(conf_block, manifest)
    write_frontmatter(md_path, frontmatter, body_md)


class PushOutcome(Enum):
    """What a push did to the remote page."""

    PUSHED = "pushed"
    """A new page version was sent."""
    ATTACHMENTS_ONLY = "attachments-only"
    """Attachments were uploaded; the page body got no new version."""
    NO_CHANGE = "no-change"
    """Local and remote already matched; nothing was sent."""
    NOT_PUSHED = "not-pushed"
    """Dry run, or the operator declined the confirmation prompt."""
    FAILED = "failed"
    """An error, conflict or managed-page refusal stopped the push."""

    @property
    def sent_changes(self) -> bool:
        """True when Confluence received a new page version or attachment."""
        return self in {PushOutcome.PUSHED, PushOutcome.ATTACHMENTS_ONLY}


class _UpdateAbort(Exception):
    """Internal sentinel: a sub-step has logged an error and stopped the push.

    ``update_page_outcome`` turns it into :attr:`PushOutcome.FAILED`.
    """


@dataclass(frozen=True)
class _LocalSpec:
    """Validated inputs derived from the local file's frontmatter and body."""

    page_id: str
    local_version: int
    title: str
    attachment_manifest: list[AttachmentManifestEntry]


def _read_local(md_path: Path) -> tuple[dict[str, Any], str]:
    """Read frontmatter + body, raising ``_UpdateAbort`` on read failure."""
    try:
        return read_frontmatter(md_path)
    except OSError as exc:
        log.error("reading %s: %s", md_path, exc)
        raise _UpdateAbort() from exc


def _build_local_spec(md_path: Path, frontmatter: dict[str, Any], body_md: str) -> _LocalSpec:
    """Validate the frontmatter and derive the inputs needed for the push."""
    page_id = _get_page_id(frontmatter)
    if not page_id:
        log.error(
            "%s is missing 'confluence.page_id' in frontmatter. "
            "Run 'mdd confluence export page' first, or 'mdd confluence create page' "
            "if this is a new page.",
            md_path,
        )
        raise _UpdateAbort()
    local_version = _get_version(frontmatter)
    if local_version is None:
        log.error("%s is missing 'confluence.version' in frontmatter.", md_path)
        raise _UpdateAbort()
    return _LocalSpec(
        page_id=page_id,
        local_version=local_version,
        title=resolve_page_title(frontmatter, body_md, md_path),
        attachment_manifest=_get_attachments(frontmatter),
    )


def _fetch_and_check_managed(
    client: ConfluenceClient,
    page_id: str,
    managed_config: ManagedConfig | None,
) -> dict[str, Any]:
    """Fetch the remote page and refuse if it is externally managed."""
    try:
        page_data = client.get_page(page_id)
    except ConfluenceError as exc:
        log.error("Confluence API: %s", exc)
        raise _UpdateAbort() from exc

    cfg = managed_config if managed_config is not None else load_managed_config()
    body_storage_for_check = _get_remote_storage(page_data)
    try:
        page_info = resolve_page_info(client, page_data, body_storage_for_check, cfg)
    except ManagedCheckError as exc:
        log.error("%s. Refusing to push a page that could not be checked.", exc)
        raise _UpdateAbort() from exc
    classification = classify_page(page_info, cfg, client)
    if classification.is_managed:
        msg = classification.message or (
            f"This page is managed by {classification.publisher_name!r}. "
            "Edit at the source; do not update via mdd."
        )
        log.error("%s", msg)
        raise _UpdateAbort()
    return page_data


def _check_remote_space(md_path: Path, frontmatter: dict[str, Any], remote: RemotePage) -> None:
    """Refuse to push when the page is not in the space the frontmatter names.

    The page id in frontmatter picks the target page; the space fields in
    the same frontmatter say where the file expects it to be. A page that
    Confluence reports in a different space is refused rather than pushed.
    """
    refusal = space_mismatch(
        remote,
        local_space_key=_get_conf_str(frontmatter, "space_key"),
        local_space_id=_get_conf_str(frontmatter, "space_id"),
    )
    if refusal:
        log.error("%s: %s", md_path, refusal)
        raise _UpdateAbort()


def _check_no_remote_advance(remote_version: int, local_version: int) -> None:
    """Refuse to push when the remote has advanced past the local snapshot.

    Delegates to ``mdd.confluence.version.check_version_drift`` so the same
    wording is shared with the mutate orchestrators.
    """
    try:
        check_version_drift(local_version, remote_version)
    except VersionDriftError as exc:
        log.error("%s", exc)
        raise _UpdateAbort() from None


def _check_body_safety(
    md_path: Path,
    body_stripped: str,
    remote_storage: str,
    *,
    allow_empty: bool,
    allow_shrink: bool,
) -> None:
    """Refuse to push a body that looks like accidental content loss."""
    if not body_stripped.strip():
        if allow_empty:
            return
        log.error(
            "%s body is empty after stripping the export header. "
            "Refusing to wipe the remote page. Fix the file, or pass "
            "--allow-empty to explicitly clear the page.",
            md_path,
        )
        raise _UpdateAbort()
    if not remote_storage or allow_shrink:
        return
    remote_len = len(remote_storage)
    local_len = len(body_stripped)
    if local_len < remote_len * _SHRINK_THRESHOLD:
        log.error(
            "local body (%d chars) is less than %d %% of the remote body "
            "(%d chars). "
            "This looks like accidental content loss. Re-export and reconcile, "
            "or pass --allow-shrink to override.",
            local_len,
            int(_SHRINK_THRESHOLD * 100),
            remote_len,
        )
        raise _UpdateAbort()


def _render_body_xhtml(
    md_path: Path,
    body_stripped: str,
    remote_storage: str,
    *,
    resolve_links: bool = True,
) -> str:
    """Render the local markdown to storage XHTML, grafting remote identity attrs.

    With *resolve_links*, relative ``.md`` links become Confluence page links
    before the graft; the source file is the base for relative paths.

    ``reattach`` grafts identity attributes (``local-id``, ``macro-id``,
    ``schema-version``, ``ac:breakout-*`` …) from the remote storage IR onto
    the freshly-parsed-from-markdown IR. Without this step every round-trip
    strips identity from layout/section/cell/macro/paragraph nodes because
    the markdown leg intentionally does not carry them. New
    blocks the user authored locally have no match in the remote IR and
    render without identity — Confluence assigns fresh ids on save, which
    is what we want.
    """
    try:
        ir_remote = parse_confluence_storage(remote_storage, mode="preserving")
        ir_local = parse_markdown(body_stripped)
        if resolve_links:
            ir_local = resolve_page_links(ir_local, md_path, body_md=body_stripped)
        ir_grafted = reattach(ir_local, ir_remote)
        body_xhtml = render_confluence_storage(ir_grafted, mode="preserving")
    except (ValueError, KeyError) as exc:
        log.error("markdown conversion: %s", exc)
        raise _UpdateAbort() from exc
    return insert_mdd_footer(body_xhtml, get_mirror_url(md_path))


def _print_diff_or_noop(body_xhtml: str, remote_storage: str) -> str:
    """Print the diff (or no-op note) and return the diff string for the caller.

    The printed copy has control characters neutralised, since both sides
    carry page content; the returned diff is the unmodified text.
    """
    diff = unified_xhtml_diff(body_xhtml, remote_storage)
    if diff:
        log.info("%s", neutralise_lines(diff))
        return diff
    if body_xhtml != remote_storage:
        log.info("local and remote differ only in whitespace (no update needed).")
    log.info("No changes detected (diff is empty after normalization).")
    return diff


def _count_changed_lines(diff: str) -> tuple[int, int]:
    """Return ``(added, removed)`` line counts of a unified diff, headers excluded."""
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++ "):
            added += 1
        elif line.startswith("-") and not line.startswith("--- "):
            removed += 1
    return added, removed


@dataclass(frozen=True)
class _PushPreview:
    """What a push is about to send, for the summary shown before confirming."""

    remote: RemotePage
    new_title: str
    diff: str
    attachments_pending: bool


def _push_summary(preview: _PushPreview) -> str:
    """Render the target line plus a one-line change count for the push.

    Titles and the space key come from Confluence and the mirror, so
    control characters in them are neutralised.
    """
    remote = preview.remote
    lines = [f'Update: "{remote.title}" (page {remote.page_id}) in space {remote.space_label}']
    if preview.new_title != remote.title:
        lines.append(f'  new title: "{preview.new_title}"')
    if preview.diff:
        added, removed = _count_changed_lines(preview.diff)
        detail = "" if log.isEnabledFor(logging.INFO) else " (run with -v to see the diff)"
        lines.append(f"  page body: {added + removed} lines changed (+{added} -{removed}){detail}")
    else:
        lines.append("  page body: unchanged")
    if preview.attachments_pending:
        lines.append("  attachments: changes will be uploaded")
    return neutralise_lines("\n".join(lines))


def _show_push_summary(preview: _PushPreview) -> None:
    """Print the push summary to stderr, where the confirmation prompt appears."""
    print(_push_summary(preview), file=sys.stderr, flush=True)  # noqa: T201  # program output


def _confirm_push(preview: _PushPreview, *, yes: bool) -> bool:
    """Return True iff the user confirmed (or ``--yes`` was passed).

    The target page and a change summary are shown before the question;
    with ``--yes`` they are logged instead.
    """
    if yes:
        log.info("%s", _push_summary(preview))
        return True
    if not sys.stdin.isatty():
        log.error("stdin is not a TTY. Use --yes to confirm non-interactively.")
        raise _UpdateAbort()
    _show_push_summary(preview)
    try:
        answer = input("Push these changes? [y/N] ").strip().lower()
    except EOFError, KeyboardInterrupt:
        log.info("Aborted.")
        return False
    return answer == "y"


def _put_with_409_message(
    client: ConfluenceClient,
    page_id: str,
    title: str,
    body_xhtml: str,
    new_version: int,
    message: str,
) -> dict[str, Any]:
    """PUT the page, translating 409 conflicts into the friendly conflict guidance."""
    try:
        return client.put_page(page_id, title, body_xhtml, new_version, message)
    except ConfluenceError as exc:
        if "409" in str(exc):
            # Another writer bumped the page between our GET and PUT.
            log.error(
                "Conflict: the page was updated remotely between fetch and push "
                "(version conflict - HTTP 409). "
                "Re-export the page to get the latest version, reconcile manually, "
                "then re-run update.",
            )
            raise _UpdateAbort() from exc
        log.error("Confluence API: %s", exc)
        raise _UpdateAbort() from exc


def _sync_attachments(
    client: ConfluenceClient,
    spec: _LocalSpec,
    body_stripped: str,
    md_path: Path,
    *,
    dry_run: bool,
) -> tuple[list[AttachmentManifestEntry], str] | None:
    """Sync (or, with *dry_run*, only plan) the page's local image attachments.

    Returns ``(manifest, body to render)`` or ``None`` after logging the error.
    """
    try:
        return sync_attachments_for_update(
            client,
            spec.page_id,
            body_stripped,
            md_path.parent,
            spec.attachment_manifest,
            attachments_dir=md_path.parent / f"{md_path.stem}-attachments",
            dry_run=dry_run,
        )
    except (ConfluenceError, AttachmentCollisionError, OSError) as exc:
        log.error("attachment sync: %s", exc)
        return None


def _manifest_changed(
    before: list[AttachmentManifestEntry], after: list[AttachmentManifestEntry]
) -> bool:
    """True when *after* names or hashes any attachment differently from *before*."""
    return {(e.filename, e.sha256) for e in before} != {(e.filename, e.sha256) for e in after}


def _push_page(  # noqa: PLR0913
    client: ConfluenceClient,
    spec: _LocalSpec,
    page_data: dict[str, Any],
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    *,
    remote: RemotePage,
    message: str,
    yes: bool,
    dry_run: bool,
    allow_empty: bool,
    allow_shrink: bool,
    resolve_links: bool = True,
) -> PushOutcome:
    """Run the post-fetch lifecycle: safety checks, render, diff, PUT, frontmatter."""
    remote_version = _get_remote_version(page_data)
    _check_no_remote_advance(remote_version, spec.local_version)

    body_stripped = strip_export_title_h1(strip_export_header(body_md), spec.title)
    remote_storage = _get_remote_storage(page_data)
    _check_body_safety(
        md_path,
        body_stripped,
        remote_storage,
        allow_empty=allow_empty,
        allow_shrink=allow_shrink,
    )
    # After the safety guard, which must judge the author's body, and before
    # attachment sync, which uploads and rasterizes the rendered SVGs.
    body_stripped = render_mermaid_fences(body_stripped, md_path)

    # Plan-only pass: lists what would be uploaded and rewrites the body the
    # way a real sync would, without touching Confluence. Uploads happen
    # only after the operator has seen the preview and confirmed.
    planned = _sync_attachments(client, spec, body_stripped, md_path, dry_run=True)
    if planned is None:
        raise _UpdateAbort()
    planned_manifest, preview_body = planned
    attachments_pending = _manifest_changed(spec.attachment_manifest, planned_manifest)

    body_xhtml = _render_body_xhtml(
        md_path, preview_body, remote_storage, resolve_links=resolve_links
    )
    diff = _print_diff_or_noop(body_xhtml, remote_storage)
    preview = _PushPreview(
        remote=remote,
        new_title=spec.title,
        diff=diff,
        attachments_pending=attachments_pending,
    )
    if dry_run:
        _show_push_summary(preview)
        return PushOutcome.NOT_PUSHED
    if not diff and not attachments_pending:
        # The file matches the remote page, so it is no longer a local edit.
        # Pin mtime rather than restamping exported_at, so the file content
        # stays untouched.
        pin_mtime_to_exported_at(md_path, frontmatter)
        return PushOutcome.NO_CHANGE
    if not diff:
        log.info("Only attachments changed; the page body will not get a new version.")
    if not _confirm_push(preview, yes=yes):
        return PushOutcome.NOT_PUSHED

    synced = _sync_attachments(client, spec, body_stripped, md_path, dry_run=False)
    if synced is None:
        raise _UpdateAbort()
    updated_manifest, body_stripped = synced
    if not diff:
        # Only attachments changed; the page body itself needs no new version.
        _record_attachment_manifest(md_path, frontmatter, body_md, updated_manifest)
        pin_mtime_to_exported_at(md_path, frontmatter)
        return PushOutcome.ATTACHMENTS_ONLY
    body_xhtml = _render_body_xhtml(
        md_path, body_stripped, remote_storage, resolve_links=resolve_links
    )

    new_version = remote_version + 1
    result = _put_with_409_message(
        client, spec.page_id, spec.title, body_xhtml, new_version, message
    )
    _rewrite_frontmatter(
        md_path,
        frontmatter,
        body_md,
        result=result,
        new_version=new_version,
        updated_manifest=updated_manifest,
        client=client,
    )
    # The file now holds exactly what was pushed, so it is not a local edit.
    pin_mtime_to_exported_at(md_path, frontmatter)
    return PushOutcome.PUSHED


def update_page_outcome(  # noqa: PLR0913
    md_path: Path,
    config: ConfluenceConfig,
    *,
    dry_run: bool = False,
    message: str = "Updated via mdd",
    yes: bool = False,
    allow_empty: bool = False,
    allow_shrink: bool = False,
    managed_config: ManagedConfig | None = None,
    resolve_links: bool = True,
) -> PushOutcome:
    """Update a Confluence page from a local Markdown file and say what happened.

    Args:
        md_path:        Path to the local ``.md`` file.
        config:         Resolved Confluence connection config.
        dry_run:        Show diff but do not push.
        message:        Version comment stored in page history.
        yes:            Skip the interactive prompt.
        allow_empty:    Allow replacing the remote page body with an empty body.
        allow_shrink:   Allow the local body to be less than 10 % of the remote body.
        managed_config: Pre-loaded ManagedConfig for managed-elsewhere detection.
                        When None, loaded lazily on first page-fetch.
        resolve_links:  Rewrite relative ``.md`` links to Confluence page links
                        before rendering.

    Returns:
        The :class:`PushOutcome`; ``FAILED`` on error, conflict, or
        managed-page refusal.
    """
    try:
        frontmatter, body_md = _read_local(md_path)
        spec = _build_local_spec(md_path, frontmatter, body_md)

        def token_resolver() -> str:
            return config.api_token

        with ConfluenceClient(config.url, config.username, token_resolver) as client:
            page_data = _fetch_and_check_managed(client, spec.page_id, managed_config)
            remote = describe_remote_page(client, page_data)
            _check_remote_space(md_path, frontmatter, remote)
            return _push_page(
                client,
                spec,
                page_data,
                md_path,
                frontmatter,
                body_md,
                remote=remote,
                message=message,
                yes=yes,
                dry_run=dry_run,
                allow_empty=allow_empty,
                allow_shrink=allow_shrink,
                resolve_links=resolve_links,
            )
    except _UpdateAbort:
        return PushOutcome.FAILED


def update_page(  # noqa: PLR0913
    md_path: Path,
    config: ConfluenceConfig,
    *,
    dry_run: bool = False,
    message: str = "Updated via mdd",
    yes: bool = False,
    allow_empty: bool = False,
    allow_shrink: bool = False,
    managed_config: ManagedConfig | None = None,
    resolve_links: bool = True,
) -> int:
    """Update a Confluence page from a local Markdown file.

    Takes the same arguments as :func:`update_page_outcome`.

    Returns:
        0 on success or no-op; 1 on error, conflict, or managed-page refusal.
    """
    outcome = update_page_outcome(
        md_path,
        config,
        dry_run=dry_run,
        message=message,
        yes=yes,
        allow_empty=allow_empty,
        allow_shrink=allow_shrink,
        managed_config=managed_config,
        resolve_links=resolve_links,
    )
    return 1 if outcome is PushOutcome.FAILED else 0
