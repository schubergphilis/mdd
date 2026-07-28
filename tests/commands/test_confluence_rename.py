"""CLI tests for ``mdd confluence rename-page`` (spec S27 / P06 Phase 4)."""

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
        username="u@example.com",
        api_token="t",
    )


def test_rename_page_calls_orchestrator(tmp_path: Path) -> None:
    md_path = tmp_path / "Page.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://example.atlassian.net\nusername: u\napi_token: t\n")

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.rename_page", return_value=0) as mock_rn,
    ):
        rc = _cli_main(
            [
                "confluence",
                "rename-page",
                str(md_path),
                "New Title",
                "--config",
                str(cfg),
                "--yes",
            ]
        )

    assert rc == 0
    mock_rn.assert_called_once()
    args, kwargs = mock_rn.call_args
    assert args[0] == md_path
    assert args[1] == "New Title"
    opts = kwargs["opts"]
    assert opts.yes is True
    assert opts.dry_run is False
    assert opts.no_commit is False


def test_rename_page_file_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.md"
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    rc = _cli_main(
        ["confluence", "rename-page", str(missing), "Title", "--config", str(cfg), "--yes"]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "file not found" in err


def test_rename_page_config_load_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    md_path = tmp_path / "Page.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    missing_cfg = tmp_path / "nope.yaml"

    rc = _cli_main(
        [
            "confluence",
            "rename-page",
            str(md_path),
            "Title",
            "--config",
            str(missing_cfg),
            "--yes",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "ERROR" in err or "Error" in err


def test_rename_page_dry_run_flag_propagates(tmp_path: Path) -> None:
    md_path = tmp_path / "Page.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.rename_page", return_value=0) as mock_rn,
    ):
        rc = _cli_main(
            [
                "confluence",
                "rename-page",
                str(md_path),
                "New Title",
                "--config",
                str(cfg),
                "--yes",
                "--dry-run",
            ]
        )

    assert rc == 0
    _, kwargs = mock_rn.call_args
    assert kwargs["opts"].dry_run is True


def test_rename_page_no_commit_flag_propagates(tmp_path: Path) -> None:
    md_path = tmp_path / "Page.md"
    md_path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")
    cfg = tmp_path / "confluence.yaml"
    cfg.write_text("url: https://x\nusername: u\napi_token: t\n")

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.rename_page", return_value=0) as mock_rn,
    ):
        _ = _cli_main(
            [
                "confluence",
                "rename-page",
                str(md_path),
                "T",
                "--config",
                str(cfg),
                "--yes",
                "--no-commit",
            ]
        )

    _, kwargs = mock_rn.call_args
    assert kwargs["opts"].no_commit is True
