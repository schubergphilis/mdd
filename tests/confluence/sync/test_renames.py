"""Single-event entry points to the bulk rename/archive handlers.

The mutate orchestrators (``mdd.confluence.mutate``) drive the per-page
refresh by calling the existing bulk handlers with a one-element list of
:class:`SyncEvent`.  These tests pin that contract so a future refactor of
``apply_renames_moves`` / ``apply_archive_unarchive`` cannot regress the
single-page case.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
import yaml

from mdd.confluence.state import LocalPage

if TYPE_CHECKING:
    from pathlib import Path
from mdd.confluence.sync._types import SyncSummary
from mdd.confluence.sync.renames import apply_archive_unarchive, apply_renames_moves
from mdd.confluence.sync_diff import DesiredPage, EventKind, SyncEvent


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def _git_add_and_commit(path: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(path), check=True, capture_output=True
    )


def _write_md(path: Path, *, title: str, status: str = "CURRENT") -> None:
    fm = {
        "confluence": {
            "page_id": "12345",
            "space_key": "ENG",
            "space_id": "98306",
            "title": title,
            "status": status,
            "version": 1,
            "exported_at": "2026-01-01T00:00:00+00:00",
        }
    }
    body = f"# {title}\n\nbody\n"
    fm_str = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False)
    path.write_text(f"---\n{fm_str}---\n{body}", encoding="utf-8")


class _FakeMirror:
    """Minimal :class:`MirrorState` stand-in for the per-event handlers."""

    def __init__(self, tracked: dict[str, LocalPage]) -> None:
        self.tracked = tracked


def _make_local_page(path: Path, *, title: str, status: str = "CURRENT") -> LocalPage:
    return LocalPage(
        path=path,
        page_id="12345",
        title=title,
        parent_id=None,
        status=status,
        version_number=1,
        space_key="ENG",
        space_id="98306",
    )


def _make_desired(*, title: str, status: str = "current") -> DesiredPage:
    return DesiredPage(
        page_id="12345",
        title=title,
        parent_id=None,
        status=status,
        version_number=2,
        version_created_at="2026-05-01T00:00:00Z",
        space_id="98306",
    )


def test_apply_renames_moves_drives_single_event(tmp_path: Path) -> None:
    """``apply_renames_moves([event], ...)`` renames one page end-to-end."""
    _init_git_repo(tmp_path)
    old_path = tmp_path / "Old-Title.md"
    _write_md(old_path, title="Old Title")
    _git_add_and_commit(tmp_path)

    mirror = _FakeMirror({"12345": _make_local_page(old_path, title="Old Title")})
    summary = SyncSummary()
    event = SyncEvent(
        kind=EventKind.RENAME,
        page_id="12345",
        desired=_make_desired(title="New Title"),
        current_path=str(old_path),
    )

    apply_renames_moves(
        [event],
        mirror,
        tmp_path,
        page_to_outdir={},
        used_paths=set(),
        summary=summary,
    )

    new_path = tmp_path / "New Title.md"
    assert summary.renamed == 1
    assert summary.failures == []
    assert mirror.tracked["12345"].path == new_path
    # The body H1 must reflect the new title — `_extract_title` reads
    # the first ATX H1, so leaving it stale would resurrect the old
    # title on the next `update-page`.
    assert "# New Title\n" in new_path.read_text(encoding="utf-8")
    assert "# Old Title" not in new_path.read_text(encoding="utf-8")


def test_apply_archive_unarchive_drives_single_event(tmp_path: Path) -> None:
    """``apply_archive_unarchive([event], ...)`` flips a single page's status."""
    _init_git_repo(tmp_path)
    md_path = tmp_path / "Page.md"
    _write_md(md_path, title="Page", status="CURRENT")
    _git_add_and_commit(tmp_path)

    mirror = _FakeMirror({"12345": _make_local_page(md_path, title="Page")})
    summary = SyncSummary()
    event = SyncEvent(
        kind=EventKind.ARCHIVE,
        page_id="12345",
        desired=_make_desired(title="Page", status="archived"),
        current_path=str(md_path),
    )

    apply_archive_unarchive([event], mirror, summary)

    assert summary.archived == 1
    assert summary.failures == []
    parsed: object = yaml.safe_load(md_path.read_text().split("---")[1])
    assert isinstance(parsed, dict)
    conf_raw: object = parsed.get("confluence")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert isinstance(conf_raw, dict)
    # Status is lowercase end-to-end on disk.
    assert conf_raw.get("status") == "archived"  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize("kind", [EventKind.ARCHIVE, EventKind.UNARCHIVE])
def test_apply_archive_unarchive_ignores_other_kinds(kind: EventKind, tmp_path: Path) -> None:
    """Sanity check: handler accepts both ARCHIVE and UNARCHIVE in a single-element list."""
    _init_git_repo(tmp_path)
    md_path = tmp_path / "P.md"
    initial_status = "CURRENT" if kind == EventKind.ARCHIVE else "ARCHIVED"
    _write_md(md_path, title="P", status=initial_status)
    _git_add_and_commit(tmp_path)
    mirror = _FakeMirror({"12345": _make_local_page(md_path, title="P", status=initial_status)})
    summary = SyncSummary()
    desired_status = "archived" if kind == EventKind.ARCHIVE else "current"
    event = SyncEvent(
        kind=kind,
        page_id="12345",
        desired=_make_desired(title="P", status=desired_status),
        current_path=str(md_path),
    )
    apply_archive_unarchive([event], mirror, summary)
    assert summary.failures == []
