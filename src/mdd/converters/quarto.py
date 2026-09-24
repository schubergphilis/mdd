"""quarto.py — ReverseConverter implementations using the Quarto CLI.

QuartoDocxRenderer and QuartoPptxRenderer shell out to ``quarto render`` to
produce .docx and .pptx from a Markdown source.  Both are registered in
``REVERSE_CONVERTERS`` so any caller can look them up by target extension.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from mdd.converters.protocol import RenderResult
from mdd.converters.quarto_source import prepare_quarto_source
from mdd.utils.logging import get_logger

log = get_logger(__name__)


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


# Name of the prepared copy of the source inside the render directory.
_SOURCE_NAME = "source.md"

_PROJECT_FILE = "project:\n  type: default\n"

# Environment variables Quarto gets. Everything else in mdd's environment
# (tokens, credentials) stays out of reach of the render.
_ENVIRONMENT_NAMES: frozenset[str] = frozenset({"PATH", "HOME", "TMPDIR", "LANG"})
_ENVIRONMENT_PREFIXES: tuple[str, ...] = ("LC_",)


def _render_environment() -> dict[str, str]:
    """Return the minimal environment ``quarto render`` runs with."""
    return {
        name: value
        for name, value in os.environ.items()
        if name in _ENVIRONMENT_NAMES or name.startswith(_ENVIRONMENT_PREFIXES)
    }


def _copy_attachments(source: Path, render_dir: Path) -> None:
    """Copy the page's attachments directory into *render_dir*, under the same name.

    Only regular files are copied, keeping their layout below *source*.
    Symlinks (to files or directories, including *source* itself) are skipped
    and logged, so the render cannot reach files outside the directory.
    """
    try:
        mode = source.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        log.warning("not copying symlinked attachments directory into the render: %s", source)
        return
    if not stat.S_ISDIR(mode):
        return
    target_root = render_dir / source.name
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(dirpath)
        for name in [*dirnames, *filenames]:
            entry = current / name
            entry_mode = entry.lstat().st_mode
            if stat.S_ISLNK(entry_mode):
                log.warning("not copying symlinked attachment into the render: %s", entry)
            elif stat.S_ISREG(entry_mode):
                target = target_root / entry.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry, target)


def _render(
    md_path: Path,
    *,
    dest: Path,
    to: str,
    reference_doc: Path | None,
) -> RenderResult:
    """Run ``quarto render`` on *md_path* and write the result to *dest*.

    Quarto requires ``--output`` to be a filename (not an absolute path), so
    we write the source into a temporary directory, render there, then move
    the result to *dest*.

    The source is passed through :func:`prepare_quarto_source` first: the
    Markdown was authored by whoever wrote the document or the mirror page,
    so frontmatter is reduced to presentation keys and body constructs that
    make Quarto read files or run code are neutralised. Dropped frontmatter
    keys are logged and reported in ``RenderResult.warnings``.

    The render directory holds only that copy, the page's own
    ``<stem>-attachments/`` directory and a project file that keeps Quarto
    from picking up a ``_quarto.yml`` from a parent directory. mdd's image
    filter replaces every image that points anywhere else (a URL, an absolute
    path, a ``..`` path) with its alt text and reports it on stderr, which
    ends up in ``RenderResult.warnings``. Quarto runs with only ``PATH``,
    ``HOME``, ``TMPDIR``, ``LANG`` and ``LC_*`` from mdd's environment.

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
        # A project file of its own stops Quarto from searching the parent
        # directories of the temp dir for a _quarto.yml to apply.
        (tmp / "_quarto.yml").write_text(_PROJECT_FILE, encoding="utf-8")
        _copy_attachments(md_path.parent / f"{md_path.stem}-attachments", tmp)
        # A fixed .md name: Quarto runs code cells in .qmd sources, never in .md.
        tmp_src = tmp / _SOURCE_NAME
        prepared = prepare_quarto_source(
            md_path.read_text(encoding="utf-8", errors="replace"),
            extra_metadata={"filters": [str(bundled_image_guard())]},
        )
        tmp_src.write_text(prepared.text, encoding="utf-8")
        if prepared.dropped_keys:
            log.warning(
                "%s: ignoring frontmatter keys not used for rendering: %s",
                md_path.name,
                ", ".join(prepared.dropped_keys),
            )

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
            env=_render_environment(),
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
    if prepared.dropped_keys:
        warnings.append(
            f"ignored frontmatter keys not used for rendering: {', '.join(prepared.dropped_keys)}"
        )
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


def bundled_image_guard() -> Path:
    """Return the path to the bundled Lua filter that drops images from outside the render.

    Raises:
        FileNotFoundError: if the bundled filter cannot be located.
    """
    pkg_files: Any = resources.files("mdd")  # pyright: ignore[reportAny]
    filter_ref: Any = pkg_files.joinpath("templates/quarto/image-guard.lua")  # pyright: ignore[reportAny]
    filter_path = Path(str(filter_ref))
    if not filter_path.is_file():
        raise FileNotFoundError(
            f"Bundled image filter not found at {filter_path}. "
            "Re-install mdd to restore bundled templates."
        )
    return filter_path


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
