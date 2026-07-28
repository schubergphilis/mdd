"""Tests for mdd.ai.config — config loading and validation (spec S20)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mdd.ai.config import AiConfig, load
from mdd.ai.models import AiAuthError
from mdd.utils.config import ConfigError
from mdd.utils.secrets import SecretError

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


_VALID_YAML = """\
ai:
  api_token: plaintoken
  base_url: https://litellm.example.com/v1
  models:
    default: gpt-4o
    summarise: gpt-4o-mini
  concurrency: 2
  cache_ttl_days: 7
"""


class TestLoadValidConfig:
    def test_returns_ai_config(self, tmp_path: Path) -> None:
        cfg_file = _write_config(tmp_path / "ai.yaml", _VALID_YAML)
        cfg = load(cfg_file)
        assert isinstance(cfg, AiConfig)
        assert cfg.api_token == "plaintoken"
        assert cfg.base_url == "https://litellm.example.com/v1"
        assert cfg.models["default"] == "gpt-4o"
        assert cfg.models["summarise"] == "gpt-4o-mini"
        assert cfg.concurrency == 2
        assert cfg.cache_ttl_days == 7

    def test_strips_trailing_slash_from_base_url(self, tmp_path: Path) -> None:
        yaml = _VALID_YAML.replace(
            "base_url: https://litellm.example.com/v1",
            "base_url: https://litellm.example.com/v1/",
        )
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert not cfg.base_url.endswith("/")

    def test_resolves_op_reference(self, tmp_path: Path) -> None:
        yaml = _VALID_YAML.replace("api_token: plaintoken", "api_token: op://Vault/Item/token")
        cfg_file = _write_config(tmp_path / "ai.yaml", yaml)
        with patch("mdd.ai.config.resolve_secret", return_value="resolved-token"):
            cfg = load(cfg_file)
        assert cfg.api_token == "resolved-token"

    def test_defaults_applied_for_missing_optional_fields(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: tok\n"
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert cfg.concurrency == 4
        assert cfg.cache_ttl_days == 30
        assert "default" in cfg.models
        assert cfg.base_url == "http://localhost:4000/v1"

    def test_custom_cache_dir(self, tmp_path: Path) -> None:
        yaml = f"ai:\n  api_token: tok\n  cache_dir: {tmp_path}/cache\n"
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert cfg.cache_dir == tmp_path / "cache"


class TestSiteDefaultsComeFromConfig:
    """`mdd.ai` ships open-source, so no site hostname may be a source literal (S44)."""

    def test_gateway_url_comes_from_config(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: tok\n  base_url: https://gateway.internal/v1\n"
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert cfg.base_url == "https://gateway.internal/v1"

    def test_token_hint_comes_from_config(self, tmp_path: Path) -> None:
        yaml = 'ai:\n  api_token: tok\n  token_hint: "ask the platform team"\n'
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert cfg.token_hint == "ask the platform team"

    def test_configured_token_hint_reaches_the_auth_error(self, tmp_path: Path) -> None:
        """The hint has to survive to the message a user actually sees."""
        yaml = 'ai:\n  token_hint: "ask the platform team"\n'
        with pytest.raises(AiAuthError) as exc_info:
            load(_write_config(tmp_path / "ai.yaml", yaml))
        assert "ask the platform team" in str(exc_info.value)

    def test_no_remote_gateway_host_in_the_module_source(self) -> None:
        """A regression guard for the S44 scrub gate, not a style preference.

        `mdd.ai` is published, so the only URL its source may contain is a
        loopback fallback. Anything else is a site's gateway leaking into a
        module that ships to strangers.
        """
        import pathlib
        import re as _re

        import mdd.ai.client
        import mdd.ai.config

        for module in (mdd.ai.config, mdd.ai.client):
            source = pathlib.Path(module.__file__ or "").read_text(encoding="utf-8")
            hosts = _re.findall(r"https?://([A-Za-z0-9.\-]+)", source)
            remote = [h for h in hosts if h not in {"localhost", "127.0.0.1"}]
            assert remote == [], f"{module.__name__} hard-codes gateway host(s): {remote}"


class TestLoadMissingToken:
    def test_raises_ai_auth_error_when_no_config_found(self) -> None:
        """When config file is not found, token is absent → AiAuthError."""
        with (
            patch("mdd.ai.config._find_config_file", return_value=None),
            pytest.raises(AiAuthError) as exc_info,
        ):
            load()
        assert "ai.api_token" in str(exc_info.value)
        assert "op://" in str(exc_info.value)

    def test_raises_ai_auth_error_when_token_key_absent(self, tmp_path: Path) -> None:
        yaml = "ai:\n  base_url: https://litellm.example.com/v1\n"
        with pytest.raises(AiAuthError):
            load(_write_config(tmp_path / "ai.yaml", yaml))

    def test_raises_ai_auth_error_on_secret_resolution_failure(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: op://Missing/Vault/token\n"
        cfg_file = _write_config(tmp_path / "ai.yaml", yaml)
        with (
            patch(
                "mdd.ai.config.resolve_secret",
                side_effect=SecretError("op read failed"),
            ),
            pytest.raises(AiAuthError) as exc_info,
        ):
            load(cfg_file)
        assert "ai.api_token" in str(exc_info.value)

    def test_actionable_hint_in_error_message(self) -> None:
        with (
            patch("mdd.ai.config._find_config_file", return_value=None),
            pytest.raises(AiAuthError) as exc_info,
        ):
            load()
        msg = str(exc_info.value)
        assert "1Password" in msg or "op://" in msg


class TestLoadValidation:
    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load(tmp_path / "nonexistent.yaml")

    def test_invalid_ai_section_type(self, tmp_path: Path) -> None:
        yaml = "ai: not-a-mapping\n"
        with pytest.raises(ConfigError):
            load(_write_config(tmp_path / "ai.yaml", yaml))

    def test_invalid_concurrency(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: tok\n  concurrency: 0\n"
        with pytest.raises(ConfigError):
            load(_write_config(tmp_path / "ai.yaml", yaml))

    def test_invalid_ttl(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: tok\n  cache_ttl_days: -1\n"
        with pytest.raises(ConfigError):
            load(_write_config(tmp_path / "ai.yaml", yaml))

    def test_model_override_merges_with_defaults(self, tmp_path: Path) -> None:
        yaml = "ai:\n  api_token: tok\n  models:\n    default: custom-model\n"
        cfg = load(_write_config(tmp_path / "ai.yaml", yaml))
        assert cfg.models["default"] == "custom-model"
        # Other defaults still present
        assert "embed" in cfg.models
