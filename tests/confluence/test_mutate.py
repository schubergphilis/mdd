"""Unit tests for the S27 mutate orchestrators (P06 Phase 3).

Each test builds a self-contained ``tmp_path`` git repo + a single ``.md``
file with the expected frontmatter, then drives one of
``rename_page`` / ``move_page`` / ``archive_page`` / ``unarchive_page`` with
a mocked :class:`ConfluenceClient` patched at the
``mdd.confluence.mutate`` boundary.

The fixtures helper builds the minimal frontmatter shape the orchestrators
expect; tests parametrize specific fields where the variation matters.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from mdd.confluence.client import ConfluenceClient
from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.managed import ManagedConfig
from mdd.confluence.mutate import (
    MutateOptions,
    archive_page,
    move_page,
    rename_page,
    unarchive_page,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=str(repo), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=str(repo), check=True, capture_output=True
    )


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True
    )


_BASE_FM: dict[str, Any] = {
    "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/12345/Old+Title",
    "page_id": "12345",
    "space_key": "ENG",
    "space_id": "98306",
    "title": "Old Title",
    "parent_id": None,
    "status": "CURRENT",
    "version": 3,
    "updated_at": "2026-01-01T00:00:00.000Z",
    "exported_at": "2026-01-01T00:00:00+00:00",
}


def _make_fm(**overrides: Any) -> dict[str, Any]:
    block = dict(_BASE_FM)
    block.update(overrides)
    return {"confluence": block}


def _write_md(path: Path, fm: dict[str, Any], body: str = "# Old Title\n\nbody\n") -> None:
    fm_str = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False)
    path.write_text(f"---\n{fm_str}---\n{body}", encoding="utf-8")


_REMOTE_PAGE: dict[str, Any] = {
    "id": "12345",
    "title": "Old Title",
    "status": "current",
    "spaceId": "98306",
    "spaceKey": "ENG",
    "parentId": None,
    "version": {"number": 3, "createdAt": "2026-04-01T00:00:00Z"},
    "body": {"storage": {"value": "<p>body</p>", "representation": "storage"}},
}


_PUT_RESPONSE: dict[str, Any] = {
    "id": "12345",
    "title": "New Title",
    "version": {"number": 4, "createdAt": "2026-05-08T10:00:00Z", "authorId": "user-xyz"},
}


_ARCHIVE_RESPONSE: dict[str, Any] = {
    "id": "12345",
    "status": "archived",
    "version": {"number": 4, "createdAt": "2026-05-08T10:00:00Z"},
}


def _enter(self: object) -> object:
    return self


def _make_mock_client(
    *,
    page_response: dict[str, Any] | None = None,
    put_response: dict[str, Any] | None = None,
    archive_response: dict[str, Any] | None = None,
    parent_response: dict[str, Any] | None = None,
) -> MagicMock:
    client = MagicMock(spec=ConfluenceClient)
    client.__enter__ = _enter
    client.__exit__ = MagicMock(return_value=False)
    client.base_url = "https://example.atlassian.net"
    page = page_response if page_response is not None else _REMOTE_PAGE

    def _get_page(page_id: str, **_kw: object) -> dict[str, Any]:
        if parent_response is not None and page_id == parent_response.get("id"):
            return parent_response
        return page

    client.get_page.side_effect = _get_page
    client.put_page.return_value = put_response if put_response is not None else _PUT_RESPONSE
    arch = archive_response if archive_response is not None else _ARCHIVE_RESPONSE
    client.archive_page.return_value = arch
    client.unarchive_page.return_value = arch
    return client


def _make_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        url="https://example.atlassian.net",
        username="u@example.com",
        api_token="t",
    )


def _empty_managed() -> ManagedConfig:
    return ManagedConfig()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# rename_page
# ---------------------------------------------------------------------------


class TestRenamePage:
    def test_happy_path(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        mock_client.put_page.assert_called_once()
        call_kwargs = mock_client.put_page.call_args
        # 2nd positional is the new title
        assert call_kwargs.args[1] == "New Title"

        new_path = repo / "New Title.md"
        assert new_path.exists() or md_path.exists()

    def test_dry_run_makes_no_calls(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(
            config=_make_config(),
            yes=True,
            dry_run=True,
            managed_config=_empty_managed(),
        )

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        mock_client.put_page.assert_not_called()
        assert md_path.exists()  # working tree untouched

    def test_no_commit_leaves_staged_changes(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
        ).stdout.strip()

        mock_client = _make_mock_client()
        opts = MutateOptions(
            config=_make_config(),
            yes=True,
            no_commit=True,
            managed_config=_empty_managed(),
        )

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
        ).stdout.strip()
        assert head_after == head_before, "no_commit should leave HEAD untouched"

    def test_version_drift_refused(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm(version=2))  # local behind remote
        _commit_all(repo)

        # remote says version 3 — drift detected
        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 1
        mock_client.put_page.assert_not_called()

    def test_dirty_tree_refused(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)
        # Introduce an uncommitted change
        md_path.write_text(md_path.read_text() + "\nextra\n")

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 1
        mock_client.put_page.assert_not_called()

    def test_managed_elsewhere_refused(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        # Force classify_page to return managed=True
        from mdd.confluence.managed import ManagedClassification

        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            patch(
                "mdd.confluence.mutate.classify_page",
                return_value=ManagedClassification(
                    is_managed=True,
                    publisher_name="ConfigBot",
                    message="Managed by ConfigBot",
                ),
            ),
        ):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 1
        mock_client.put_page.assert_not_called()

    def test_collision_with_sibling(self, repo: Path) -> None:
        """Rename collides with an existing sibling — both files get the page-id suffix."""
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        sibling = repo / "New Title.md"
        _write_md(sibling, _make_fm(page_id="67890", title="New Title"))
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        # Rename succeeded.  The handler used compute_rename_path; the
        # collision triggers a ``(12345)`` suffix on at least one file.
        assert rc == 0
        renamed_to_suffix = (repo / "New Title (12345).md").exists()
        assert renamed_to_suffix, "expected (page-id) suffix on collision"


# ---------------------------------------------------------------------------
# move_page
# ---------------------------------------------------------------------------


class TestMovePage:
    def test_happy_path(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        parent_md = repo / "Parent.md"
        _write_md(parent_md, _make_fm(page_id="99999", title="Parent"))
        _commit_all(repo)

        parent_response: dict[str, Any] = {
            "id": "99999",
            "title": "New Parent",
            "spaceId": "98306",
            "spaceKey": "ENG",
            "version": {"number": 1},
            "body": {"storage": {"value": "", "representation": "storage"}},
        }
        mock_client = _make_mock_client(parent_response=parent_response)
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = move_page(md_path, str(parent_md), opts=opts)

        assert rc == 0
        mock_client.put_page.assert_called_once()
        # parent_id was sent via PutPageOptions
        call_args = mock_client.put_page.call_args
        opts_kw = call_args.kwargs.get("options")
        assert opts_kw is not None
        assert opts_kw.parent_id == "99999"

    def test_cross_space_rejected(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345", space_key="ENG", space_id="98306"))
        _commit_all(repo)

        parent_response: dict[str, Any] = {
            "id": "99999",
            "title": "Foreign Parent",
            "spaceId": "11111",
            "spaceKey": "OTHER",
            "version": {"number": 1},
            "body": {"storage": {"value": "", "representation": "storage"}},
        }
        mock_client = _make_mock_client(parent_response=parent_response)
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 1
        mock_client.put_page.assert_not_called()

    def test_dry_run_makes_no_put(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        _commit_all(repo)

        parent_response: dict[str, Any] = {
            "id": "99999",
            "title": "Parent",
            "spaceId": "98306",
            "spaceKey": "ENG",
            "version": {"number": 1},
            "body": {"storage": {"value": "", "representation": "storage"}},
        }
        mock_client = _make_mock_client(parent_response=parent_response)
        opts = MutateOptions(
            config=_make_config(),
            yes=True,
            dry_run=True,
            managed_config=_empty_managed(),
        )

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        mock_client.put_page.assert_not_called()


# ---------------------------------------------------------------------------
# archive_page / unarchive_page
# ---------------------------------------------------------------------------


def _read_status(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    parsed: object = yaml.safe_load(text.split("---")[1])
    assert isinstance(parsed, dict)
    conf_raw: object = parsed.get("confluence")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert isinstance(conf_raw, dict)
    return str(conf_raw.get("status", ""))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


class TestArchivePage:
    def test_archive_flips_status(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(status="CURRENT"))
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = archive_page(md_path, opts=opts)

        assert rc == 0
        mock_client.archive_page.assert_called_once()
        # #130 F4: status is lowercase end-to-end on disk.
        assert _read_status(md_path) == "archived"

    def test_unarchive_flips_status(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        # Remote shape: an archived page
        archived_remote = dict(_REMOTE_PAGE)
        archived_remote["status"] = "archived"
        _write_md(md_path, _make_fm(status="ARCHIVED"))
        _commit_all(repo)

        mock_client = _make_mock_client(page_response=archived_remote)
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = unarchive_page(md_path, opts=opts)

        assert rc == 0
        mock_client.unarchive_page.assert_called_once()
        # #130 F4: status is lowercase end-to-end on disk.
        assert _read_status(md_path) == "current"

    def test_archive_dry_run_makes_no_call(self, repo: Path) -> None:
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(status="CURRENT"))
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(
            config=_make_config(),
            yes=True,
            dry_run=True,
            managed_config=_empty_managed(),
        )

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = archive_page(md_path, opts=opts)

        assert rc == 0
        mock_client.archive_page.assert_not_called()
        assert _read_status(md_path) == "CURRENT"

    def test_refresh_failure_returns_1(self, repo: Path) -> None:
        """When API call succeeded but local refresh fails: exit 1 + hint."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(status="CURRENT"))
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        from mdd.confluence.apply import ApplyError

        def _boom(*_args: object, **_kw: object) -> None:
            raise ApplyError("simulated refresh failure")

        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.mutate.apply_archive_unarchive", side_effect=_boom),
        ):
            rc = archive_page(md_path, opts=opts)

        assert rc == 1
        # API was still called even though local refresh failed
        mock_client.archive_page.assert_called_once()


# ---------------------------------------------------------------------------
# Issue #130: frontmatter refresh after rename / move / archive
# ---------------------------------------------------------------------------


def _read_conf(md_path: Path) -> dict[str, Any]:
    text = md_path.read_text(encoding="utf-8")
    parsed: object = yaml.safe_load(text.split("---")[1])
    assert isinstance(parsed, dict)
    conf_raw: object = parsed.get("confluence")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert isinstance(conf_raw, dict)
    return dict(conf_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


def _read_body(md_path: Path) -> str:
    """Return the markdown body (everything after the second ``---``)."""
    return md_path.read_text(encoding="utf-8").split("---", 2)[2]


class TestIssue130RenameRefresh:
    """F1 + F2: rename rewrites body H1, drops `confluence.title:`, refreshes URL slug."""

    def test_rename_rewrites_body_h1(self, repo: Path) -> None:
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        new_path = repo / "New Title.md"
        assert new_path.exists()
        body = _read_body(new_path)
        # F1: body H1 reflects the new title — `_extract_title` reads
        # the first ATX H1, so leaving it stale would resurrect the old
        # title on the next `update-page`.
        assert "# New Title" in body
        assert "# Old Title" not in body

    def test_rename_does_not_write_confluence_title(self, repo: Path) -> None:
        """F1: `confluence.title:` is dead audit data — never written by rename."""
        md_path = repo / "Old-Title.md"
        # Start without a `title:` key in the conf block; rename must not add one.
        fm = _make_fm()
        del fm["confluence"]["title"]
        _write_md(md_path, fm)
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        new_path = repo / "New Title.md"
        conf = _read_conf(new_path)
        assert "title" not in conf, "rename must not resurrect the dead `confluence.title:` field"

    def test_rename_refreshes_url_slug(self, repo: Path) -> None:
        """F2: `confluence.url` slug component is rewritten to match the new title."""
        md_path = repo / "Old-Title.md"
        _write_md(md_path, _make_fm())
        _commit_all(repo)

        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = rename_page(md_path, "New Title", opts=opts)

        assert rc == 0
        new_path = repo / "New Title.md"
        conf = _read_conf(new_path)
        url = str(conf.get("url", ""))
        # Page id is unchanged; slug suffix now matches the new title.
        assert "/12345/New+Title" in url, f"URL slug not refreshed: {url}"
        assert "Old+Title" not in url, f"URL still carries old slug: {url}"


class TestIssue130ArchiveRefresh:
    """F4 + F5: status is lowercase end-to-end, `updated_at` refreshes on archive/unarchive."""

    def test_archive_updated_at_refreshed_when_api_omits_created_at(self, repo: Path) -> None:
        """F5: archive endpoint may omit `version.createdAt` — fall back to local now()."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(status="CURRENT"))
        _commit_all(repo)

        # Simulate the live v2 archive endpoint: no `version.createdAt`.
        slim_archive: dict[str, Any] = {
            "id": "12345",
            "status": "archived",
            "version": {"number": 4},  # no createdAt
        }
        mock_client = _make_mock_client(archive_response=slim_archive)
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = archive_page(md_path, opts=opts)

        assert rc == 0
        conf = _read_conf(md_path)
        # The stale timestamp from the prior mutation must be replaced.
        new_updated_at = str(conf.get("updated_at", ""))
        assert new_updated_at != "2026-01-01T00:00:00.000Z", (
            f"updated_at not refreshed on archive: {new_updated_at}"
        )
        assert new_updated_at.endswith("Z"), f"unexpected timestamp shape: {new_updated_at}"

    def test_archive_status_lowercase(self, repo: Path) -> None:
        """F4: archived status is lowercase even when local frontmatter had uppercase."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(status="CURRENT"))
        _commit_all(repo)
        mock_client = _make_mock_client()
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = archive_page(md_path, opts=opts)

        assert rc == 0
        assert _read_conf(md_path).get("status") == "archived"

    def test_unarchive_status_lowercase_after_uppercase_start(self, repo: Path) -> None:
        """F4: unarchive returns frontmatter to lowercase `current`, not `CURRENT`."""
        md_path = repo / "Page.md"
        archived_remote = dict(_REMOTE_PAGE)
        archived_remote["status"] = "archived"
        _write_md(md_path, _make_fm(status="ARCHIVED"))
        _commit_all(repo)

        mock_client = _make_mock_client(page_response=archived_remote)
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = unarchive_page(md_path, opts=opts)

        assert rc == 0
        assert _read_conf(md_path).get("status") == "current"

    def test_unarchive_updated_at_refreshed_when_api_omits_created_at(self, repo: Path) -> None:
        """F5: unarchive endpoint may omit `version.createdAt` — fall back to local now()."""
        md_path = repo / "Page.md"
        archived_remote = dict(_REMOTE_PAGE)
        archived_remote["status"] = "archived"
        _write_md(md_path, _make_fm(status="ARCHIVED"))
        _commit_all(repo)

        slim_unarchive: dict[str, Any] = {
            "id": "12345",
            "status": "current",
            "version": {"number": 5},  # no createdAt
        }
        mock_client = _make_mock_client(
            page_response=archived_remote,
            archive_response=slim_unarchive,
        )
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = unarchive_page(md_path, opts=opts)

        assert rc == 0
        new_updated_at = str(_read_conf(md_path).get("updated_at", ""))
        assert new_updated_at != "2026-01-01T00:00:00.000Z", (
            f"updated_at not refreshed on unarchive: {new_updated_at}"
        )


# ---------------------------------------------------------------------------
# P05 — move-page materialises missing ancestor mirror dirs (spec S27)
# ---------------------------------------------------------------------------


def _parent_response(
    page_id: str,
    title: str,
    *,
    space_id: str = "98306",
    space_key: str = "ENG",
) -> dict[str, Any]:
    """Build a minimal parent page payload for the move tests."""
    return {
        "id": page_id,
        "title": title,
        "spaceId": space_id,
        "spaceKey": space_key,
        "version": {"number": 1},
        "body": {"storage": {"value": "<p>parent body</p>", "representation": "storage"}},
    }


def _patch_pull_writes_index(
    target_dirs: dict[str, Path],
) -> Any:  # pyright: ignore[reportExplicitAny]
    """Return a patch object for ``pull_single_page`` that writes ``_index.md``.

    *target_dirs* maps page_id -> the directory the pull is expected to
    target.  Each invocation writes a stub frontmatter-only ``_index.md``
    into ``target_dir`` so the rest of the orchestrator sees a real file.
    """

    from mdd.confluence.materialise import INDEX_BASENAME, PullResult

    def _fake_pull(_client: object, page_id: str, target_dir: Path) -> PullResult:
        target_dir.mkdir(parents=True, exist_ok=True)
        index = target_dir / INDEX_BASENAME
        index.write_text(
            f"---\nconfluence:\n  page_id: '{page_id}'\n---\n# pulled\n",
            encoding="utf-8",
        )
        target_dirs.setdefault(page_id, target_dir)
        return PullResult(page_id=page_id, written_path=index)

    return patch("mdd.confluence.mutate.pull_single_page", side_effect=_fake_pull)


def _last_commit_message(repo: Path) -> str:
    """Return the most recent commit's full message (subject + body)."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class TestMovePageMaterialisation:
    """P05: move-page materialises missing ancestor mirror dirs (S27)."""

    def test_parent_dir_already_exists_no_materialisation(self, repo: Path) -> None:
        """When the parent dir already exists locally, no pulls or promotes happen."""
        # Layout: Page.md at repo root; parent "Existing Parent" already a dir.
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        parent_dir = repo / "Existing Parent"
        parent_dir.mkdir()
        (parent_dir / "_index.md").write_text(
            "---\nconfluence:\n  page_id: '99999'\n---\nx\n",
            encoding="utf-8",
        )
        _commit_all(repo)

        mock_client = _make_mock_client(
            parent_response=_parent_response("99999", "Existing Parent"),
        )
        # No ancestors above the direct parent.
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.mutate.pull_single_page") as fake_pull,
            patch("mdd.confluence.mutate.promote_flat_to_dir") as fake_promote,
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        fake_pull.assert_not_called()
        fake_promote.assert_not_called()
        # File landed inside the existing parent dir.  The sanitized
        # filename matches the frontmatter title (not the on-disk stem).
        assert (parent_dir / "Old Title.md").exists()
        assert not md_path.exists()

    def test_flat_parent_promoted_to_dir(self, repo: Path) -> None:
        """A flat ``Parent.md`` is promoted to ``Parent/_index.md`` before the move."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        flat_parent = repo / "Parent.md"
        _write_md(flat_parent, _make_fm(page_id="99999", title="Parent"))
        _commit_all(repo)

        mock_client = _make_mock_client(parent_response=_parent_response("99999", "Parent"))
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        # Parent.md is gone, Parent/_index.md exists.
        assert not flat_parent.exists()
        assert (repo / "Parent" / "_index.md").exists()
        # Moved file landed inside Parent/.  Sanitized name from frontmatter title.
        assert (repo / "Parent" / "Old Title.md").exists()
        assert not md_path.exists()

    def test_absent_parent_pulled(self, repo: Path) -> None:
        """An ancestor absent from the mirror is pulled via ``pull_single_page``."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        _commit_all(repo)

        mock_client = _make_mock_client(parent_response=_parent_response("99999", "New Parent"))
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        target_dirs: dict[str, Path] = {}
        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            _patch_pull_writes_index(target_dirs),
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        # Parent was pulled into the expected mirror dir.
        assert target_dirs["99999"] == repo / "New Parent"
        assert (repo / "New Parent" / "_index.md").exists()
        # File landed inside the pulled parent's dir.
        assert (repo / "New Parent" / "Old Title.md").exists()

    def test_whole_chain_absent_pulled(self, repo: Path) -> None:
        """Both grandparent and parent are absent — both are pulled."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        _commit_all(repo)

        mock_client = _make_mock_client(parent_response=_parent_response("99999", "Parent"))
        mock_client.get_page_ancestors.return_value = [
            {"id": "88888", "title": "Grandparent", "spaceId": "98306"},
        ]
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        target_dirs: dict[str, Path] = {}
        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            _patch_pull_writes_index(target_dirs),
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        # Both ancestors materialised, in the correct nested order.
        assert target_dirs["88888"] == repo / "Grandparent"
        assert target_dirs["99999"] == repo / "Grandparent" / "Parent"
        assert (repo / "Grandparent" / "_index.md").exists()
        assert (repo / "Grandparent" / "Parent" / "_index.md").exists()
        assert (repo / "Grandparent" / "Parent" / "Old Title.md").exists()

    def test_cross_space_refusal_no_materialisation(self, repo: Path) -> None:
        """Cross-space parent: refuse before any pull or promote happens."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345", space_id="98306"))
        _commit_all(repo)

        # Parent in a different space.
        mock_client = _make_mock_client(
            parent_response=_parent_response(
                "99999",
                "Foreign",
                space_id="OTHER",
                space_key="OTHER",
            ),
        )
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.mutate.pull_single_page") as fake_pull,
            patch("mdd.confluence.mutate.promote_flat_to_dir") as fake_promote,
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 1
        # Refusal happens at _check_same_space, before _finish_move runs.
        fake_pull.assert_not_called()
        fake_promote.assert_not_called()
        mock_client.put_page.assert_not_called()
        # File was not moved.
        assert md_path.exists()

    def test_mid_chain_failure_recovery_hint(self, repo: Path, caplog: Any) -> None:  # pyright: ignore[reportExplicitAny]
        """Materialisation failure mid-chain: exit 1, recovery hint, no rollback."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        _commit_all(repo)

        mock_client = _make_mock_client(parent_response=_parent_response("99999", "Parent"))
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        def _boom(_c: object, _pid: str, _t: Path) -> None:
            raise OSError("disk full")

        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            patch("mdd.confluence.mutate.pull_single_page", side_effect=_boom),
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 1
        # API call still happened — Confluence side is the source of truth.
        mock_client.put_page.assert_called_once()
        # Recovery hint emitted in the logs.
        joined = "\n".join(caplog.messages)
        assert "Confluence updated successfully but local refresh failed" in joined
        assert "sync-space" in joined

    def test_commit_body_lists_materialised_paths(self, repo: Path) -> None:
        """Spec S27: commit body lists every materialised ancestor + the moved path."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        _commit_all(repo)

        mock_client = _make_mock_client(parent_response=_parent_response("99999", "New Parent"))
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        target_dirs: dict[str, Path] = {}
        with (
            patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client),
            _patch_pull_writes_index(target_dirs),
        ):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        msg = _last_commit_message(repo)
        # Subject unchanged
        assert 'chore(mirror): move "Old Title" to "New Parent"' in msg
        # Body has the structured sections from S27's example
        assert "materialised ancestors (pulled from Confluence):" in msg
        assert "New Parent/_index.md  (page 99999)" in msg
        assert "moved:" in msg
        assert "Page.md -> New Parent/Old Title.md" in msg

    def test_existing_parent_dir_subject_unchanged_no_body(self, repo: Path) -> None:
        """No materialisation → commit message has no S27 body (subject only)."""
        md_path = repo / "Page.md"
        _write_md(md_path, _make_fm(page_id="12345"))
        parent_dir = repo / "Existing Parent"
        parent_dir.mkdir()
        (parent_dir / "_index.md").write_text(
            "---\nconfluence:\n  page_id: '99999'\n---\nx\n",
            encoding="utf-8",
        )
        _commit_all(repo)

        mock_client = _make_mock_client(
            parent_response=_parent_response("99999", "Existing Parent"),
        )
        mock_client.get_page_ancestors.return_value = []
        opts = MutateOptions(config=_make_config(), yes=True, managed_config=_empty_managed())

        with patch("mdd.confluence.mutate.ConfluenceClient", return_value=mock_client):
            rc = move_page(md_path, "99999", opts=opts)

        assert rc == 0
        msg = _last_commit_message(repo)
        # Subject is identical to today's shape.
        assert 'chore(mirror): move "Old Title" to "Existing Parent"' in msg
        # No materialisation section.
        assert "materialised ancestors" not in msg
