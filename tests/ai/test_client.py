"""Tests for mdd.ai.client — Client class with mocked OpenAI SDK."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import openai
import pytest

from mdd.ai.client import Client
from mdd.ai.config import AiConfig
from mdd.ai.models import AiAuthError, AiModelUnavailableError, ChatResult

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_MODELS = {"claude-sonnet-4-5", "claude-haiku-4-5", "text-embedding-3-large"}


def _make_config(tmp_path: Path, *, concurrency: int = 4) -> AiConfig:
    return AiConfig(
        api_token="test-token",
        base_url="https://litellm.example.com/v1",
        token_hint="set ai.api_token in ~/.config/mdd/ai.yaml.",
        models={
            "default": "claude-sonnet-4-5",
            "summarise": "claude-haiku-4-5",
            "embed": "text-embedding-3-large",
        },
        concurrency=concurrency,
        cache_dir=tmp_path / "ai_cache",
        cache_ttl_days=30,
    )


def _make_completion(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> Any:  # pyright: ignore[reportAny]
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClientChat:
    def test_returns_chat_result(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("Hello back!")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            result = client.chat(user="Hello!")

        assert isinstance(result, ChatResult)
        assert result.text == "Hello back!"
        assert result.cached is False
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5

    def test_cache_hit_on_second_call(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("Cached text")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            result1 = client.chat(user="Same prompt")
            result2 = client.chat(user="Same prompt")

        # Only one API call
        assert mock_oai.chat.completions.create.call_count == 1
        assert result1.cached is False
        assert result2.cached is True
        assert result2.text == "Cached text"
        assert result2.prompt_tokens == 0

    def test_cache_miss_on_different_prompts(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("response")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="Prompt A")
            client.chat(user="Prompt B")

        assert mock_oai.chat.completions.create.call_count == 2

    def test_task_selects_model(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="hello", task="summarise")

        call_kwargs = mock_oai.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-haiku-4-5"

    def test_model_override(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")
        extended_models = _ALL_MODELS | {"my-custom-model"}

        with patch.object(client, "_fetch_available_models", return_value=extended_models):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="hello", model="my-custom-model")

        call_kwargs = mock_oai.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "my-custom-model"

    def test_system_message_included(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(system="Be concise.", user="hello")

        call_kwargs = mock_oai.chat.completions.create.call_args
        messages = call_kwargs.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be concise."
        assert messages[1]["role"] == "user"

    def test_cache_key_extra_changes_key(self, tmp_path: Path) -> None:
        """Same prompt with different cache_key_extra must miss the cache."""
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="hello", cache_key_extra=b"style-a")
            client.chat(user="hello", cache_key_extra=b"style-b")

        assert mock_oai.chat.completions.create.call_count == 2

    def test_summary_accumulates(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok", prompt_tokens=20, completion_tokens=10)

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="a")
            client.chat(user="b")

        summary = client.summary
        assert summary.total_calls == 2
        assert summary.api_calls == 2
        assert summary.prompt_tokens == 40
        assert summary.completion_tokens == 20

    def test_summary_counts_cached_separately(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")

        with patch.object(client, "_fetch_available_models", return_value=_ALL_MODELS):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="same")
            client.chat(user="same")

        summary = client.summary
        assert summary.total_calls == 2
        assert summary.cached_calls == 1
        assert summary.api_calls == 1


class TestClientModelAvailability:
    def test_raises_model_unavailable_when_not_in_list(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)

        # Model list does not include "claude-haiku-4-5"
        with (
            patch.object(
                client,
                "_fetch_available_models",
                return_value={"claude-sonnet-4-5", "text-embedding-3-large"},
            ),
            pytest.raises(AiModelUnavailableError) as exc_info,
        ):
            client.chat(user="hello")

        assert "claude-haiku-4-5" in str(exc_info.value)

    def test_model_check_done_once(self, tmp_path: Path) -> None:
        """_ensure_models_checked should not call _fetch_available_models twice."""
        config = _make_config(tmp_path)
        client = Client(config=config)
        completion = _make_completion("ok")

        fetch_count = 0

        def mock_fetch() -> set[str]:
            nonlocal fetch_count
            fetch_count += 1
            return _ALL_MODELS

        with patch.object(client, "_fetch_available_models", side_effect=mock_fetch):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.return_value = completion
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            client.chat(user="a")
            client.chat(user="b")

        assert fetch_count == 1


class TestClientAuthError:
    def test_auth_error_on_completion_raises_ai_auth_error(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        client = Client(config=config)

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(
            client,
            "_fetch_available_models",
            return_value=_ALL_MODELS,
        ):
            mock_oai = MagicMock()
            mock_oai.chat.completions.create.side_effect = openai.AuthenticationError(
                message="Unauthorized", response=mock_response, body={}
            )
            client._oai = mock_oai  # pyright: ignore[reportPrivateUsage]

            with pytest.raises(AiAuthError):
                client.chat(user="hello")


@pytest.mark.integration
class TestClientIntegration:
    """Live round-trip test. Requires a live LiteLLM endpoint and valid config."""

    def test_live_chat(self) -> None:
        client = Client()
        result = client.chat(user="Say the word 'pong' and nothing else.")
        assert "pong" in result.text.lower()
        assert result.prompt_tokens > 0
        assert result.completion_tokens > 0
        assert result.cached is False

    def test_live_cache_hit(self) -> None:
        client = Client()
        r1 = client.chat(user="Say the word 'ping' and nothing else.")
        r2 = client.chat(user="Say the word 'ping' and nothing else.")
        assert r1.text == r2.text
        assert r2.cached is True
