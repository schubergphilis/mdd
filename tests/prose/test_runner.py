"""Tests for the shared runner: the reflow write gates and CLI-level argument types."""

from __future__ import annotations

import argparse
import datetime as dt
from typing import TYPE_CHECKING

import pytest

from mdd.commands.prose import _iso_date, _positive_int  # pyright: ignore[reportPrivateUsage]
from mdd.prose import runner
from mdd.prose.config import ProseConfig
from mdd.prose.reflow import apply as reflow_apply
from mdd.prose.rules import RULES

if TYPE_CHECKING:
    from pathlib import Path

LONG = (
    "One sentence that is quite long and carries a clause, and then keeps going for "
    "long enough that the reflow has to break it somewhere. A second sentence.\n"
)


def config() -> ProseConfig:
    return ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})


def options(**kwargs: object) -> runner.RunOptions:
    base: dict[str, object] = {"checks": ("reflow",), "as_of": dt.date(2026, 8, 24)}
    return runner.RunOptions(**{**base, **kwargs})  # pyright: ignore[reportArgumentType]


def test_non_equivalent_reflow_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")

    def never_equivalent(before: str, after: str) -> bool:
        return False

    monkeypatch.setattr(reflow_apply, "equivalent", never_equivalent)
    result = runner.run([target], config(), options(write=True))
    assert "not-equivalent" in [f.rule for f in result.findings]
    assert target.read_text(encoding="utf-8") == LONG
    assert result.written == 0


def test_successful_reflow_write_drops_the_fixable_finding(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    result = runner.run([target], config(), options(write=True))
    assert result.findings == []
    assert result.written == 1


def test_reflow_off_reports_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text(LONG, encoding="utf-8")
    from dataclasses import replace

    from mdd.prose.rules import Severity

    cfg = replace(config(), severities={**config().severities, "reflow": Severity.OFF})
    result = runner.run([target], cfg, options(write=True))
    assert result.written == 0
    assert target.read_text(encoding="utf-8") == LONG


def test_iso_date_type_rejects_junk() -> None:
    assert _iso_date("2026-08-24") == dt.date(2026, 8, 24)
    with pytest.raises(argparse.ArgumentTypeError, match="ISO-8601"):
        _ = _iso_date("yesterday")


def test_positive_int_type_rejects_junk() -> None:
    assert _positive_int("7") == 7
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        _ = _positive_int("nope")
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        _ = _positive_int("0")
