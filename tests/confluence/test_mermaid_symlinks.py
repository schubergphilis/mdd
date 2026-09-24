"""Mermaid rendering never reads or writes through a symlink in the attachments directory."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mdd.confluence.mermaid import render_mermaid_fences
from mdd.converters.models import MermaidConfig

_WHICH = "mdd.confluence.mermaid.shutil.which"
_RUN = "mdd.confluence.mermaid.subprocess.run"
_MMDC = MermaidConfig(renderer="mmdc")
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
_FENCE = "```mermaid\ngraph TD\n  A --> B\n```"


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


def _fake_run_ok(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
    out = Path(argv[argv.index("-o") + 1])
    out.write_bytes(_SVG)
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class TestMermaidRefusesSymlinks:
    def test_symlinked_attachments_dir_leaves_fence(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        md_path = tmp_path / "page.md"
        md_path.write_text("# Page\n", encoding="utf-8")
        _plant_symlink(tmp_path / "page-attachments", outside)

        with (
            patch(_WHICH, return_value="/usr/local/bin/mmdc"),
            patch(_RUN, side_effect=_fake_run_ok) as run,
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE}\n", md_path, config=_MMDC)

        assert out == f"{_FENCE}\n"
        run.assert_not_called()
        assert list(outside.iterdir()) == []
        assert any("symlink" in r.getMessage() for r in caplog.records)

    def test_symlinked_svg_is_not_a_cache_hit(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = tmp_path / "secret.svg"
        secret.write_bytes(b"<svg/>")
        md_path = tmp_path / "page.md"
        md_path.write_text("# Page\n", encoding="utf-8")
        att = tmp_path / "page-attachments"
        att.mkdir()
        sha = hashlib.sha256(b"graph TD\n  A --> B").hexdigest()[:12]
        _plant_symlink(att / f"mermaid-{sha}.svg", secret)

        with (
            patch(_WHICH, return_value="/usr/local/bin/mmdc"),
            patch(_RUN, side_effect=_fake_run_ok) as run,
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE}\n", md_path, config=_MMDC)

        assert out == f"{_FENCE}\n"
        run.assert_not_called()
        assert (att / f"mermaid-{sha}.svg").is_symlink()
        assert secret.read_bytes() == b"<svg/>"
