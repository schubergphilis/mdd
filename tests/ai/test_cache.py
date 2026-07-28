"""Tests for mdd.ai.cache — filesystem cache (spec S20)."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.ai.cache import CacheEntry, FileSystemCache, build_cache_key

if TYPE_CHECKING:
    from pathlib import Path


class TestBuildCacheKey:
    def test_deterministic(self) -> None:
        key1 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        key2 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert key1 == key2

    def test_differs_on_model_change(self) -> None:
        key1 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        key2 = build_cache_key(
            model="gpt-4o-mini",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert key1 != key2

    def test_differs_on_task_change(self) -> None:
        key1 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        key2 = build_cache_key(
            model="gpt-4o",
            task="summarise",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert key1 != key2

    def test_differs_on_content_change(self) -> None:
        key1 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        key2 = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "world"}],
        )
        assert key1 != key2

    def test_extra_bytes_change_key(self) -> None:
        base_key = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
        )
        extra_key = build_cache_key(
            model="gpt-4o",
            task="default",
            messages=[{"role": "user", "content": "hello"}],
            cache_key_extra=b"style-hash-abc123",
        )
        assert base_key != extra_key

    def test_hex_string(self) -> None:
        key = build_cache_key(
            model="m",
            task="t",
            messages=[],
        )
        assert len(key) == 64
        int(key, 16)  # should not raise


class TestFileSystemCache:
    def test_miss_on_empty_cache(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        assert cache.get("nonexistent-key") is None

    def test_hit_after_put(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "a" * 64
        cache.put(
            key,
            text="hello world",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.001,
        )
        entry = cache.get(key)
        assert entry is not None
        assert entry.text == "hello world"
        assert entry.prompt_tokens == 10
        assert entry.completion_tokens == 5
        assert entry.cost_usd is not None
        assert abs(entry.cost_usd - 0.001) < 1e-9

    def test_hit_with_none_cost(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "b" * 64
        cache.put(key, text="t", prompt_tokens=1, completion_tokens=1, cost_usd=None)
        entry = cache.get(key)
        assert entry is not None
        assert entry.cost_usd is None

    def test_ttl_eviction(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=1)
        key = "c" * 64
        cache.put(key, text="stale", prompt_tokens=1, completion_tokens=1, cost_usd=None)

        # Mock time to be 2 days in the future
        future = time.time() + 2 * 86400
        with patch("mdd.ai.cache.time") as mock_time:
            mock_time.time.return_value = future
            result = cache.get(key)

        assert result is None
        # File should be deleted
        assert not (tmp_path / "cache" / key[:2] / f"{key}.json").exists()

    def test_ttl_zero_never_expires(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=0)
        key = "d" * 64
        cache.put(key, text="forever", prompt_tokens=1, completion_tokens=1, cost_usd=None)

        future = time.time() + 999 * 86400
        with patch("mdd.ai.cache.time") as mock_time:
            mock_time.time.return_value = future
            result = cache.get(key)

        assert result is not None
        assert result.text == "forever"

    def test_sharded_directory_structure(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "abcdef" + "0" * 58
        cache.put(key, text="t", prompt_tokens=0, completion_tokens=0, cost_usd=None)
        expected = tmp_path / "cache" / "ab" / f"{key}.json"
        assert expected.exists()

    def test_prune_removes_expired(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=1)
        for i in range(3):
            key = str(i) * 64
            cache.put(key, text="x", prompt_tokens=0, completion_tokens=0, cost_usd=None)

        future = time.time() + 2 * 86400
        with patch("mdd.ai.cache.time") as mock_time:
            mock_time.time.return_value = future
            deleted = cache.prune()

        assert deleted == 3

    def test_clear_removes_all(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        for i in range(5):
            key = str(i) * 64
            cache.put(key, text="x", prompt_tokens=0, completion_tokens=0, cost_usd=None)

        deleted = cache.clear()
        assert deleted == 5

    def test_clear_on_empty_dir(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        assert cache.clear() == 0

    def test_corrupted_entry_treated_as_miss(self, tmp_path: Path) -> None:
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "e" * 64
        path = tmp_path / "cache" / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json", encoding="utf-8")
        assert cache.get(key) is None

    def test_put_is_atomic(self, tmp_path: Path) -> None:
        """put() should not leave .tmp files behind."""
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "f" * 64
        cache.put(key, text="t", prompt_tokens=0, completion_tokens=0, cost_usd=None)
        tmp_files = list((tmp_path / "cache").rglob("*.tmp"))
        assert len(tmp_files) == 0

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        """An on-disk entry with an unknown field is dropped (schema drift)."""
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "9" * 64
        path = tmp_path / "cache" / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Inject an extra key not present in the CacheEntry model.
        payload = {
            "v": 1,
            "text": "hi",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cost_usd": None,
            "timestamp": time.time(),
            "unexpected_future_field": "future-schema",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert cache.get(key) is None
        # The corrupted file is unlinked on miss.
        assert not path.exists()

    def test_legacy_v_field_drift_accepted(self, tmp_path: Path) -> None:
        """A bumped ``v`` value still parses — `v: int`, not `Literal[1]`."""
        cache = FileSystemCache(tmp_path / "cache", ttl_days=30)
        key = "8" * 64
        path = tmp_path / "cache" / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "v": 2,  # future schema version
            "text": "legacy",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cost_usd": None,
            "timestamp": time.time(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        entry = cache.get(key)
        assert entry is not None
        assert entry.text == "legacy"
        assert entry.v == 2


class TestCacheEntry:
    def test_round_trip(self) -> None:
        entry = CacheEntry.model_validate(
            {
                "v": 1,
                "text": "hello",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "cost_usd": 0.001,
                "timestamp": 1234.5,
            }
        )
        assert entry.text == "hello"
        assert entry.prompt_tokens == 10
        assert entry.cost_usd == 0.001
        assert entry.timestamp == 1234.5

    def test_unknown_key_raises(self) -> None:
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ = CacheEntry.model_validate(
                {
                    "v": 1,
                    "text": "x",
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": None,
                    "timestamp": 0.0,
                    "typo_field": "boom",
                }
            )

    def test_flexible_int_coercion(self) -> None:
        # pydantic v2 lax mode: a JSON string `"5"` decodes into int.
        entry = CacheEntry.model_validate(
            {
                "v": "1",
                "text": "x",
                "prompt_tokens": "10",
                "completion_tokens": "5",
                "cost_usd": None,
                "timestamp": 0.0,
            }
        )
        assert entry.v == 1
        assert entry.prompt_tokens == 10
        assert entry.completion_tokens == 5
