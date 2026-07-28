"""Tests for mdd.utils.config."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.utils.config import ConfigError, find_blacklist_files, load_yaml

if TYPE_CHECKING:
    from pathlib import Path


class TestLoadYaml:
    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "conf.yaml"
        f.write_text("key: value\nnested:\n  x: 1\n", encoding="utf-8")
        data = load_yaml(f)
        assert data["key"] == "value"
        assert data["nested"]["x"] == 1  # type: ignore[index]

    def test_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("key: [\nunot closed", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_yaml(f)

    def test_non_mapping_yaml_raises_config_error(self, tmp_path: Path) -> None:
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="YAML mapping"):
            load_yaml(f)

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-file.yaml"
        with pytest.raises(ConfigError, match="Failed to read"):
            load_yaml(missing)

    @pytest.mark.skipif(
        __import__("os").geteuid() == 0,
        reason="chmod 0o000 has no effect on root",
    )
    def test_permission_denied_raises_config_error(self, tmp_path: Path) -> None:
        import os

        f = tmp_path / "locked.yaml"
        f.write_text("key: value\n", encoding="utf-8")
        os.chmod(f, 0o000)  # noqa: PTH101
        try:
            with pytest.raises(ConfigError, match="Failed to read"):
                load_yaml(f)
        finally:
            os.chmod(f, 0o644)  # noqa: PTH101


@pytest.fixture
def no_repo_blacklist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the repo-bundled blacklist doesn't exist (test isolation)."""
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: None)


class TestFindBlacklistFiles:
    def test_explicit_path_included(self, tmp_path: Path, no_repo_blacklist: None) -> None:
        del no_repo_blacklist
        f = tmp_path / "my-blacklist.yaml"
        f.write_text("confluence:\n  blacklisted_spaces: []\n")
        result = find_blacklist_files(f)
        assert f in result

    def test_explicit_missing_raises_config_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-blacklist.yaml"
        with pytest.raises(ConfigError, match="Blacklist file not found"):
            find_blacklist_files(missing)

    def test_falls_back_to_user_home(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        no_repo_blacklist: None,
    ) -> None:
        del no_repo_blacklist
        monkeypatch.chdir(tmp_path)  # no configs/ here
        user_cfg = tmp_path / ".config" / "mdd" / "data-protection.yaml"
        user_cfg.parent.mkdir(parents=True)
        user_cfg.write_text("confluence:\n  blacklisted_spaces: []\n")
        with patch("mdd.utils.config.Path.home", return_value=tmp_path):
            result = find_blacklist_files(None)
        assert result == [user_cfg]

    def test_raises_when_no_file_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        no_repo_blacklist: None,
    ) -> None:
        del no_repo_blacklist
        monkeypatch.chdir(tmp_path)
        with (
            patch("mdd.utils.config.Path.home", return_value=tmp_path),
            pytest.raises(ConfigError, match="No data-protection blacklist"),
        ):
            find_blacklist_files(None)

    def test_additive_repo_user_cwd_explicit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All four sources contribute when they all exist."""
        repo_file = tmp_path / "repo" / "data-protection.yaml"
        repo_file.parent.mkdir()
        repo_file.write_text("confluence:\n  blacklisted_spaces: []\n")

        user_file = tmp_path / ".config" / "mdd" / "data-protection.yaml"
        user_file.parent.mkdir(parents=True)
        user_file.write_text("confluence:\n  blacklisted_spaces: []\n")

        cwd_dir = tmp_path / "work"
        (cwd_dir / "configs").mkdir(parents=True)
        cwd_file = cwd_dir / "configs" / "data-protection.yaml"
        cwd_file.write_text("confluence:\n  blacklisted_spaces: []\n")

        explicit = tmp_path / "extra.yaml"
        explicit.write_text("confluence:\n  blacklisted_spaces: []\n")

        monkeypatch.chdir(cwd_dir)
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: repo_file)
        with patch("mdd.utils.config.Path.home", return_value=tmp_path):
            result = find_blacklist_files(explicit)
        assert [p.resolve() for p in result] == [
            repo_file.resolve(),
            user_file.resolve(),
            cwd_file.resolve(),
            explicit.resolve(),
        ]

    def test_dedupes_when_cwd_is_repo_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running from the repo root must not double-load the bundled file."""
        configs = tmp_path / "configs"
        configs.mkdir()
        repo_file = configs / "data-protection.yaml"
        repo_file.write_text("confluence:\n  blacklisted_spaces: []\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: repo_file)
        with patch("mdd.utils.config.Path.home", return_value=tmp_path):
            result = find_blacklist_files(None)
        assert len(result) == 1
        assert result[0].resolve() == repo_file.resolve()
