"""The confidentiality blacklist gate on the Confluence sync and export paths.

The gate fires at the entry point, before anything is fetched or written, so a
blacklisted space aborts the whole run rather than being caught per page. These
tests cover the wiring; the matching rules themselves live in
``tests/utils/test_blacklist.py``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.attachments import AttachmentSyncSummary
from mdd.confluence.config import ConfluenceConfig
from mdd.confluence.export import export_page
from mdd.confluence.sync import SyncOptions, sync_space
from mdd.utils.blacklist import BlacklistConfigError, BlacklistError

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# discovery isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_blacklist_discovery(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the checked-out and per-user blacklists out of these tests.

    ``find_blacklist_files`` is additive, so without this the real
    ``configs/data-protection.yaml`` unions in and the "no config at all"
    assertions cannot be made.
    """
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: None)
    monkeypatch.setattr("mdd.utils.config.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def blacklist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a discoverable blacklist that protects ``PRIVATE`` and ``Legal*``."""
    f = tmp_path / "data-protection.yaml"
    f.write_text(
        textwrap.dedent(
            """\
            confluence:
              blacklisted_spaces:
                - PRIVATE
                - "Legal*"
            sharepoint:
              blacklisted_sites: []
            """
        )
    )
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: f)
    return f


@pytest.fixture
def empty_blacklist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install a discoverable blacklist that protects nothing."""
    f = tmp_path / "data-protection.yaml"
    f.write_text("confluence:\n  blacklisted_spaces: []\nsharepoint:\n  blacklisted_sites: []\n")
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: f)
    return f


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _page_data(space_key: str = "ENG") -> dict[str, Any]:
    return {
        "id": "42",
        "title": "Sample",
        "status": "current",
        "spaceId": "s1",
        "spaceKey": space_key,
        "parentId": None,
        "body": {"storage": {"value": "<p>Hello.</p>"}},
        "_links": {"webui": f"/wiki/spaces/{space_key}/pages/42/Sample"},
        "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
    }


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.base_url = "https://example.atlassian.net"
    client.get_user.return_value = {"displayName": "Bot"}
    return client


def _config() -> ConfluenceConfig:
    return ConfluenceConfig(url="https://example.atlassian.net", username="test", api_token="token")


@pytest.fixture
def no_attachment_sync() -> Iterator[None]:
    """Stub the attachment sync so exports do no network work."""
    with patch(
        "mdd.confluence.export.sync_all_attachments",
        return_value=([], AttachmentSyncSummary()),
    ):
        yield


# ---------------------------------------------------------------------------
# sync_space
# ---------------------------------------------------------------------------


class TestSyncSpaceGate:
    def test_blacklisted_space_aborts_before_any_fetch(self, blacklist: Path) -> None:
        client = _fake_client()
        output_dir = Path("mirror")
        with pytest.raises(BlacklistError, match="PRIVATE"):
            sync_space(client, "PRIVATE", output_dir, _config())
        # Nothing was fetched and the mirror directory was never created.
        assert client.method_calls == []
        assert not output_dir.exists()

    def test_prefix_pattern_aborts(self, blacklist: Path) -> None:
        with pytest.raises(BlacklistError, match="Legal"):
            sync_space(_fake_client(), "LegalOps", Path("mirror"), _config())

    def test_refusal_names_the_declaring_file(self, blacklist: Path) -> None:
        with pytest.raises(BlacklistError, match=str(blacklist)):
            sync_space(_fake_client(), "PRIVATE", Path("mirror"), _config())

    def test_dry_run_is_gated_too(self, blacklist: Path) -> None:
        """--dry-run of a blacklisted space still refuses; it is not a preview escape."""
        with pytest.raises(BlacklistError, match="PRIVATE"):
            sync_space(
                _fake_client(),
                "PRIVATE",
                Path("mirror"),
                _config(),
                opts=SyncOptions(dry_run=True),
            )

    def test_missing_config_aborts(self) -> None:
        """Fail closed, matching the SharePoint half: no config is not an allow-all."""
        with pytest.raises(BlacklistConfigError, match="No data-protection blacklist found"):
            sync_space(_fake_client(), "ENG", Path("mirror"), _config())

    def test_non_blacklisted_space_proceeds(self, empty_blacklist: Path, tmp_path: Path) -> None:
        output_dir = tmp_path / "mirror"
        client = _fake_client()
        client.get_folder.side_effect = Exception("no folders")
        with (
            patch("mdd.confluence.sync.get_space_id", return_value="98306"),
            patch("mdd.confluence.sync.state.list_pages_for_sync", return_value=[]),
        ):
            summary = sync_space(
                client,
                "ENG",
                output_dir,
                _config(),
                opts=SyncOptions(dry_run=False),
            )
        # Got past the gate and ran a real (empty) reconciliation.
        assert summary.failures == []
        assert output_dir.exists()


# ---------------------------------------------------------------------------
# export_page
# ---------------------------------------------------------------------------


class TestExportPageGate:
    def test_blacklisted_space_aborts_before_writing(self, blacklist: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        with pytest.raises(BlacklistError, match="PRIVATE"):
            export_page(_fake_client(), "42", out_dir, page_data=_page_data("PRIVATE"))
        assert not out_dir.exists()

    def test_gate_runs_on_the_fetched_page_when_no_page_data_passed(
        self, blacklist: Path, tmp_path: Path
    ) -> None:
        client = _fake_client()
        client.get_page.return_value = _page_data("PRIVATE")
        with pytest.raises(BlacklistError, match="PRIVATE"):
            export_page(client, "42", tmp_path / "out")

    def test_unknown_space_refused_while_a_blacklist_is_active(
        self, blacklist: Path, tmp_path: Path
    ) -> None:
        page = _page_data("PRIVATE")
        del page["spaceKey"]
        page["_links"] = {}
        with pytest.raises(BlacklistError, match="Could not determine which Confluence space"):
            export_page(_fake_client(), "42", tmp_path / "out", page_data=page)

    def test_unknown_space_allowed_when_nothing_is_blacklisted(
        self,
        empty_blacklist: Path,
        tmp_path: Path,
        no_attachment_sync: None,
    ) -> None:
        page = _page_data("ENG")
        del page["spaceKey"]
        page["_links"] = {}
        out = export_page(_fake_client(), "42", tmp_path / "out", page_data=page)
        assert out.exists()

    def test_missing_config_aborts(self, tmp_path: Path) -> None:
        with pytest.raises(BlacklistConfigError, match="No data-protection blacklist found"):
            export_page(_fake_client(), "42", tmp_path / "out", page_data=_page_data("ENG"))

    def test_non_blacklisted_space_proceeds(
        self,
        empty_blacklist: Path,
        tmp_path: Path,
        no_attachment_sync: None,
    ) -> None:
        out = export_page(_fake_client(), "42", tmp_path / "out", page_data=_page_data("ENG"))
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("---")
