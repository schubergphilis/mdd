"""CLI tests for ``mdd confluence move-page`` (spec S27 / P06 Phase 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from mdd.cli import main as _cli_main
from mdd.confluence.config import ConfluenceConfig

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        url="https://example.atlassian.net",
        username="u",
        api_token="t",
    )


def test_move_page_calls_orchestrator(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.move_page", return_value=0) as mock_mv,
    ):
        rc = _cli_main(
            [
                "confluence",
                "move-page",
                str(md_path),
                "--parent",
                "99999",
                "--config",
                str(cfg),
                "--yes",
            ]
        )

    assert rc == 0
    args, kwargs = mock_mv.call_args
    assert args[0] == md_path
    assert args[1] == "99999"
    assert kwargs["opts"].yes is True


def test_move_page_requires_parent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md_path = tmp_path / "P.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    try:
        rc = _cli_main(["confluence", "move-page", str(md_path), "--config", str(cfg), "--yes"])
    except SystemExit as exc:
        rc = int(exc.code) if isinstance(exc.code, int) else 2
    err = capsys.readouterr().err
    assert rc != 0
    assert "--parent" in err or "required" in err.lower()


def test_move_page_file_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.md"
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    rc = _cli_main(
        [
            "confluence",
            "move-page",
            str(missing),
            "--parent",
            "1",
            "--config",
            str(cfg),
            "--yes",
        ]
    )

    assert rc == 1
    assert "file not found" in capsys.readouterr().err


def test_move_page_config_load_error(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    missing_cfg = tmp_path / "nope.yaml"

    rc = _cli_main(
        [
            "confluence",
            "move-page",
            str(md_path),
            "--parent",
            "1",
            "--config",
            str(missing_cfg),
            "--yes",
        ]
    )

    assert rc == 1
