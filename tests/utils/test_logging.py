"""Tests for mdd.utils.logging."""

from __future__ import annotations

import io
import logging

import pytest

from mdd.utils.logging import TRACE, configure, get_logger


class TestTraceLevel:
    def test_trace_level_is_below_debug(self) -> None:
        assert TRACE < logging.DEBUG

    def test_trace_method_attached_to_logger(self) -> None:
        log = get_logger("mdd.test")
        assert hasattr(log, "trace")

    def test_trace_emits_when_level_low_enough(self) -> None:
        buf = io.StringIO()
        configure(level="TRACE", stream=buf)
        log = get_logger("mdd.test")
        log.trace("hello %s", "world")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert "hello world" in buf.getvalue()
        assert "TRACE" in buf.getvalue()


class TestConfigure:
    def test_configure_is_idempotent(self) -> None:
        # Calling configure() twice should not stack handlers.
        configure(level="INFO")
        root = logging.getLogger("mdd")
        n_stream = sum(
            1
            for h in root.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
        )
        configure(level="DEBUG")
        n_stream2 = sum(
            1
            for h in root.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
        )
        assert n_stream == n_stream2 == 1

    def test_unknown_level_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown log level"):
            configure(level="WHATEVER")

    def test_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MDD_LOG_LEVEL", "INFO")
        log = configure(level=None)
        assert log.level == logging.INFO


class TestGetLogger:
    def test_returns_namespaced_logger(self) -> None:
        log = get_logger("client")
        assert log.name == "mdd.client"

    def test_passes_through_dotted_mdd_name(self) -> None:
        log = get_logger("mdd.confluence.client")
        assert log.name == "mdd.confluence.client"
