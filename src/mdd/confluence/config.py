"""Confluence configuration loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mdd.utils.config import ConfigError, load_yaml
from mdd.utils.secrets import parse_secret_ref, resolve_secret


@dataclass(frozen=True)
class ConfluenceConfig:
    """Resolved Confluence connection config."""

    url: str  # base URL, e.g. https://example.atlassian.net
    username: str
    api_token: str  # already resolved (plain token, not op://)


def _find_config_file(explicit: Path | None) -> Path:
    """Find the confluence config file using the standard search path."""
    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"Config file not found: {explicit}")
        return explicit

    local = Path("configs") / "confluence.yaml"
    if local.exists():
        return local

    user = Path.home() / ".config" / "mdd" / "confluence.yaml"
    if user.exists():
        return user

    raise ConfigError(
        "No Confluence config found. "
        "Create ./configs/confluence.yaml or ~/.config/mdd/confluence.yaml, "
        "or pass an explicit path."
    )


def load(path: Path | None = None) -> ConfluenceConfig:
    """Load and validate the Confluence config.

    Search order: explicit path -> ./configs/confluence.yaml -> ~/.config/mdd/confluence.yaml.

    The api_token is resolved via resolve_secret() so op:// references are expanded.

    Raises ConfigError on missing file or missing key.
    """
    config_path = _find_config_file(path)
    data = load_yaml(config_path)

    confluence_raw: Any = data.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(confluence_raw, dict):
        raise ConfigError(f"{config_path}: missing or invalid 'confluence' section")
    conf: dict[str, Any] = dict(confluence_raw.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]

    url_raw: Any = conf.get("url")  # pyright: ignore[reportAny]
    if not isinstance(url_raw, str) or not url_raw:
        raise ConfigError(f"{config_path}: 'confluence.url' is required")
    url: str = url_raw

    username_raw: Any = conf.get("username")  # pyright: ignore[reportAny]
    if not isinstance(username_raw, str) or not username_raw:
        raise ConfigError(f"{config_path}: 'confluence.username' is required")
    username: str = username_raw

    api_token_raw: Any = conf.get("api_token")  # pyright: ignore[reportAny]
    if api_token_raw is None or api_token_raw == "":
        raise ConfigError(f"{config_path}: 'confluence.api_token' is required")
    try:
        ref, account = parse_secret_ref(api_token_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{config_path}: 'confluence.api_token' is invalid: {exc}") from exc
    api_token: str = resolve_secret(ref, account=account)

    return ConfluenceConfig(
        url=url.rstrip("/"),
        username=username,
        api_token=api_token,
    )
