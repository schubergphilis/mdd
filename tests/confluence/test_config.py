"""Tests for mdd.confluence.config — config loading and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.confluence.config import ConfluenceConfig, load
from mdd.utils.config import ConfigError

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_VALID_YAML = """\
confluence:
  url: https://example.atlassian.net
  username: user@example.com
  api_token: plaintoken
"""


class TestLoadValidConfig:
    def test_returns_confluence_config(self, tmp_path: Path) -> None:
        cfg_file = _write_config(tmp_path / "confluence.yaml", _VALID_YAML)
        cfg = load(cfg_file)
        assert isinstance(cfg, ConfluenceConfig)
        assert cfg.url == "https://example.atlassian.net"
        assert cfg.username == "user@example.com"
        assert cfg.api_token == "plaintoken"

    def test_strips_trailing_slash_from_url(self, tmp_path: Path) -> None:
        yaml = _VALID_YAML.replace(
            "url: https://example.atlassian.net",
            "url: https://example.atlassian.net/",
        )
        cfg = load(_write_config(tmp_path / "confluence.yaml", yaml))
        assert not cfg.url.endswith("/")

    def test_resolves_op_reference(self, tmp_path: Path) -> None:
        yaml = _VALID_YAML.replace("api_token: plaintoken", "api_token: op://Vault/Item/token")
        cfg_file = _write_config(tmp_path / "confluence.yaml", yaml)
        with patch("mdd.confluence.config.resolve_secret", return_value="resolved-token") as mock:
            cfg = load(cfg_file)
        assert cfg.api_token == "resolved-token"
        # bare string -> account=None
        assert mock.call_args.kwargs == {"account": None}

    def test_api_token_object_passes_account_to_resolver(self, tmp_path: Path) -> None:
        yaml = (
            "confluence:\n"
            "  url: https://example.atlassian.net\n"
            "  username: user@example.com\n"
            "  api_token:\n"
            "    ref: op://Employee/confluence-pat/token\n"
            "    account: example-org\n"
        )
        cfg_file = _write_config(tmp_path / "confluence.yaml", yaml)
        with patch("mdd.confluence.config.resolve_secret", return_value="resolved-token") as mock:
            cfg = load(cfg_file)
        assert cfg.api_token == "resolved-token"
        mock.assert_called_once_with("op://Employee/confluence-pat/token", account="example-org")

    def test_api_token_object_missing_ref_raises(self, tmp_path: Path) -> None:
        yaml = (
            "confluence:\n"
            "  url: https://example.atlassian.net\n"
            "  username: user@example.com\n"
            "  api_token:\n"
            "    account: example-org\n"
        )
        with pytest.raises(ConfigError, match="api_token"):
            load(_write_config(tmp_path / "confluence.yaml", yaml))


class TestLoadMissingFile:
    def test_explicit_path_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load(tmp_path / "nonexistent.yaml")

    def test_no_config_anywhere_raises(self, tmp_path: Path) -> None:
        with (
            patch("mdd.confluence.config.Path.home", return_value=tmp_path),
            patch("mdd.confluence.config.Path.exists", return_value=False),
            pytest.raises(ConfigError, match="No Confluence config"),
        ):
            load(None)

    def test_falls_back_to_local_configs_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        cfg_dir = tmp_path / "configs"
        cfg_dir.mkdir()
        _write_config(cfg_dir / "confluence.yaml", _VALID_YAML)
        cfg = load(None)
        assert cfg.username == "user@example.com"

    def test_falls_back_to_home_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)  # no configs/ here
        home_cfg = tmp_path / ".config" / "mdd" / "confluence.yaml"
        _write_config(home_cfg, _VALID_YAML)
        with patch("mdd.confluence.config.Path.home", return_value=tmp_path):
            cfg = load(None)
        assert cfg.username == "user@example.com"


class TestLoadMissingKeys:
    def test_missing_confluence_section_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_config(tmp_path / "c.yaml", "other_section:\n  x: 1\n")
        with pytest.raises(ConfigError, match="confluence"):
            load(cfg_file)

    def test_missing_url_raises(self, tmp_path: Path) -> None:
        yaml = "confluence:\n  username: u\n  api_token: t\n"
        with pytest.raises(ConfigError, match="url"):
            load(_write_config(tmp_path / "c.yaml", yaml))

    def test_missing_username_raises(self, tmp_path: Path) -> None:
        yaml = "confluence:\n  url: https://x\n  api_token: t\n"
        with pytest.raises(ConfigError, match="username"):
            load(_write_config(tmp_path / "c.yaml", yaml))

    def test_missing_api_token_raises(self, tmp_path: Path) -> None:
        yaml = "confluence:\n  url: https://x\n  username: u\n"
        with pytest.raises(ConfigError, match="api_token"):
            load(_write_config(tmp_path / "c.yaml", yaml))

    def test_empty_url_raises(self, tmp_path: Path) -> None:
        yaml = "confluence:\n  url: ''\n  username: u\n  api_token: t\n"
        with pytest.raises(ConfigError, match="url"):
            load(_write_config(tmp_path / "c.yaml", yaml))
