"""Tests for mdd.mirror.hints — CLI hints that come from the backend (spec S44)."""

from __future__ import annotations

from unittest.mock import patch

from mdd.mirror.hints import clone_hint
from tests.mirror_stub import STUB_GROUP, STUB_HOST, stub_backend


class TestCloneHint:
    def test_uses_the_backends_remote(self) -> None:
        with stub_backend():
            hint = clone_hint("confluence", "SPACE")
        assert hint == f"  git clone https://{STUB_HOST}/{STUB_GROUP}/SPACE.git && cd SPACE"

    def test_falls_back_when_the_backend_has_no_remote(self) -> None:
        """A local-only / plain-git deployment still gets a printable line."""
        with patch("mdd.mirror.hints.default_backend") as backend:
            backend.return_value.resolve_remote.return_value = None
            hint = clone_hint("sharepoint", "SITE")
        assert "no sharepoint mirror remote" in hint
        assert "SITE" in hint

    def test_falls_back_when_no_backend_is_wired(self) -> None:
        with patch("mdd.mirror.hints.default_backend", side_effect=RuntimeError("no default")):
            hint = clone_hint("confluence", "SPACE")
        assert "no confluence mirror remote" in hint
