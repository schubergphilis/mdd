"""Filesystem cache backend for AI responses (spec S20).

Cache key is a SHA-256 hash of the canonical serialisation of:
  - model name
  - task class
  - system + user messages
  - temperature / extra params
  - mdd package version
  - caller-supplied cache_key_extra bytes

Each entry is a JSON file at <cache_dir>/<hex>.json containing the
response text, token counts, timestamp, and metadata.

TTL eviction is lazy: any file older than cache_ttl_days is deleted
when the cache is accessed, not on a background timer.

The on-disk entry is validated through :class:`CacheEntry`, a
``FrontmatterModel`` subclass with ``extra="forbid"``: unknown keys
(schema drift) cause the entry to be treated as a miss and dropped.
The ``v`` field is typed as ``int`` rather than ``Literal[1]`` so
existing on-disk caches stay readable across schema bumps
(spec S40 §Risks / watch-outs).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError

from mdd.utils.frontmatter import FrontmatterModel, parse_json_mapping

if TYPE_CHECKING:
    from pathlib import Path

_CACHE_VERSION = 1
_ENTRY_VERSION = 1


def _mdd_version() -> str:
    """Return the installed mdd package version for cache key freshness."""
    try:
        return importlib.metadata.version("mdd")
    except Exception:
        return "dev"


def build_cache_key(
    *,
    model: str,
    task: str,
    messages: list[dict[str, str]],
    cache_key_extra: bytes = b"",
) -> str:
    """Return a hex SHA-256 cache key for the given inputs.

    *messages* should be a list of ``{"role": ..., "content": ...}`` dicts
    in canonical order.  The serialisation is deterministic (sorted keys,
    no whitespace).

    *cache_key_extra* lets callers (e.g. spec S21 rewrite) inject additional
    material (style prompt hash, etc.) into the key without polluting the
    call signature.
    """
    blob = json.dumps(
        {
            "v": _CACHE_VERSION,
            "mdd": _mdd_version(),
            "model": model,
            "task": task,
            "messages": messages,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(blob + cache_key_extra).hexdigest()


class CacheEntry(FrontmatterModel):
    """A single deserialized cache entry (on-disk JSON shape).

    Inherits ``extra="forbid"`` from :class:`FrontmatterModel`: an
    unknown key in the on-disk file means the schema has drifted, and
    the caller will drop the file as a corrupted miss.  The ``v``
    field is validated as ``int`` (not ``Literal[1]``) so old cache
    entries from a previous schema version still decode and are aged
    out by the normal TTL path.
    """

    v: int = _ENTRY_VERSION
    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    timestamp: float = 0.0


def _read_entry(path: Path) -> CacheEntry | None:
    """Read a cache entry from *path*; return ``None`` on any failure or wrong shape.

    No side effects: this never unlinks. Callers decide whether to drop the file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    mapping = parse_json_mapping(text)
    if mapping is None:
        return None
    try:
        return CacheEntry.model_validate(mapping)
    except ValidationError:
        return None


class FileSystemCache:
    """JSON file-per-entry cache stored under *cache_dir*."""

    def __init__(self, cache_dir: Path, ttl_days: int) -> None:
        self._dir = cache_dir
        self._ttl_seconds = ttl_days * 86400

    def _entry_path(self, key: str) -> Path:
        # shard by first 2 chars to avoid huge flat directories
        return self._dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        """Return the cached entry for *key*, or None on miss/expiry."""
        path = self._entry_path(key)
        if not path.exists():
            return None
        entry = _read_entry(path)
        if entry is None:
            path.unlink(missing_ok=True)
            return None
        age = time.time() - entry.timestamp
        if self._ttl_seconds > 0 and age > self._ttl_seconds:
            path.unlink(missing_ok=True)
            return None
        return entry

    def put(
        self,
        key: str,
        *,
        text: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None,
    ) -> None:
        """Write a new entry to the cache."""
        path = self._entry_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = CacheEntry(
            v=_ENTRY_VERSION,
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            timestamp=time.time(),
        )
        # Atomic write: write to .tmp then rename
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            entry.model_dump_json(),
            encoding="utf-8",
        )
        tmp.replace(path)

    def prune(self) -> int:
        """Delete all entries older than TTL.  Returns the count deleted."""
        if not self._dir.exists():
            return 0
        deleted = 0
        now = time.time()
        for json_file in self._dir.rglob("*.json"):
            entry = _read_entry(json_file)
            if entry is None:
                continue
            if self._ttl_seconds > 0 and (now - entry.timestamp) > self._ttl_seconds:
                json_file.unlink(missing_ok=True)
                deleted += 1
        return deleted

    def clear(self) -> int:
        """Delete all cache entries.  Returns the count deleted."""
        if not self._dir.exists():
            return 0
        deleted = 0
        for json_file in self._dir.rglob("*.json"):
            json_file.unlink(missing_ok=True)
            deleted += 1
        return deleted
