"""Walk the mirror tree and build the current-state map."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mdd.confluence.models import ConfluenceAttachment, ConfluenceBlock, ConfluenceFrontmatter
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

log = get_logger(__name__)

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)

# Converter-output suffixes written under ``*-attachments/`` by the attachment
# sync pipeline (see ``confluence/attachments/sync_all.py``). Files with these
# composite extensions are mdd-managed conversion artefacts, not user-authored
# manual files.
_ATTACHMENT_CONVERTER_SUFFIXES: tuple[str, ...] = (".pdf.md", ".pptx.md", ".docx.md")


def _is_attachment_derived(path: Path) -> bool:
    """Return True if *path* is a converter output under a ``*-attachments/`` dir.

    The rule requires BOTH a ``*-attachments`` parent directory AND a converter
    suffix (``.pdf.md`` / ``.pptx.md`` / ``.docx.md``). A user-authored
    ``notes.pdf.md`` outside any ``*-attachments/`` parent stays ``manual``.
    """
    if not any(path.name.endswith(suffix) for suffix in _ATTACHMENT_CONVERTER_SUFFIXES):
        return False
    return any(parent.name.endswith("-attachments") for parent in path.parents)


class DuplicatePageIdError(Exception):
    """Raised when the same page_id appears in two .md files."""


@dataclass
class LocalPage:
    """Metadata about a .md file in the mirror tree."""

    path: Path
    page_id: str
    title: str
    parent_id: str | None
    status: str
    version_number: int
    space_key: str
    space_id: str
    attachments_manifest: list[dict[str, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    # Set to True when the page was exported with --no-attachments
    # so a subsequent sync without that flag can back-fill the attachments.
    attachments_skipped: bool = False


@dataclass
class MirrorState:
    """Outcome of a mirror-tree walk."""

    # page_id → LocalPage for files with valid frontmatter and page_id
    tracked: dict[str, LocalPage] = field(default_factory=dict)
    # files without page_id but with recognizable publish-candidate shape
    untracked: list[Path] = field(default_factory=list)
    # files that are manually managed (no valid frontmatter or page_id, non-publishable)
    manual: list[Path] = field(default_factory=list)
    # converter outputs under ``*-attachments/`` (e.g. ``Foo-attachments/bar.pdf.md``)
    # — mdd-managed conversion artefacts that should not be flagged as drift
    attachment_derived: list[Path] = field(default_factory=list)


def _read_frontmatter(path: Path) -> tuple[ConfluenceFrontmatter, str] | None:
    """Return (frontmatter, body) from a file, or None if the file is not parseable.

    Returns ``None`` on read error, missing frontmatter fence,
    non-mapping YAML, or a :class:`ValidationError` (an unknown key
    in the ``confluence:`` block, etc.).  Validation failures are
    logged with the file path; callers treat the file as
    ``state.manual`` to mirror today's silent-fallback behaviour
    while still surfacing the problem in the log.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    split = split_frontmatter(text)
    if split is None:
        return None
    yaml_block, body = split

    mapping = parse_yaml_mapping(yaml_block)
    if mapping is None:
        return None

    try:
        fm = ConfluenceFrontmatter.model_validate(mapping)
    except ValidationError as exc:
        log.warning("%s: invalid frontmatter: %s", path, exc)
        return None
    return fm, body


def _derive_title(body: str, path: Path) -> str:
    """Extract the first ATX H1 from *body*, or fall back to filename stem."""
    m = _H1_RE.search(body)
    return m.group(1).strip() if m else path.stem


def _is_publish_candidate(conf: ConfluenceBlock | None) -> bool:
    """Return True if this file looks like a local-authored publish candidate.

    Criteria: has a ``confluence`` block with at least ``space_key``.
    Title is always derivable (first H1 or filename stem), so we don't check it.
    No ``page_id`` — that is checked before calling this function.
    """
    return conf is not None and bool(conf.space_key)


def _attachment_manifest(conf: ConfluenceBlock) -> list[dict[str, Any]]:
    """Render the typed attachments back into the dict shape downstream code expects."""
    if not conf.attachments:
        return []
    return [_dump_attachment(a) for a in conf.attachments]


def _dump_attachment(a: ConfluenceAttachment) -> dict[str, Any]:
    """Serialize an attachment back to a dict, omitting defaulted-empty fields."""
    return {k: v for k, v in a.model_dump().items() if v not in ("", 0)}


def _local_page_from_conf(md_path: Path, body: str, conf: ConfluenceBlock) -> LocalPage:
    """Build a :class:`LocalPage` from a parsed ``confluence:`` block.

    Caller has already validated that ``conf.page_id`` is a non-empty
    string and resolved duplicates.
    """
    page_id = conf.page_id or ""
    return LocalPage(
        path=md_path,
        page_id=page_id,
        title=_derive_title(body, md_path),
        parent_id=conf.parent_id or None,
        status=(conf.status or "CURRENT").upper(),
        version_number=conf.version,
        space_key=conf.space_key,
        space_id=conf.space_id,
        attachments_manifest=_attachment_manifest(conf),
        labels=list(conf.labels),
        attachments_skipped=conf.attachments_skipped,
    )


def _ingest_md_path(state: MirrorState, md_path: Path) -> None:
    """Read *md_path*, classify it, and slot it into *state*.

    Mutates *state* with one append (or one tracked-dict insert).  Raises
    :class:`DuplicatePageIdError` when a page_id collides with one already in
    ``state.tracked``.
    """
    fm_result = _read_frontmatter(md_path)
    if fm_result is None:
        state.manual.append(md_path)
        return

    fm, body = fm_result
    conf = fm.confluence
    if conf is None:
        state.manual.append(md_path)
        return

    if not conf.page_id:
        # No page_id: publish candidate vs plain manual file.
        bucket = state.untracked if _is_publish_candidate(conf) else state.manual
        bucket.append(md_path)
        return

    page_id = conf.page_id
    if page_id in state.tracked:
        existing = state.tracked[page_id]
        raise DuplicatePageIdError(
            f"page_id {page_id!r} appears in two files:\n"
            f"  {existing.path}\n"
            f"  {md_path}\n"
            "Remove or fix one before running sync."
        )
    state.tracked[page_id] = _local_page_from_conf(md_path, body, conf)


def build_mirror_state(output_dir: Path) -> MirrorState:
    """Walk *output_dir* and build the current state of the mirror.

    Raises:
        DuplicatePageIdError: If the same ``confluence.page_id`` appears in two
            different ``.md`` files.

    Returns:
        :class:`MirrorState` with ``tracked``, ``untracked``, ``manual``, and
        ``attachment_derived`` lists.
    """
    state = MirrorState()
    for md_path in sorted(output_dir.rglob("*.md")):
        _ingest_md_path(state, md_path)
    _split_attachment_derived(state)
    return state


def _split_attachment_derived(state: MirrorState) -> None:
    """Move converter outputs out of ``manual`` into ``attachment_derived``.

    Run after the main walk so it stays a single linear pass that does not add
    cognitive complexity to ``build_mirror_state`` itself.
    """
    keep: list[Path] = []
    derived: list[Path] = []
    for path in state.manual:
        (derived if _is_attachment_derived(path) else keep).append(path)
    state.manual = keep
    state.attachment_derived = derived
