"""CLI tests for ``mdd confluence archive-page`` and ``unarchive-page``."""

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


def _write_md(path: Path) -> None:
    path.write_text("---\nconfluence:\n  page_id: '1'\n---\nbody\n", encoding="utf-8")


def _write_cfg(path: Path) -> None:
    path.write_text("url: https://x\nusername: u\napi_token: t\n", encoding="utf-8")


def test_archive_page_calls_orchestrator(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    _write_md(md_path)
    cfg = tmp_path / "confluence.yaml"
    _write_cfg(cfg)

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.archive_page", return_value=0) as mock_ar,
    ):
        rc = _cli_main(["confluence", "archive-page", str(md_path), "--config", str(cfg), "--yes"])

    assert rc == 0
    args, kwargs = mock_ar.call_args
    assert args[0] == md_path
    assert kwargs["opts"].yes is True


def test_unarchive_page_calls_orchestrator(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    _write_md(md_path)
    cfg = tmp_path / "confluence.yaml"
    _write_cfg(cfg)

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.unarchive_page", return_value=0) as mock_un,
    ):
        rc = _cli_main(
            ["confluence", "unarchive-page", str(md_path), "--config", str(cfg), "--yes"]
        )

    assert rc == 0
    args, kwargs = mock_un.call_args
    assert args[0] == md_path
    assert kwargs["opts"].yes is True


def test_archive_page_file_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "no.md"
    cfg = tmp_path / "confluence.yaml"
    _write_cfg(cfg)

    rc = _cli_main(["confluence", "archive-page", str(missing), "--config", str(cfg), "--yes"])

    assert rc == 1
    assert "file not found" in capsys.readouterr().err


def test_unarchive_page_file_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "no.md"
    cfg = tmp_path / "confluence.yaml"
    _write_cfg(cfg)

    rc = _cli_main(["confluence", "unarchive-page", str(missing), "--config", str(cfg), "--yes"])

    assert rc == 1
    assert "file not found" in capsys.readouterr().err


def test_archive_page_config_load_error(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    _write_md(md_path)
    missing_cfg = tmp_path / "nope.yaml"

    rc = _cli_main(
        ["confluence", "archive-page", str(md_path), "--config", str(missing_cfg), "--yes"]
    )

    assert rc == 1


def test_archive_page_dry_run_propagates(tmp_path: Path) -> None:
    md_path = tmp_path / "P.md"
    _write_md(md_path)
    cfg = tmp_path / "confluence.yaml"
    _write_cfg(cfg)

    with (
        patch("mdd.commands.confluence.load_config", return_value=_make_config()),
        patch("mdd.commands.confluence.archive_page", return_value=0) as mock_ar,
    ):
        _ = _cli_main(
            [
                "confluence",
                "archive-page",
                str(md_path),
                "--config",
                str(cfg),
                "--yes",
                "--dry-run",
            ]
        )

    _, kwargs = mock_ar.call_args
    assert kwargs["opts"].dry_run is True
