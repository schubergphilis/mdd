"""Replace with real tests as you add code."""

import pytest

from mdd import greet


def test_greet_returns_greeting() -> None:
    assert greet("world") == "Hello, world!"


def test_greet_rejects_empty() -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        greet("")
