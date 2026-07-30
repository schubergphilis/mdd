"""Tests for mdd.converters.quarto."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mdd.converters.quarto import (
    QuartoDocxRenderer,
    QuartoNotFoundError,
    QuartoPptxRenderer,
    bundled_reference_doc,
    quarto_version,
)

# ---------------------------------------------------------------------------
# quarto_version()
# ---------------------------------------------------------------------------


class TestQuartoVersion:
    def test_returns_version_string_when_quarto_present(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1.6.0\n"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ver = quarto_version()
        assert ver == "1.6.0"
        mock_run.assert_called_once_with(
            ["quarto", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_raises_when_quarto_missing(self) -> None:
        with (
            patch("subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(QuartoNotFoundError, match="quarto.*CLI"),  # noqa: RUF043
        ):
            quarto_version()

    def test_raises_when_quarto_exits_nonzero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"
        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(QuartoNotFoundError, match="failed"),
        ):
            quarto_version()


# ---------------------------------------------------------------------------
# QuartoDocxRenderer
# ---------------------------------------------------------------------------


class TestQuartoDocxRenderer:
    def test_target_extension(self) -> None:
        r = QuartoDocxRenderer()
        assert r.target_extension == ".docx"

    def test_render_calls_quarto_with_docx(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")
        dest = tmp_path / "page.docx"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        # Simulate quarto creating the output file in the render cwd
        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            if cmd[0] == "quarto" and "--version" in cmd:
                r = MagicMock()
                r.returncode = 0
                r.stdout = "1.6.0"
                return r
            # _render uses cwd=tmpdir; write the output there
            cwd = kw.get("cwd") or str(tmp_path)
            out_name = cmd[cmd.index("--output") + 1]
            Path(str(cwd), out_name).write_bytes(b"fake-docx")
            return mock_result

        with patch("subprocess.run", side_effect=fake_run):
            result = QuartoDocxRenderer().render(md, dest=dest)

        assert result.output_path == dest

    def test_render_raises_on_nonzero_exit(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")
        dest = tmp_path / "page.docx"

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            if "--version" in cmd:
                r.returncode = 0
                r.stdout = "1.6.0"
                r.stderr = ""
            else:
                r.returncode = 1
                r.stdout = "quarto output"
                r.stderr = "render failed"
            return r

        with (
            patch("subprocess.run", side_effect=fake_run),
            pytest.raises(RuntimeError, match="quarto render failed"),
        ):
            QuartoDocxRenderer().render(md, dest=dest)

    def test_render_passes_reference_doc(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")
        dest = tmp_path / "page.docx"
        ref = tmp_path / "ref.docx"
        ref.write_bytes(b"ref")

        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            r = MagicMock()
            r.returncode = 0
            r.stdout = "1.6.0" if "--version" in cmd else ""
            r.stderr = ""
            if "--version" not in cmd and "--output" in cmd:
                cwd = kw.get("cwd") or str(tmp_path)
                out_name = cmd[cmd.index("--output") + 1]
                Path(str(cwd), out_name).write_bytes(b"fake")
            return r

        with patch("subprocess.run", side_effect=fake_run):
            QuartoDocxRenderer().render(md, dest=dest, reference_doc=ref)

        render_cmd = [c for c in calls if "render" in c]
        assert render_cmd, "expected a render command"
        assert f"--reference-doc={ref}" in render_cmd[0]

    def test_render_raises_when_quarto_absent(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")
        dest = tmp_path / "page.docx"

        with (
            patch("subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(QuartoNotFoundError),
        ):
            QuartoDocxRenderer().render(md, dest=dest)


# ---------------------------------------------------------------------------
# QuartoPptxRenderer
# ---------------------------------------------------------------------------


class TestQuartoPptxRenderer:
    def test_target_extension(self) -> None:
        r = QuartoPptxRenderer()
        assert r.target_extension == ".pptx"

    def test_render_uses_pptx_format(self, tmp_path: Path) -> None:
        md = tmp_path / "slides.md"
        md.write_text("# Slide\n", encoding="utf-8")
        dest = tmp_path / "slides.pptx"

        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            calls.append(list(cmd))
            r = MagicMock()
            r.returncode = 0
            r.stdout = "1.6.0" if "--version" in cmd else ""
            r.stderr = ""
            if "--version" not in cmd and "--output" in cmd:
                cwd = kw.get("cwd") or str(tmp_path)
                out_name = cmd[cmd.index("--output") + 1]
                Path(str(cwd), out_name).write_bytes(b"fake")
            return r

        with patch("subprocess.run", side_effect=fake_run):
            QuartoPptxRenderer().render(md, dest=dest)

        render_cmd = [c for c in calls if "render" in c]
        assert render_cmd
        assert "pptx" in render_cmd[0]


# ---------------------------------------------------------------------------
# bundled_reference_doc()
# ---------------------------------------------------------------------------


class TestBundledReferenceDoc:
    def test_returns_path_for_docx(self) -> None:
        path = bundled_reference_doc(".docx")
        assert path.exists()
        assert path.name == "reference.docx"

    def test_returns_path_for_pptx(self) -> None:
        path = bundled_reference_doc(".pptx")
        assert path.exists()
        assert path.name == "reference.pptx"

    def test_leading_dot_optional(self) -> None:
        path = bundled_reference_doc("docx")
        assert path.name == "reference.docx"

    def test_raises_for_unknown_extension(self) -> None:
        with pytest.raises(FileNotFoundError):
            bundled_reference_doc(".xyz")


# ---------------------------------------------------------------------------
# REVERSE_CONVERTERS registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_docx_registered(self) -> None:
        from mdd.converters import REVERSE_CONVERTERS

        assert ".docx" in REVERSE_CONVERTERS

    def test_pptx_registered(self) -> None:
        from mdd.converters import REVERSE_CONVERTERS

        assert ".pptx" in REVERSE_CONVERTERS

    def test_reverse_for_docx(self) -> None:
        from mdd.converters import reverse_for

        r = reverse_for(".docx")
        assert r is not None
        assert isinstance(r, QuartoDocxRenderer)

    def test_reverse_for_pptx(self) -> None:
        from mdd.converters import reverse_for

        r = reverse_for(".pptx")
        assert r is not None
        assert isinstance(r, QuartoPptxRenderer)


# ---------------------------------------------------------------------------
# End-to-end: actual Quarto render (requires quarto on PATH)
# ---------------------------------------------------------------------------


class TestQuartoEndToEnd:
    def test_render_docx(self, tmp_path: Path) -> None:
        md = tmp_path / "hello.md"
        md.write_text(
            "---\ntitle: Test\n---\n\n# Hello World\n\nThis is a test.\n",
            encoding="utf-8",
        )
        dest = tmp_path / "hello.docx"
        result = QuartoDocxRenderer().render(md, dest=dest)
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 0
