"""quarto.py — ReverseConverter implementations using the Quarto CLI.

QuartoDocxRenderer and QuartoPptxRenderer shell out to ``quarto render`` to
produce .docx and .pptx from a Markdown source.  Both are registered in
``REVERSE_CONVERTERS`` so any caller can look them up by target extension.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from mdd.converters.protocol import RenderResult


class QuartoNotFoundError(Exception):
    """Raised when the ``quarto`` binary cannot be found on PATH."""


def _check_quarto() -> str:
    """Return the Quarto version string or raise QuartoNotFoundError."""
    try:
        result = subprocess.run(
            ["quarto", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise QuartoNotFoundError(
            "The 'quarto' CLI was not found on PATH.  "
            "Install Quarto from https://quarto.org/docs/get-started/ "
            "to use the office-publish feature."
        ) from exc
    if result.returncode != 0:
        raise QuartoNotFoundError(
            f"'quarto --version' failed (exit {result.returncode}): {result.stderr[:200]}"
        )
    return result.stdout.strip()


def quarto_version() -> str:
    """Return the currently installed Quarto version string.

    Raises QuartoNotFoundError if Quarto is absent or non-functional.
    """
    return _check_quarto()


def _render(
    md_path: Path,
    *,
    dest: Path,
    to: str,
    reference_doc: Path | None,
) -> RenderResult:
    """Run ``quarto render`` on *md_path* and write the result to *dest*.

    Quarto requires ``--output`` to be a filename (not an absolute path), so
    we copy the source file into a temporary directory, render there, then
    move the result to *dest*.

    Args:
        md_path: Source Markdown file.
        dest: Where to write the output (absolute path).
        to: Target format name, e.g. ``"docx"`` or ``"pptx"``.
        reference_doc: Optional reference template path.

    Returns:
        RenderResult with output_path set to *dest*.

    Raises:
        QuartoNotFoundError: if quarto is not on PATH.
        RuntimeError: if quarto render exits non-zero.
    """
    _check_quarto()

    output_filename = dest.name  # e.g. "My-Page.docx"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Copy source into temp dir so relative references in the .md resolve
        tmp_src = tmp / md_path.name
        shutil.copy2(md_path, tmp_src)

        cmd: list[str] = [
            "quarto",
            "render",
            tmp_src.name,
            "--to",
            to,
            "--output",
            output_filename,
        ]
        if reference_doc is not None:
            cmd += [f"--reference-doc={reference_doc}"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmpdir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"quarto render failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout[:500]}\n"
                f"stderr: {result.stderr[:500]}"
            )

        rendered = tmp / output_filename
        if not rendered.exists():
            raise RuntimeError(
                f"quarto render succeeded but output {output_filename!r} not found in {tmpdir}"
            )
        shutil.move(str(rendered), str(dest))

    warnings: list[str] = []
    if result.stderr:
        for line in result.stderr.splitlines():
            stripped = line.strip()
            if stripped:
                warnings.append(stripped)

    return RenderResult(output_path=dest, warnings=warnings)


class QuartoDocxRenderer:
    """ReverseConverter: Markdown → .docx via Quarto.

    Registered in REVERSE_CONVERTERS[".docx"] by the converters package.
    """

    target_extension: str = ".docx"

    def render(
        self,
        md_path: Path,
        *,
        dest: Path,
        reference_doc: Path | None = None,
    ) -> RenderResult:
        """Render *md_path* to *dest* (.docx) via ``quarto render``."""
        return _render(md_path, dest=dest, to="docx", reference_doc=reference_doc)


class QuartoPptxRenderer:
    """ReverseConverter: Markdown → .pptx via Quarto.

    Registered in REVERSE_CONVERTERS[".pptx"] by the converters package.
    """

    target_extension: str = ".pptx"

    def render(
        self,
        md_path: Path,
        *,
        dest: Path,
        reference_doc: Path | None = None,
    ) -> RenderResult:
        """Render *md_path* to *dest* (.pptx) via ``quarto render``."""
        return _render(md_path, dest=dest, to="pptx", reference_doc=reference_doc)


def bundled_reference_doc(extension: str) -> Path:
    """Return the path to the bundled reference template for *extension*.

    *extension* should be ``.docx`` or ``.pptx`` (with leading dot).

    Raises:
        FileNotFoundError: if the bundled template cannot be located.
    """
    ext = extension.lstrip(".").lower()
    pkg_files: Any = resources.files("mdd")  # pyright: ignore[reportAny]
    template_ref: Any = pkg_files.joinpath(f"templates/quarto/reference.{ext}")  # pyright: ignore[reportAny]
    # importlib.resources path — convert to a real filesystem Path
    template_path = Path(str(template_ref))
    if not template_path.exists():
        raise FileNotFoundError(
            f"Bundled reference template for {extension!r} not found at {template_path}. "
            "Re-install mdd to restore bundled templates."
        )
    return template_path
