"""Tests for mdd.converters.quarto."""

from __future__ import annotations

import base64
import shutil
import zipfile
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from mdd.converters.quarto import (
    QuartoDocxRenderer,
    QuartoNotFoundError,
    QuartoPptxRenderer,
    bundled_image_guard,
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

    def test_render_hands_quarto_a_prepared_copy(self, tmp_path: Path) -> None:
        """Quarto sees an allow-listed frontmatter and a neutralised body, not the file itself."""
        md = tmp_path / "page.md"
        md.write_text(
            "---\ntitle: T\nfilters: [/tmp/evil.lua]\n---\n"
            "Intro\n\n---\nfilters: [/tmp/evil.lua]\n---\n\n{{< include /etc/passwd >}}\n",
            encoding="utf-8",
        )
        dest = tmp_path / "page.docx"
        seen: dict[str, str] = {}

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stdout = "1.6.0"
            r.stderr = ""
            if "--version" in cmd:
                return r
            cwd = str(kw["cwd"])
            seen["source"] = Path(cwd, cmd[2]).read_text(encoding="utf-8")
            Path(cwd, cmd[cmd.index("--output") + 1]).write_bytes(b"fake-docx")
            return r

        with patch("subprocess.run", side_effect=fake_run):
            result = QuartoDocxRenderer().render(md, dest=dest)

        assert seen["source"] == (
            f"---\ntitle: T\nfilters:\n- {bundled_image_guard()}\n---\n"
            "Intro\n\n***\nfilters: [/tmp/evil.lua]\n---\n\n"
            "{{{< include /etc/passwd >}}}\n"
        )
        assert result.warnings == ["ignored frontmatter keys not used for rendering: filters"]
        # the mirror file itself is untouched
        assert "filters: [/tmp/evil.lua]" in md.read_text(encoding="utf-8")

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
# What the render directory and the Quarto process get
# ---------------------------------------------------------------------------


class _RenderSpy:
    """Fake ``subprocess.run`` that records the render call and the render directory."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.symlinks: list[str] = []
        self.cmd: list[str] = []
        self.env: dict[str, str] | None = None

    def __call__(self, cmd: list[str], **kw: object) -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = "1.6.0"
        r.stderr = ""
        if "--version" in cmd:
            return r
        cwd = Path(str(kw["cwd"]))
        self.cmd = list(cmd)
        self.env = cast("dict[str, str] | None", kw.get("env"))
        for path in sorted(cwd.rglob("*")):
            rel = path.relative_to(cwd).as_posix()
            if path.is_symlink():
                self.symlinks.append(rel)
            elif path.is_file():
                self.files[rel] = path.read_bytes()
        Path(cwd, cmd[cmd.index("--output") + 1]).write_bytes(b"fake-docx")
        return r


def _spy_render(md: Path) -> _RenderSpy:
    spy = _RenderSpy()
    with patch("subprocess.run", side_effect=spy):
        QuartoDocxRenderer().render(md, dest=md.parent / "out.docx")
    return spy


class TestRenderDirectory:
    def test_source_is_renamed_and_project_file_written(self, tmp_path: Path) -> None:
        md = tmp_path / "notes.qmd.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        assert spy.cmd[2] == "source.md"
        assert spy.cmd[spy.cmd.index("--output") + 1] == "out.docx"
        assert spy.files["_quarto.yml"] == b"project:\n  type: default\n"
        assert set(spy.files) == {"_quarto.yml", "source.md"}

    def test_image_filter_is_injected(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        guard = bundled_image_guard()
        assert guard.name == "image-guard.lua"
        assert spy.files["source.md"].decode() == f"---\nfilters:\n- {guard}\n---\n# Hello\n"

    def test_page_attachments_are_copied(self, tmp_path: Path) -> None:
        md = tmp_path / "Doc.docx.md"
        md.write_text("![x](Doc.docx-attachments/image1.png)\n", encoding="utf-8")
        attachments = tmp_path / "Doc.docx-attachments"
        (attachments / "sub").mkdir(parents=True)
        (attachments / "image1.png").write_bytes(b"one")
        (attachments / "sub" / "image2.png").write_bytes(b"two")
        (tmp_path / "other-attachments").mkdir()
        (tmp_path / "other-attachments" / "x.png").write_bytes(b"other")
        (tmp_path / "sibling.png").write_bytes(b"sibling")

        spy = _spy_render(md)

        assert spy.files["Doc.docx-attachments/image1.png"] == b"one"
        assert spy.files["Doc.docx-attachments/sub/image2.png"] == b"two"
        assert set(spy.files) == {
            "_quarto.yml",
            "source.md",
            "Doc.docx-attachments/image1.png",
            "Doc.docx-attachments/sub/image2.png",
        }

    def test_symlinked_attachments_are_not_copied(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(b"secret")
        mirror = tmp_path / "mirror"
        attachments = mirror / "page-attachments"
        attachments.mkdir(parents=True)
        (attachments / "ok.png").write_bytes(b"ok")
        (attachments / "file-link.png").symlink_to(outside / "secret.png")
        (attachments / "dir-link").symlink_to(outside, target_is_directory=True)
        md = mirror / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        assert set(spy.files) == {"_quarto.yml", "source.md", "page-attachments/ok.png"}
        assert spy.symlinks == []

    def test_symlinked_attachments_directory_is_not_copied(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(b"secret")
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        (mirror / "page-attachments").symlink_to(outside, target_is_directory=True)
        md = mirror / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        assert set(spy.files) == {"_quarto.yml", "source.md"}

    def test_attachments_path_that_is_a_file_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "page-attachments").write_bytes(b"not a directory")
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        assert set(spy.files) == {"_quarto.yml", "source.md"}

    def test_quarto_runs_with_a_minimal_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/someone")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("API_TOKEN", "value")
        monkeypatch.setenv("QUARTO_PYTHON", "/usr/bin/python3")
        md = tmp_path / "page.md"
        md.write_text("# Hello\n", encoding="utf-8")

        spy = _spy_render(md)

        assert spy.env is not None
        assert {k: spy.env[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")} == {
            "PATH": "/usr/bin",
            "HOME": "/home/someone",
            "TMPDIR": str(tmp_path),
            "LANG": "en_US.UTF-8",
            "LC_ALL": "C",
        }
        assert all(k in {"PATH", "HOME", "TMPDIR", "LANG"} or k.startswith("LC_") for k in spy.env)

    def test_missing_image_filter_is_reported(self, tmp_path: Path) -> None:
        with (
            patch("mdd.converters.quarto.resources.files", return_value=tmp_path),
            pytest.raises(FileNotFoundError, match="image filter"),
        ):
            bundled_image_guard()


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


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _package_bytes(path: Path) -> bytes:
    with zipfile.ZipFile(path) as package:
        return b"".join(package.read(name) for name in package.namelist())


@pytest.mark.skipif(shutil.which("quarto") is None, reason="quarto not installed")
class TestQuartoImageGuardEndToEnd:
    """Real renders: only images from the page's own attachments are embedded."""

    @pytest.fixture
    def outside(self, tmp_path: Path) -> Path:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(_PNG + b"OUTSIDEMARKER")
        (outside / "secret.txt").write_bytes(b"OUTSIDEMARKER")
        return outside

    @pytest.mark.parametrize("to", ["docx", "pptx"])
    def test_outside_images_become_alt_text(self, tmp_path: Path, outside: Path, to: str) -> None:
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        up = "../" * 12
        targets = [
            f"{outside}/secret.png",
            f"{up}{outside}/secret.png",
            f"{up}{outside}/secret.txt".replace("/", "%2F"),
            f"file://{outside}/secret.png",
            "http://127.0.0.1:9/secret.png",
            "//127.0.0.1:9/secret.png",
        ]
        body = "# T\n\n## S\n\n" + "".join(f"![alt{i}]({t})\n\n" for i, t in enumerate(targets))
        body += f'## B {{background-image="{up}{outside}/secret.png"}}\n\ntext\n'
        md = mirror / "page.md"
        md.write_text(body, encoding="utf-8")
        dest = tmp_path / f"page.{to}"

        result = (QuartoDocxRenderer() if to == "docx" else QuartoPptxRenderer()).render(
            md, dest=dest
        )

        assert b"OUTSIDEMARKER" not in _package_bytes(dest)
        dropped = [w for w in result.warnings if "dropped image" in w]
        assert len(dropped) == len(targets) + 1
        assert b"alt0" in _package_bytes(dest)

    def test_attachment_images_are_embedded(self, tmp_path: Path, outside: Path) -> None:
        mirror = tmp_path / "mirror"
        attachments = mirror / "Doc.docx-attachments"
        attachments.mkdir(parents=True)
        (attachments / "image1.png").write_bytes(_PNG + b"ATTACHMENTMARKER")
        (attachments / "linked.png").symlink_to(outside / "secret.png")
        md = mirror / "Doc.docx.md"
        md.write_text(
            "# T\n\n![one](Doc.docx-attachments/image1.png)\n\n"
            "![two](Doc.docx-attachments/linked.png)\n\n"
            "::: {.callout-note}\nnote\n:::\n",
            encoding="utf-8",
        )
        dest = tmp_path / "Doc.docx"

        QuartoDocxRenderer().render(md, dest=dest)

        content = _package_bytes(dest)
        assert b"ATTACHMENTMARKER" in content
        assert b"OUTSIDEMARKER" not in content
        with zipfile.ZipFile(dest) as package:
            media = [n for n in package.namelist() if n.startswith("word/media/")]
        assert len(media) == 2  # the attachment and the callout icon

    def test_parent_project_file_is_not_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "root"
        (root / "tmp").mkdir(parents=True)
        (root / "_quarto.yml").write_text("format:\n  docx:\n    title: PLANTEDTITLE\n")
        monkeypatch.setattr("tempfile.tempdir", str(root / "tmp"))
        md = tmp_path / "page.md"
        md.write_text("# T\n\npara\n", encoding="utf-8")
        dest = tmp_path / "page.docx"

        QuartoDocxRenderer().render(md, dest=dest)

        assert b"PLANTEDTITLE" not in _package_bytes(dest)
