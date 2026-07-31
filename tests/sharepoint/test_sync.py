"""Tests for mdd.sharepoint.sync — sync-root resolution and site discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.commands.sharepoint import _load_config  # pyright: ignore[reportPrivateUsage]
from mdd.sharepoint.models import SharepointCliConfig, SharepointCliSection
from mdd.sharepoint.sync import SyncRootMissing, list_sites, resolve_sync_root

if TYPE_CHECKING:
    from pathlib import Path


class TestListSites:
    def test_library_root_strips_documents_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "HR Documentation - Documents").mkdir()
        entries = list_sites(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.is_library_root is True
        assert e.display_name == "HR Documentation - Documents"
        assert e.derived_site_name == "HR Documentation"

    def test_subfolder_sync_no_strip(self, tmp_path: Path) -> None:
        (tmp_path / "Appraisals - Alice Example").mkdir()
        entries = list_sites(tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.is_library_root is False
        assert e.display_name == "Appraisals - Alice Example"
        assert e.derived_site_name == "Appraisals - Alice Example"

    def test_dotfiles_skipped(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "._onedrive_meta").mkdir()
        (tmp_path / "Visible Site - Documents").mkdir()
        entries = list_sites(tmp_path)
        names = [e.display_name for e in entries]
        assert ".hidden" not in names
        assert "._onedrive_meta" not in names
        assert "Visible Site - Documents" in names

    def test_underscore_prefix_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "_internal").mkdir()
        (tmp_path / "Normal Site - Documents").mkdir()
        entries = list_sites(tmp_path)
        names = [e.display_name for e in entries]
        assert "_internal" not in names
        assert "Normal Site - Documents" in names

    def test_non_directories_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "SomeSite - Documents").mkdir()
        entries = list_sites(tmp_path)
        assert len(entries) == 1
        assert entries[0].display_name == "SomeSite - Documents"

    def test_empty_sync_root(self, tmp_path: Path) -> None:
        entries = list_sites(tmp_path)
        assert entries == []

    def test_multiple_sites_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "Zebra Site - Documents").mkdir()
        (tmp_path / "Alpha Site - Documents").mkdir()
        entries = list_sites(tmp_path)
        assert entries[0].derived_site_name == "Alpha Site"
        assert entries[1].derived_site_name == "Zebra Site"

    def test_path_is_set_correctly(self, tmp_path: Path) -> None:
        d = tmp_path / "Engineering - Documents"
        d.mkdir()
        entries = list_sites(tmp_path)
        assert entries[0].path == d


class TestResolveSyncRoot:
    def test_discovers_the_shared_library_root(self, tmp_path: Path) -> None:
        """The tenant name is site-specific, so it is globbed, not hard-coded."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        cloud = fake_home / "Library" / "CloudStorage" / "OneDrive-SharedLibraries-Contoso"
        cloud.mkdir(parents=True)
        with patch("mdd.sharepoint.sync.Path.home", return_value=fake_home):
            result = resolve_sync_root()
        assert result == cloud

    def test_refuses_to_guess_between_two_tenants(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        cloud = fake_home / "Library" / "CloudStorage"
        (cloud / "OneDrive-SharedLibraries-Contoso").mkdir(parents=True)
        (cloud / "OneDrive-SharedLibraries-Fabrikam").mkdir(parents=True)
        with (
            patch("mdd.sharepoint.sync.Path.home", return_value=fake_home),
            pytest.raises(SyncRootMissing, match="Multiple OneDrive shared-library roots"),
        ):
            _ = resolve_sync_root()

    def test_ignores_non_shared_library_cloud_entries(self, tmp_path: Path) -> None:
        """A personal OneDrive is not a SharePoint sync root."""
        fake_home = tmp_path / "home"
        cloud = fake_home / "Library" / "CloudStorage"
        (cloud / "OneDrive-Personal").mkdir(parents=True)
        shared = cloud / "OneDrive-SharedLibraries-Contoso"
        shared.mkdir(parents=True)
        with patch("mdd.sharepoint.sync.Path.home", return_value=fake_home):
            assert resolve_sync_root() == shared

    def test_raises_if_neither_exists(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch("mdd.sharepoint.sync.Path.home", return_value=fake_home),
            pytest.raises(SyncRootMissing),
        ):
            resolve_sync_root()

    def test_config_override_wins(self, tmp_path: Path) -> None:
        custom_root = tmp_path / "custom_onedrive"
        custom_root.mkdir()

        config = SharepointCliConfig(sharepoint=SharepointCliSection(sync_root=str(custom_root)))
        result = resolve_sync_root(config)
        assert result == custom_root

    def test_config_override_missing_path_falls_through(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        cloud = fake_home / "Library" / "CloudStorage" / "OneDrive-SharedLibraries-Contoso"
        cloud.mkdir(parents=True)

        config = SharepointCliConfig(
            sharepoint=SharepointCliSection(sync_root=str(tmp_path / "nonexistent"))
        )
        with patch("mdd.sharepoint.sync.Path.home", return_value=fake_home):
            result = resolve_sync_root(config)
        # A configured-but-missing path falls through to discovery.
        assert result == cloud

    def test_config_from_real_yaml_file_is_honoured(self, tmp_path: Path) -> None:
        """The path from `_load_config` (the CLI's real parse path) must work here too.

        This is the regression test for the bug where `resolve_sync_root`
        `getattr`'d a plain `dict` — always `None` — instead of the typed
        config `_load_config` actually returns.
        """
        custom_root = tmp_path / "custom_onedrive"
        custom_root.mkdir()
        config_path = tmp_path / "sharepoint.yaml"
        config_path.write_text(f"sharepoint:\n  sync_root: {custom_root}\n")

        config = _load_config(config_path)
        assert config is not None

        result = resolve_sync_root(config)
        assert result == custom_root

    def test_error_message_mentions_macos(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        with (
            patch("mdd.sharepoint.sync.Path.home", return_value=fake_home),
            pytest.raises(SyncRootMissing, match="macOS"),
        ):
            resolve_sync_root()
