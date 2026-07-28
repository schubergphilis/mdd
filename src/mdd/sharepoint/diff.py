"""diff.py — pure pair classification for SharePoint bidirectional sync (spec S18).

``classify_pair`` computes the :class:`PairAction` for a single
``(Foo.docx, Foo.docx.md)`` pair given the current filesystem state and the
``sync`` block stored in the ``.md`` frontmatter.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import yaml
from pydantic import ValidationError

from mdd.sharepoint.models import SharepointFrontmatter, SharepointSync
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

log = get_logger(__name__)


class PairAction(StrEnum):
    """Outcome classification for a single office-markdown pair."""

    NO_OP = "no_op"
    """Both sides unchanged since last sync."""

    DOCX_TO_MD = "docx_to_md"
    """Office file changed → re-convert to Markdown, overwrite .md."""

    MD_TO_DOCX = "md_to_docx"
    """Markdown changed → render via Quarto, overwrite office file."""

    SKIP_MD_UPDATE = "skip_md_update"
    """Markdown changed but ``update_office`` is False → skip render, warn user.

    Office (.docx/.pptx) is treated as authoritative unless the user explicitly
    opts the pair into md→office rendering by setting ``update_office: true``
    in the sync block. Covers both "md changed alone" and "both changed".
    """

    DIVERGED = "diverged"
    """Both sides changed since last sync (and ``update_office`` is True) →
    write *.from-md.docx candidate."""

    FIRST_SYNC_DOCX_AUTHORITATIVE = "first_sync_docx_authoritative"
    """First encounter of .docx with no .md sibling → convert to .md."""

    FIRST_SYNC_MD_AUTHORITATIVE = "first_sync_md_authoritative"
    """First encounter of .md with no .docx sibling → render to .docx."""

    FIRST_SYNC_BOTH_DOCX_WINS = "first_sync_both_docx_wins"
    """Both files exist but no sync block → treat docx as authoritative, convert to .md."""

    WORD_LOCKED = "word_locked"
    """Word lock file (``~$Foo.docx``) is present → skip entirely."""

    MD_ONLY = "md_only"
    """Only the .md exists — equivalent to FIRST_SYNC_MD_AUTHORITATIVE for doc-only case."""


@dataclass(frozen=True)
class SyncState:
    """The ``sharepoint.sync`` block extracted from ``.md`` frontmatter.

    All string fields may be ``None`` if the block is absent (first sync).
    ``update_office`` defaults to ``False`` (the conservative default — see
    spec S18): md→office rendering only happens when the user explicitly
    opts in.
    """

    office_sha256_at_sync: str | None
    md_sha256_at_sync: str | None
    last_sync: str | None
    converter_version: str | None
    update_office: bool = False


_EMPTY_SYNC_STATE = SyncState(
    office_sha256_at_sync=None,
    md_sha256_at_sync=None,
    last_sync=None,
    converter_version=None,
    update_office=False,
)


def sha256_file(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_md_content(md_path: Path) -> str:
    """Return SHA-256 of *md_path*'s content in canonical form.

    The canonical form strips the ``sharepoint.sync`` block (and an empty
    ``sharepoint`` parent) from the YAML frontmatter and re-serializes via
    ``yaml.safe_dump``. This makes the hash independent of tool-managed
    metadata (timestamps, the recorded hashes themselves), so it stays
    stable across a sync that only restamps the sync block.
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(_canonical_md_bytes(text)).hexdigest()


def _canonical_md_bytes(text: str) -> bytes:
    """Return canonical-form bytes for *text* (see :func:`sha256_md_content`).

    Strips the ``sharepoint.sync`` block (and an empty ``sharepoint``
    parent) so a sync that only restamps the tool-managed metadata does
    not register as a user edit.  Falls back to the raw text bytes if
    the frontmatter is missing or unparseable — this is a hashing
    function, not a validator, so "garbage in, garbage hashed" is the
    correct behaviour.
    """
    split = split_frontmatter(text)
    if split is None:
        return text.encode("utf-8")
    fm_block, body = split

    mapping = parse_yaml_mapping(fm_block)
    if mapping is None:
        return text.encode("utf-8")

    fm_dict: dict[str, Any] = dict(mapping)
    sp_raw = fm_dict.get("sharepoint")
    if isinstance(sp_raw, dict):
        sp_mapping = cast("Mapping[str, Any]", sp_raw)
        sp_dict: dict[str, Any] = {k: v for k, v in sp_mapping.items() if k != "sync"}
        if sp_dict:
            fm_dict["sharepoint"] = sp_dict
        else:
            fm_dict.pop("sharepoint", None)

    if not fm_dict:
        return body.encode("utf-8")

    merged = yaml.safe_dump(fm_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{merged}---\n{body}".encode()


def _word_lock_path(office_path: Path) -> Path:
    """Return the Word lock-file path for *office_path*.

    Word writes ``~$Foo.docx`` next to ``Foo.docx``.
    """
    return office_path.parent / ("~$" + office_path.name)


def _read_text_safe(md_path: Path) -> str | None:
    """Return the file's text, or ``None`` if it is missing or unreadable."""
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _load_sharepoint_sync(md_path: Path) -> SharepointSync | None:
    """Return the parsed ``sharepoint.sync`` model from *md_path*, or ``None``.

    Returns ``None`` if the file is missing, unreadable, has no
    frontmatter, has frontmatter that does not contain a
    ``sharepoint.sync`` sub-block, or fails ``ValidationError`` on the
    typed model.  Validation failures are logged with the file path so
    typos like ``souce_path`` surface in the run log.
    """
    text = _read_text_safe(md_path)
    if text is None:
        return None

    split = split_frontmatter(text)
    if split is None:
        return None
    fm_block, _body = split

    mapping = parse_yaml_mapping(fm_block)
    if mapping is None:
        return None

    try:
        fm = SharepointFrontmatter.model_validate(mapping)
    except ValidationError as exc:
        log.warning("%s: invalid frontmatter: %s", md_path, exc)
        return None

    return None if fm.sharepoint is None else fm.sharepoint.sync


def read_sync_state(md_path: Path) -> SyncState:
    """Read the ``sharepoint.sync`` block from *md_path* and return a :class:`SyncState`.

    Returns :data:`_EMPTY_SYNC_STATE` if the file does not exist, does
    not contain a ``sharepoint.sync`` block, or the frontmatter fails
    validation (an unknown key inside ``sharepoint:`` — pydantic
    raises ``ValidationError`` and we fall through with a logged
    warning, matching today's silent-fallthrough behaviour while
    surfacing the typo in the log).
    """
    sync = _load_sharepoint_sync(md_path)
    if sync is None:
        return _EMPTY_SYNC_STATE
    return SyncState(
        office_sha256_at_sync=sync.office_sha256_at_sync,
        md_sha256_at_sync=sync.md_sha256_at_sync,
        last_sync=sync.last_sync,
        converter_version=sync.converter_version,
        update_office=sync.update_office,
    )


def classify_pair(
    docx_path: Path | None,
    md_path: Path | None,
    *,
    sync_state: SyncState,
) -> PairAction:
    """Classify a single office-markdown pair and return the :class:`PairAction`.

    Args:
        docx_path: Absolute path to the office file, or None if it does not exist.
        md_path: Absolute path to the ``.md`` file, or None if it does not exist.
        sync_state: The ``sharepoint.sync`` block previously read from the ``.md``
            frontmatter.  Pass :data:`_EMPTY_SYNC_STATE` if there is no prior sync.

    Returns:
        The :class:`PairAction` describing what the apply layer should do.

    The diff table (from spec S18):

    +---------------------+-------------------+----------------+----------------------+
    | office_now == sync  | md_now == sync    | update_office  | Verdict              |
    +=====================+===================+================+======================+
    | Yes                 | Yes               | any            | NO_OP                |
    +---------------------+-------------------+----------------+----------------------+
    | Yes                 | No                | True           | MD_TO_DOCX           |
    +---------------------+-------------------+----------------+----------------------+
    | Yes                 | No                | False          | SKIP_MD_UPDATE       |
    +---------------------+-------------------+----------------+----------------------+
    | No                  | Yes               | any            | DOCX_TO_MD           |
    +---------------------+-------------------+----------------+----------------------+
    | No                  | No                | True           | DIVERGED             |
    +---------------------+-------------------+----------------+----------------------+
    | No                  | No                | False          | SKIP_MD_UPDATE       |
    +---------------------+-------------------+----------------+----------------------+
    """
    # Determine which files exist
    docx_exists = docx_path is not None and docx_path.exists()
    md_exists = md_path is not None and md_path.exists()

    # --- Word lock check (takes priority over everything else) ---
    if docx_exists and docx_path is not None and _word_lock_path(docx_path).exists():
        return PairAction.WORD_LOCKED

    # --- Handle missing-file cases ---
    if not docx_exists and not md_exists:
        # Caller should not present this; treat as no-op
        return PairAction.NO_OP

    if not md_exists:
        # Only office file — first encounter
        return PairAction.FIRST_SYNC_DOCX_AUTHORITATIVE

    if not docx_exists:
        # Only .md file — first encounter
        return PairAction.FIRST_SYNC_MD_AUTHORITATIVE

    # Both files exist; check for sync block
    assert docx_path is not None  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction
    assert md_path is not None  # noqa: S101  # type-narrowing assert; invariant guaranteed by construction

    if sync_state.office_sha256_at_sync is None:
        # Both present but no prior sync record → docx wins (spec S18 rule)
        return PairAction.FIRST_SYNC_BOTH_DOCX_WINS

    return _classify_with_sync_block(docx_path, md_path, sync_state)


def _classify_with_sync_block(docx_path: Path, md_path: Path, sync_state: SyncState) -> PairAction:
    """Diff-table classification for the both-files-exist-with-sync-block case.

    Uses canonical-form hash for md so the tool's own sync-block restamp does
    not register as a user edit. md→office actions are gated on
    ``sync_state.update_office``.
    """
    office_unchanged = sha256_file(docx_path) == sync_state.office_sha256_at_sync
    md_unchanged = sha256_md_content(md_path) == sync_state.md_sha256_at_sync

    if office_unchanged and md_unchanged:
        return PairAction.NO_OP
    if md_unchanged:
        return PairAction.DOCX_TO_MD
    # md changed (alone or with office) — gated by update_office.
    if not sync_state.update_office:
        return PairAction.SKIP_MD_UPDATE
    if office_unchanged:
        return PairAction.MD_TO_DOCX
    return PairAction.DIVERGED
