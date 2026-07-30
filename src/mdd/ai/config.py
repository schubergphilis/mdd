"""AI config loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mdd.ai.models import AiAuthError
from mdd.utils.config import ConfigError, load_yaml
from mdd.utils.secrets import SecretError, parse_secret_ref, resolve_secret

# Neutral fallback: a LiteLLM proxy on its default port. The real gateway is
# site-specific and belongs in configs/ai.yaml; no site hostname may be
# hard-coded here.
_DEFAULT_BASE_URL = "http://localhost:4000/v1"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mdd" / "ai"
_DEFAULT_CACHE_TTL_DAYS = 30
_DEFAULT_CONCURRENCY = 4
_DEFAULT_MODELS: dict[str, str] = {
    "default": "claude-sonnet-4-5",
    "summarise": "claude-haiku-4-5",
    "embed": "text-embedding-3-large",
}


@dataclass(frozen=True)
class AiConfig:
    """Resolved AI connection and behaviour config."""

    api_token: str  # resolved (plain token, not op://)
    base_url: str
    token_hint: str  # site-specific "how to fix a bad token" text
    models: dict[str, str]
    concurrency: int
    cache_dir: Path
    cache_ttl_days: int


def _find_config_file(explicit: Path | None) -> Path | None:
    """Search for an ai config file.  Returns None if none found (all defaults)."""
    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"Config file not found: {explicit}")
        return explicit

    for candidate in (
        Path("configs") / "ai.yaml",
        Path.home() / ".config" / "mdd" / "ai.yaml",
    ):
        if candidate.exists():
            return candidate

    return None


# Shown whenever the token is missing or rejected. Site deployments point
# at their own gateway and secret store, so the operational half of this
# message is config-supplied (`ai.token_hint`) rather than a source literal.
_DEFAULT_TOKEN_HINT = (
    "Set `ai.api_token` in configs/ai.yaml or ~/.config/mdd/ai.yaml. "  # noqa: S105  # not a secret: missing-token help text
    "The value may be an `op://` reference resolved through the 1Password CLI."
)
_AI_TOKEN_PREFIX = "AI token unavailable. Run `mdd ai --help` for setup. To fix: "  # noqa: S105  # not a secret: missing-token help text


def _token_hint(raw_ai: dict[str, Any]) -> str:
    """Return the configured token hint, or the neutral built-in default."""
    raw: Any = raw_ai.get("token_hint")  # pyright: ignore[reportAny]
    return raw if isinstance(raw, str) and raw else _DEFAULT_TOKEN_HINT


def _read_ai_section(config_path: Path | None) -> dict[str, Any]:
    """Return the `ai:` mapping from `config_path`, or {} when absent.

    Raises ConfigError if the section is present but not a mapping.
    """
    if config_path is None:
        return {}
    data = load_yaml(config_path)
    section: Any = data.get("ai")  # pyright: ignore[reportAny]
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"{config_path}: 'ai' section must be a mapping")
    return dict(section.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


def _resolve_api_token(raw_ai: dict[str, Any]) -> str:
    """Resolve the API token from raw config, following op:// references.

    Raises AiAuthError when missing or unresolvable; ConfigError when malformed.
    """
    api_token_raw: Any = raw_ai.get("api_token")  # pyright: ignore[reportAny]
    if api_token_raw is None or api_token_raw == "":
        raise AiAuthError(_AI_TOKEN_PREFIX + _token_hint(raw_ai))
    try:
        ref, account = parse_secret_ref(api_token_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ai.api_token is invalid: {exc}") from exc
    try:
        return resolve_secret(ref, account=account)
    except SecretError as exc:
        raise AiAuthError(_AI_TOKEN_PREFIX + _token_hint(raw_ai)) from exc


def _resolve_base_url(raw_ai: dict[str, Any]) -> str:
    """Validate `ai.base_url`, defaulting to `_DEFAULT_BASE_URL`, trailing-slash stripped."""
    raw: Any = raw_ai.get("base_url", _DEFAULT_BASE_URL)  # pyright: ignore[reportAny]
    if not isinstance(raw, str) or not raw:
        raise ConfigError("ai.base_url must be a non-empty string")
    return raw.rstrip("/")


def _resolve_models(raw_ai: dict[str, Any]) -> dict[str, str]:
    """Return `_DEFAULT_MODELS` merged with overrides from `ai.models`.

    Raises ConfigError if the override section is not a string→string mapping.
    """
    raw: Any = raw_ai.get("models")  # pyright: ignore[reportAny]
    models: dict[str, str] = dict(_DEFAULT_MODELS)
    if raw is None:
        return models
    if not isinstance(raw, dict):
        raise ConfigError("ai.models must be a mapping")
    for k, v in raw.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(k, str) or not isinstance(v, str):
            raise ConfigError("ai.models entries must be string→string mappings")
        models[k] = v
    return models


def _resolve_concurrency(raw_ai: dict[str, Any]) -> int:
    """Validate `ai.concurrency` (positive int, default `_DEFAULT_CONCURRENCY`)."""
    raw: Any = raw_ai.get("concurrency", _DEFAULT_CONCURRENCY)  # pyright: ignore[reportAny]
    if not isinstance(raw, int) or raw < 1:
        raise ConfigError("ai.concurrency must be a positive integer")
    return raw


def _resolve_cache_dir(raw_ai: dict[str, Any]) -> Path:
    """Validate `ai.cache_dir` (non-empty string or default), expanding `~`."""
    raw: Any = raw_ai.get("cache_dir")  # pyright: ignore[reportAny]
    if raw is None:
        return _DEFAULT_CACHE_DIR
    if not isinstance(raw, str) or not raw:
        raise ConfigError("ai.cache_dir must be a non-empty string")
    return Path(raw).expanduser()


def _resolve_cache_ttl_days(raw_ai: dict[str, Any]) -> int:
    """Validate `ai.cache_ttl_days` (non-negative int, default `_DEFAULT_CACHE_TTL_DAYS`)."""
    raw: Any = raw_ai.get("cache_ttl_days", _DEFAULT_CACHE_TTL_DAYS)  # pyright: ignore[reportAny]
    if not isinstance(raw, int) or raw < 0:
        raise ConfigError("ai.cache_ttl_days must be a non-negative integer")
    return raw


def load(path: Path | None = None) -> AiConfig:
    """Load and validate the AI config.

    Search order: explicit path -> ./configs/ai.yaml -> ~/.config/mdd/ai.yaml.

    Falls back to sane defaults when no config file is found, but the token
    is required and will raise AiAuthError when absent.

    Raises ConfigError on malformed config.
    Raises AiAuthError when the token cannot be resolved.
    """
    raw_ai = _read_ai_section(_find_config_file(path))
    return AiConfig(
        api_token=_resolve_api_token(raw_ai),
        base_url=_resolve_base_url(raw_ai),
        token_hint=_token_hint(raw_ai),
        models=_resolve_models(raw_ai),
        concurrency=_resolve_concurrency(raw_ai),
        cache_dir=_resolve_cache_dir(raw_ai),
        cache_ttl_days=_resolve_cache_ttl_days(raw_ai),
    )
