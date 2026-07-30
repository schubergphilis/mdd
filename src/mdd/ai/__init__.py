"""mdd.ai — LiteLLM AI client plumbing.

Public API::

    from mdd.ai import Client, ChatResult

    client = Client()
    result = client.chat(user="Hello!", task="default")
    print(result.text, result.cached, result.cost_usd)
"""

from mdd.ai.client import Client
from mdd.ai.models import (
    AiAuthError,
    AiError,
    AiModelUnavailableError,
    AiRateLimitedError,
    AiServerError,
    ChatResult,
    EmbedResult,
    RunSummary,
)

__all__ = [
    "AiAuthError",
    "AiError",
    "AiModelUnavailableError",
    "AiRateLimitedError",
    "AiServerError",
    "ChatResult",
    "Client",
    "EmbedResult",
    "RunSummary",
]
