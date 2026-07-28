"""Tests for mdd.search.color."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from mdd.search.color import Color

if TYPE_CHECKING:
    import pytest


class TestColorDetect:
    def test_always_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert Color.detect("always").enabled is True

    def test_never_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert Color.detect("never").enabled is False

    def test_no_color_env_wins_over_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert Color.detect("auto").enabled is False

    def test_no_color_env_wins_over_force_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert Color.detect("auto").enabled is False

    def test_force_color_env_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert Color.detect("auto").enabled is True

    def test_auto_with_non_tty_stream_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        # StringIO returns False for isatty
        assert Color.detect("auto", stream=io.StringIO()).enabled is False


class TestColorWrappers:
    def test_disabled_passes_through(self) -> None:
        c = Color(enabled=False)
        assert c.match("foo") == "foo"
        assert c.path("foo") == "foo"
        assert c.line_number("L42") == "L42"
        assert c.meta("foo") == "foo"

    def test_enabled_wraps_with_ansi(self) -> None:
        c = Color(enabled=True)
        assert c.match("foo").startswith("\x1b[")
        assert c.match("foo").endswith("\x1b[0m")
        assert "foo" in c.match("foo")
