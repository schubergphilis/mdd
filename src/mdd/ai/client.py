"""AI client wrapping the OpenAI SDK against the LiteLLM proxy."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Literal, cast

import openai

from mdd.ai.cache import FileSystemCache, build_cache_key
from mdd.ai.config import AiConfig
from mdd.ai.config import load as load_config
from mdd.ai.models import (
    AiAuthError,
    AiModelUnavailableError,
    ChatResult,
    EmbedResult,
    RunSummary,
    is_complete,
)
from mdd.ai.retry import with_retry
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)

_EMBED_DIMENSIONS: int | None = None


class Client:
    """Single AI client for the current process.

    Constructed once, reused for all calls.  Wraps the OpenAI Python SDK
    configured against the LiteLLM gateway.

    Thread-safe via an internal concurrency semaphore.

    Usage::

        client = Client()
        result = client.chat(user="Summarise this text...", task="summarise")
        print(result.text)
        print(client.summary)
    """

    def __init__(self, *, config: AiConfig | None = None) -> None:
        self._config: AiConfig = config if config is not None else load_config()
        self._oai: openai.OpenAI | None = None
        self._sem = threading.Semaphore(self._config.concurrency)
        self._cache = FileSystemCache(
            cache_dir=self._config.cache_dir,
            ttl_days=self._config.cache_ttl_days,
        )
        self._summary = RunSummary()
        self._models_checked = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_oai(self) -> openai.OpenAI:
        if self._oai is None:
            try:
                self._oai = openai.OpenAI(
                    api_key=self._config.api_token,
                    base_url=self._config.base_url,
                )
            except openai.AuthenticationError as exc:
                raise AiAuthError(f"AI token was rejected. {self._config.token_hint}") from exc
        return self._oai

    def _ensure_models_checked(self) -> None:
        """Fetch /v1/models on first use and validate configured models.

        Raises AiModelUnavailableError if any configured model is absent.
        """
        with self._lock:
            if self._models_checked:
                return
            self._models_checked = True  # set before call so parallel threads skip

        try:
            available = self._fetch_available_models()
        except AiAuthError:
            raise
        except AiModelUnavailableError:
            raise
        except Exception as exc:
            # Non-fatal: network hiccup — skip model check rather than blocking.
            _ = exc
            return

        for task, model in self._config.models.items():
            if model not in available:
                raise AiModelUnavailableError(
                    f"Configured model {model!r} (task={task!r}) is not available. "
                    f"Available models: {sorted(available)}"
                )

    @with_retry
    def _fetch_available_models(self) -> set[str]:
        """Call /v1/models and return the set of model IDs."""
        oai = self._get_oai()
        resp = oai.models.list()
        return {m.id for m in resp.data}

    def model_for_task(self, task: str, override: str | None) -> str:
        """Resolve the model name for *task*, honouring an explicit *override*.

        Falls back to ``models[task]`` then ``models["default"]`` then ``""``.
        """
        if override:
            return override
        return self._config.models.get(task, self._config.models.get("default", ""))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(  # noqa: PLR0913
        self,
        *,
        system: str | None = None,
        user: str,
        task: Literal["default", "summarise"] = "default",
        model: str | None = None,
        cache_key_extra: bytes = b"",
        max_tokens: int | None = None,
        accept: Callable[[str], bool] | None = None,
    ) -> ChatResult:
        """Send a chat completion request, using the cache if available.

        Parameters
        ----------
        system:
            Optional system prompt.
        user:
            The user message text.
        task:
            Task class used for model selection (``"default"`` or
            ``"summarise"``).
        model:
            Override the task-class model selection with a specific model name.
        cache_key_extra:
            Additional bytes mixed into the cache key (e.g. the style-prompt
            hash used by rewrites).
        max_tokens:
            Maximum completion tokens.  None uses the model default.
        accept:
            Optional check on the response text.  A response it rejects is
            still returned, but is never written to the cache, and a cached
            entry it rejects is ignored in favour of a live call.  Callers
            use it to keep output they are going to refuse out of the cache.

        Returns
        -------
        ChatResult
        """
        self._ensure_models_checked()

        resolved_model = self.model_for_task(task, model)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        cache_key = build_cache_key(
            model=resolved_model,
            task=task,
            messages=messages,
            cache_key_extra=cache_key_extra,
        )

        # Cache check — purely local, no semaphore needed.
        cached = self._cached_result(cache_key, accept)
        if cached is not None:
            log.debug(
                "chat cache hit: model=%s task=%s key=%s chars=%d",
                resolved_model,
                task,
                cache_key[:12],
                len(cached.text),
            )
            self._summary.record_chat(cached)
            return cached

        # Acquire the concurrency semaphore for the live API call.
        with self._sem:
            # Double-check cache after acquiring semaphore — another thread
            # may have filled it while we were waiting.
            cached = self._cached_result(cache_key, accept)
            if cached is not None:
                self._summary.record_chat(cached)
                return cached

            log.debug(
                "chat request: model=%s task=%s system_chars=%d user_chars=%d max_tokens=%s",
                resolved_model,
                task,
                len(system) if system else 0,
                len(user),
                max_tokens,
            )
            result = self._do_chat(
                resolved_model=resolved_model,
                messages=messages,
                max_tokens=max_tokens,
                cache_key=cache_key,
                accept=accept,
            )

        self._summary.record_chat(result)
        return result

    def _cached_result(
        self,
        cache_key: str,
        accept: Callable[[str], bool] | None,
    ) -> ChatResult | None:
        """Return the cached response for *cache_key*, or None on a miss.

        An entry that *accept* rejects counts as a miss.
        """
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        if accept is not None and not accept(entry.text):
            log.debug("chat cache entry %s rejected by caller; ignoring it", cache_key[:12])
            return None
        return ChatResult(
            text=entry.text,
            cached=True,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=None,
            finish_reason=entry.finish_reason,
        )

    @with_retry
    def _do_chat(
        self,
        *,
        resolved_model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None,
        cache_key: str,
        accept: Callable[[str], bool] | None,
    ) -> ChatResult:
        """Execute one chat completion call (already inside the semaphore)."""
        oai = self._get_oai()
        kwargs: dict[str, Any] = {  # pyright: ignore[reportExplicitAny]
            "model": resolved_model,
            "messages": messages,  # pyright: ignore[reportArgumentType]
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response: Any = oai.chat.completions.create(**kwargs)  # pyright: ignore[reportArgumentType,reportUnknownVariableType,reportAny]
        except openai.AuthenticationError as exc:
            raise AiAuthError(
                f"AI token was rejected (401/403). {self._config.token_hint}"
            ) from exc

        # Access openai SDK return values through Any to silence strict unknown-member errors.
        choice: Any = response.choices[0]  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        raw_text: Any = choice.message.content  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        text: str = str(raw_text) if raw_text is not None else ""  # pyright: ignore[reportUnknownArgumentType]

        raw_finish: Any = choice.finish_reason  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        finish_reason: str | None = str(raw_finish) if raw_finish else None  # pyright: ignore[reportUnknownArgumentType]

        usage: Any = response.usage  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        prompt_tokens: int = int(usage.prompt_tokens) if usage and usage.prompt_tokens else 0  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType,reportUnknownArgumentType]
        completion_tokens: int = (
            int(usage.completion_tokens) if usage and usage.completion_tokens else 0  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType,reportUnknownArgumentType]
        )

        # LiteLLM may surface cost in a non-standard field.
        cost_usd: float | None = None
        for attr in ("_hidden_params", "__dict__"):
            container: Any = getattr(response, attr, None)  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType,reportUnknownArgumentType]
            if isinstance(container, dict):
                cost_raw: Any = cast("dict[str, Any]", container).get("response_cost")  # pyright: ignore[reportAny]
                cost_usd = _optional_float(cost_raw)
                if cost_usd is not None:
                    break

        log.debug(
            "chat response: model=%s finish_reason=%s chars=%d prompt_tokens=%d "
            "completion_tokens=%d",
            resolved_model,
            finish_reason,
            len(text),
            prompt_tokens,
            completion_tokens,
        )

        result = ChatResult(
            text=text,
            cached=False,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            finish_reason=finish_reason,
        )
        self._cache_if_usable(cache_key, resolved_model, result, accept)
        return result

    def _cache_if_usable(
        self,
        cache_key: str,
        resolved_model: str,
        result: ChatResult,
        accept: Callable[[str], bool] | None,
    ) -> None:
        """Store *result*, unless it was cut off or the caller rejects it.

        A truncated completion is a prefix of the real answer; caching it would
        make every later run reproduce the same partial output from disk.  The
        same holds for a response the caller is about to refuse.
        """
        if not is_complete(result.finish_reason):
            log.warning(
                "model %s stopped early (finish_reason=%s) after %d completion tokens; "
                "response NOT cached",
                resolved_model,
                result.finish_reason,
                result.completion_tokens,
            )
            return
        if accept is not None and not accept(result.text):
            log.debug("model %s response rejected by caller; response NOT cached", resolved_model)
            return
        self._cache.put(
            cache_key,
            text=result.text,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            finish_reason=result.finish_reason,
        )

    def embed(
        self,
        text: str | list[str],
        *,
        model: str | None = None,
    ) -> EmbedResult:
        """Return embeddings for *text*.

        No command calls this yet; it is kept for future semantic search.
        Backed by the OpenAI SDK's ``embeddings.create()`` endpoint on the
        LiteLLM proxy.
        """
        self._ensure_models_checked()

        resolved_model = model or self._config.models.get("embed", "text-embedding-3-large")
        inputs: list[str] = [text] if isinstance(text, str) else text

        with self._sem:
            return self._do_embed(resolved_model=resolved_model, inputs=inputs)

    @with_retry
    def _do_embed(
        self,
        *,
        resolved_model: str,
        inputs: list[str],
    ) -> EmbedResult:
        oai = self._get_oai()
        try:
            response: Any = oai.embeddings.create(model=resolved_model, input=inputs)  # pyright: ignore[reportAny,reportUnknownVariableType]
        except openai.AuthenticationError as exc:
            raise AiAuthError(
                f"AI token was rejected (401/403). {self._config.token_hint}"
            ) from exc

        vectors: list[list[float]] = [list(item.embedding) for item in response.data]  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        usage: Any = response.usage  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
        prompt_tokens: int = int(usage.prompt_tokens) if usage and usage.prompt_tokens else 0  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType,reportUnknownArgumentType]

        return EmbedResult(
            vectors=vectors,
            cached=False,
            prompt_tokens=prompt_tokens,
        )

    @property
    def summary(self) -> RunSummary:
        """Accumulated per-run totals."""
        return self._summary


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # pyright: ignore[reportArgumentType]
    except ValueError, TypeError:
        return None
