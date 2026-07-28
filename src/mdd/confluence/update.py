"""Update a Confluence page from a local Markdown file (spec 009c)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mdd.confluence.attachments import (
    AttachmentCollisionError,
    AttachmentManifestEntry,
    sync_attachments_for_update,
)
from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.diff import unified_xhtml_diff
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
    ManagedConfig,
    build_page_info_from_page_data,
    classify_page,
    load_managed_config,
)
from mdd.confluence.version import VersionDriftError, check_version_drift
from mdd.ir import reattach
from mdd.markdown.ir import parse_markdown
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.confluence.config import ConfluenceConfig

log = get_logger(__name__)


def _extract_title(body_md: str, md_path: Path) -> str:
    """First ATX H1 in the body; fall back to the markdown filename stem."""
    for line in body_md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return md_path.stem


def _get_page_id(fm: dict[str, Any]) -> str | None:
    """Extract page_id from frontmatter."""
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return None
    conf: dict[str, Any] = dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    pid: Any = conf.get("page_id")  # pyright: ignore[reportAny]
    return str(pid) if pid else None


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

    attachments_list: list[dict[str, Any]] = [
        {"filename": e.filename, "sha256": e.sha256, "version": e.version} for e in updated_manifest
    ]

    conf_fm: Any = frontmatter.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_fm, dict):
        return
    conf_block: dict[str, Any] = conf_fm  # pyright: ignore[reportUnknownVariableType]
    conf_block["version"] = actual_version
    conf_block["updated_at"] = actual_updated_at
    conf_block["updated_by"] = updated_by
    conf_block["exported_at"] = exported_at
    for _stale in _STALE_CONF_FIELDS:
        conf_block.pop(_stale, None)
    if attachments_list:
        conf_block["attachments"] = attachments_list
    else:
        conf_block.pop("attachments", None)

    write_frontmatter(md_path, frontmatter, body_md)


class _UpdateAbort(Exception):
    """Internal sentinel: a sub-step has decided to terminate ``update_page``.

    Carries the integer return code that update_page should produce.
    """

    def __init__(self, rc: int) -> None:
        super().__init__(f"update_page abort rc={rc}")
        self.rc = rc


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
        raise _UpdateAbort(1) from exc


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
        raise _UpdateAbort(1)
    local_version = _get_version(frontmatter)
    if local_version is None:
        log.error("%s is missing 'confluence.version' in frontmatter.", md_path)
        raise _UpdateAbort(1)
    return _LocalSpec(
        page_id=page_id,
        local_version=local_version,
        title=_extract_title(body_md, md_path),
        attachment_manifest=_get_attachments(frontmatter),
    )


def _fetch_and_check_managed(
    client: ConfluenceClient,
    page_id: str,
    managed_config: ManagedConfig | None,
) -> dict[str, Any]:
    """Fetch the remote page and refuse if it is externally managed (spec S26)."""
    try:
        page_data = client.get_page(page_id)
    except ConfluenceError as exc:
        log.error("Confluence API: %s", exc)
        raise _UpdateAbort(1) from exc

    cfg = managed_config if managed_config is not None else load_managed_config()
    body_storage_for_check = _get_remote_storage(page_data)
    page_info = build_page_info_from_page_data(page_data, body_storage_for_check)
    classification = classify_page(page_info, cfg, client)
    if classification.is_managed:
        msg = classification.message or (
            f"This page is managed by {classification.publisher_name!r}. "
            "Edit at the source; do not update via mdd."
        )
        log.error("%s", msg)
        raise _UpdateAbort(1)
    return page_data


def _check_no_remote_advance(remote_version: int, local_version: int) -> None:
    """Refuse to push when the remote has advanced past the local snapshot.

    Delegates to ``mdd.confluence.version.check_version_drift`` so the same
    wording is shared with the S27 mutate orchestrators (P06 phase 1).
    """
    try:
        check_version_drift(local_version, remote_version)
    except VersionDriftError as exc:
        log.error("%s", exc)
        raise _UpdateAbort(1) from None


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
        raise _UpdateAbort(1)
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
        raise _UpdateAbort(1)


def _render_body_xhtml(md_path: Path, body_stripped: str, remote_storage: str) -> str:
    """Render the local markdown to storage XHTML, grafting remote identity attrs.

    ``reattach`` grafts identity attributes (``local-id``, ``macro-id``,
    ``schema-version``, ``ac:breakout-*`` …) from the remote storage IR onto
    the freshly-parsed-from-markdown IR. Without this step every round-trip
    strips identity from layout/section/cell/macro/paragraph nodes because
    the markdown leg intentionally does not carry them (spec S33 §R3). New
    blocks the user authored locally have no match in the remote IR and
    render without identity — Confluence assigns fresh ids on save, which
    is what we want.
    """
    try:
        ir_remote = parse_confluence_storage(remote_storage, mode="preserving")
        ir_local = parse_markdown(body_stripped)
        ir_grafted = reattach(ir_local, ir_remote)
        body_xhtml = render_confluence_storage(ir_grafted, mode="preserving")
    except (ValueError, KeyError) as exc:
        log.error("markdown conversion: %s", exc)
        raise _UpdateAbort(1) from exc
    return insert_mdd_footer(body_xhtml, get_mirror_url(md_path))


def _print_diff_or_noop(body_xhtml: str, remote_storage: str) -> str:
    """Print the diff (or no-op note) and return the diff string for the caller."""
    diff = unified_xhtml_diff(body_xhtml, remote_storage)
    if diff:
        log.info("%s", diff)
        return diff
    if body_xhtml != remote_storage:
        log.info("local and remote differ only in whitespace (no update needed).")
    log.info("No changes detected (diff is empty after normalization).")
    return diff


def _confirm_push(*, yes: bool) -> bool:
    """Return True iff the user confirmed (or ``--yes`` was passed)."""
    if yes:
        return True
    if not sys.stdin.isatty():
        log.error("stdin is not a TTY. Use --yes to confirm non-interactively.")
        raise _UpdateAbort(1)
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
            raise _UpdateAbort(1) from exc
        log.error("Confluence API: %s", exc)
        raise _UpdateAbort(1) from exc


def _push_page(  # noqa: PLR0913
    client: ConfluenceClient,
    spec: _LocalSpec,
    page_data: dict[str, Any],
    md_path: Path,
    frontmatter: dict[str, Any],
    body_md: str,
    *,
    message: str,
    yes: bool,
    dry_run: bool,
    allow_empty: bool,
    allow_shrink: bool,
) -> int:
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

    try:
        updated_manifest, body_stripped = sync_attachments_for_update(
            client,
            spec.page_id,
            body_stripped,
            md_path.parent,
            spec.attachment_manifest,
            attachments_dir=md_path.parent / f"{md_path.stem}-attachments",
        )
    except (ConfluenceError, AttachmentCollisionError, OSError) as exc:
        log.error("attachment sync: %s", exc)
        return 1

    body_xhtml = _render_body_xhtml(md_path, body_stripped, remote_storage)
    diff = _print_diff_or_noop(body_xhtml, remote_storage)
    if not diff or dry_run:
        return 0
    if not _confirm_push(yes=yes):
        return 0

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
    return 0


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
) -> int:
    """Update a Confluence page from a local Markdown file.

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

    Returns:
        0 on success or no-op; 1 on error, conflict, or managed-page refusal.
    """
    try:
        frontmatter, body_md = _read_local(md_path)
        spec = _build_local_spec(md_path, frontmatter, body_md)

        def token_resolver() -> str:
            return config.api_token

        with ConfluenceClient(config.url, config.username, token_resolver) as client:
            page_data = _fetch_and_check_managed(client, spec.page_id, managed_config)
            return _push_page(
                client,
                spec,
                page_data,
                md_path,
                frontmatter,
                body_md,
                message=message,
                yes=yes,
                dry_run=dry_run,
                allow_empty=allow_empty,
                allow_shrink=allow_shrink,
            )
    except _UpdateAbort as abort:
        return abort.rc
