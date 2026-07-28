"""Data models for mdd.ai (spec S20)."""

from __future__ import annotations

from dataclasses import dataclass


class AiError(Exception):
    """Base class for all AI-related errors.

    All subclasses carry an actionable message string.
    """


class AiAuthError(AiError):
    """Raised when the AI token is missing or rejected (HTTP 401/403)."""


class AiModelUnavailableError(AiError):
    """Raised when the configured model is not in /v1/models."""


class AiRateLimitedError(AiError):
    """Raised when 429 rate-limit persists after all retries."""


class AiServerError(AiError):
    """Raised when a 5xx error persists after all retries."""


@dataclass(frozen=True)
class ChatResult:
    """Result of a single chat() call."""

    text: str
    cached: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None


@dataclass(frozen=True)
class EmbedResult:
    """Result of a single embed() call."""

    vectors: list[list[float]]
    cached: bool
    prompt_tokens: int


@dataclass
class RunSummary:
    """Accumulated totals across all calls in a single process run."""

    total_calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    errors: int = 0

    def record_chat(self, result: ChatResult) -> None:
        """Accumulate a ChatResult into the summary."""
        self.total_calls += 1
        if result.cached:
            self.cached_calls += 1
        else:
            self.prompt_tokens += result.prompt_tokens
            self.completion_tokens += result.completion_tokens
            if result.cost_usd is not None:
                self.cost_usd += result.cost_usd

    def record_error(self) -> None:
        """Increment the error counter."""
        self.errors += 1

    @property
    def api_calls(self) -> int:
        """Number of non-cached calls that hit the API."""
        return self.total_calls - self.cached_calls
