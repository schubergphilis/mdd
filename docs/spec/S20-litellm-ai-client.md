# 020 - LiteLLM AI client and caching infrastructure

**Purpose:** Establish a shared `mdd.ai` package wrapping a LiteLLM gateway with uniform retry, concurrency, and caching.

**Status:** Implemented (2026-05-08)

## Introduction

This spec covers foundational plumbing for [S21](S21-ai-rewrite-and-index.md), [S22](S22-ai-review-command.md), and [S23](S23-skills-bundle.md); no user-facing command ships here. The package exposes a small API for downstream `mdd ai *` subcommands: one `Client` class, retry/concurrency/caching applied uniformly, and a reserved embeddings surface. Originates from research note R03.

## Config schema

```yaml
ai:
  api_token: op://Employee/litellm-pat/token
  base_url: https://litellm.example.com/v1   # optional; this is the default
  models:
    default: claude-sonnet-4-5     # rewrites, judges
    summarise: claude-haiku-4-5    # cheap summaries
    embed: text-embedding-3-large  # used by [S22](S22-ai-review-command.md) if/when added
  concurrency: 4
  cache_dir: ~/.cache/mdd/ai
  cache_ttl_days: 30
```

## Requirements

**HTTP client**
- Use the OpenAI Python SDK (`openai>=1.50`) configured with the
  LiteLLM `base_url` and the API key resolved via
  `mdd.utils.secrets.resolve_secret()` ([S07](S07-data-protection.md)).
- Single `mdd.ai.Client` class encapsulates instantiation and
  defaults. Constructed once per process; reused.

**Auth**
- Token reference is an `op://` path. Resolved on demand. No raw
  tokens in config; no env-var interpolation. Same rule as [S07](S07-data-protection.md)
  / [S09](S09-confluence-command.md).
- If the token cannot be resolved, exit 1 with an actionable hint
  pointing at the 1Password entry and `op read` verification.

**Model configuration**
- Per-task-class model defaults: `default` for rewrites/judges,
  `summarise` for cheap summaries, `embed` reserved for future
  embeddings use.
- `mdd.ai.Client.chat(...)` selects the model by task class; callers
  may override per call.

**Model availability check**
- On first use per process, fetch `/v1/models` and check that all
  configured task-class models are present.
- If a model is missing, raise an actionable error naming the
  configured value and listing the available models.

**Retry and rate**
- Retry on 429, 503, 5xx, `ConnectionError`.
- Exponential backoff: 1s, 2s, 4s, 8s, 16s; max 5 attempts.
- Honour `Retry-After` header when present (cap at 60s); same as
  [S16](S16-confluence-attachment-conversion.md).
- Concurrent in-flight call cap of 4 by default (`ai.concurrency`).
  Implemented as an internal semaphore on the Client.

**Caching**
- Cache key = SHA-256 of:
  - input prompt (system + user messages, serialised canonically)
  - model name
  - configured task class
  - mdd version (so upgrades flush automatically)
  - any extra cache-key fields the caller passes (e.g. style prompt
    hash for `mdd ai rewrite`)
- Backend: filesystem at `ai.cache_dir`. One JSON file per hash
  containing the response, timestamp, and metadata for TTL eviction.
- Cache hit path is purely local; the returned `ChatResult` has
  `cached=True` and `prompt_tokens=0` so accounting reflects only
  what was actually billed.
- TTL eviction: any cache file older than `ai.cache_ttl_days`
  (default 30) is purged on the next cache access. Out-of-band:
  `mdd ai cache prune` and `mdd ai cache clear`.

**Cost / token reporting**
- Each `chat()` call returns a `ChatResult` containing the response
  text, `cached` flag, `prompt_tokens`, `completion_tokens`, and
  `cost_usd` (when the proxy returns it).
- A run-level accumulator at `mdd.ai.Client.summary` aggregates
  totals; commands print them at end-of-run.

**Embeddings (signature only)**
- `Client.embed(text)` is reserved API surface for [S22](S22-ai-review-command.md)'s
  review work. Not implemented or used by 020 itself.

**Error surface** — bespoke `AiError` hierarchy:
`AiAuthError` (token missing/rejected), `AiModelUnavailableError`
(configured model not in `/v1/models`), `AiRateLimitedError` (429
after retries exhausted), `AiServerError` (5xx after retries
exhausted). All carry actionable message strings.

## Design Approach

The OpenAI SDK is sufficient against the LiteLLM proxy; we do not
build a provider-neutral abstraction. Retry, concurrency limiting,
and caching are layered around the SDK call rather than relying on
SDK-internal retry, so policy is uniform across every callsite and
visible in one place.

Caching is content-addressed by canonical prompt + model + task +
mdd version. The "mdd version" component means library upgrades
naturally invalidate stale entries without manual purge. Callers
who need extra invalidation (e.g. `ai rewrite` keying on a style
prompt) pass `cache_key_extra` bytes.

## Out of scope

- Streaming responses. v1 is request/response only; streaming can
  be added when a use case calls for it (`mdd ai chat`?).
- Provider-neutral abstractions. The OpenAI SDK is sufficient
  against the LiteLLM proxy; we don't try to swap in Anthropic SDK
  later.
- Per-call audit logging beyond what the LiteLLM proxy itself logs
  centrally. Add later if audit policy demands it.
- A REST endpoint check for token validity beyond the model list
  call.
