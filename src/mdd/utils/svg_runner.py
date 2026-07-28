"""svg_runner.py — subprocess wrappers for SVG rasterization backends.

Each backend implements the SvgRenderer protocol:
    name     — the renderer identifier string
    version  — version string detected at runtime
    render() — invoke the backend to produce a PNG

Supported backends:
    rsvg-convert  (librsvg, default)
    cairosvg      (Python package, pure-Python option)
    resvg         (Rust-based rasterizer)
    inkscape      (Inkscape headless)

Usage:
    renderer = get_renderer("rsvg-convert")
    renderer.render(src, dest_tmp, scale=2.0, bg="transparent")

On first use each renderer probes the version; missing binaries raise
RendererUnavailableError with an actionable install hint.
"""

import subprocess
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class RendererUnavailableError(RuntimeError):
    """Raised when the configured SVG renderer is not found on PATH."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SvgRenderer(Protocol):
    """Protocol for SVG-to-PNG rasterization backends."""

    name: str
    """Renderer identifier, e.g. "rsvg-convert"."""

    @property
    def version(self) -> str:
        """Version string detected at runtime."""
        ...

    def render(self, src: Path, dest: Path, *, scale: float, bg: str) -> None:
        """Rasterize *src* SVG to *dest* PNG.

        Args:
            src:   Path to the source .svg file.
            dest:  Path for the output .png file (parent must exist).
            scale: Linear scale factor applied to the SVG's nominal dimensions.
            bg:    Background colour: "white" or "transparent".

        Raises:
            RendererUnavailableError: Binary not found on PATH.
            subprocess.CalledProcessError: Renderer exited non-zero.
        """
        ...


# ---------------------------------------------------------------------------
# rsvg-convert (librsvg)
# ---------------------------------------------------------------------------


class RsvgRenderer:
    """rsvg-convert backend (librsvg)."""

    name: str = "rsvg-convert"

    _version_cache: str | None = None

    @property
    def version(self) -> str:
        if self._version_cache is None:
            self._version_cache = _probe_version(
                self.name,
                ["rsvg-convert", "--version"],
                install_hint=(
                    "Install librsvg:\n"
                    "  macOS: brew install librsvg\n"
                    "  Debian/Ubuntu: sudo apt install librsvg2-bin"
                ),
            )
        return self._version_cache

    def render(self, src: Path, dest: Path, *, scale: float, bg: str) -> None:
        # Ensure version probe runs (raises if missing)
        _ = self.version
        bg_arg = "white" if bg == "white" else "transparent"
        subprocess.run(
            [
                "rsvg-convert",
                "-z",
                str(scale),
                "--background-color",
                bg_arg,
                "-o",
                str(dest),
                str(src),
            ],
            check=True,
        )


# ---------------------------------------------------------------------------
# cairosvg (Python package)
# ---------------------------------------------------------------------------


class CairoSvgRenderer:
    """cairosvg Python-package backend."""

    name: str = "cairosvg"

    _version_cache: str | None = None

    @property
    def version(self) -> str:
        if self._version_cache is None:
            try:
                # Lazy import (PLC0415): cairosvg is an optional dep that
                # may not be installed; the try/except below handles that.
                import cairosvg  # pyright: ignore[reportMissingImports,reportMissingModuleSource]  # noqa: PLC0415

                self._version_cache = str(
                    getattr(cairosvg, "__version__", "unknown")  # pyright: ignore[reportAny]
                )
            except ImportError as exc:
                raise RendererUnavailableError(
                    "cairosvg is not installed.\n"
                    "Install it:\n"
                    "  pip install cairosvg\n"
                    "Or switch to the default renderer:\n"
                    "  svg.renderer: rsvg-convert"
                ) from exc
        return self._version_cache

    def render(self, src: Path, dest: Path, *, scale: float, bg: str) -> None:
        _ = self.version  # raises if unavailable
        # Lazy import (PLC0415): cairosvg is an optional dep — ``self.version``
        # above raises RendererUnavailableError if it's not installed.
        import cairosvg  # pyright: ignore[reportMissingImports,reportMissingModuleSource]  # noqa: PLC0415

        background_color = "white" if bg == "white" else None
        cairosvg.svg2png(  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue,reportUnknownMemberType]
            url=str(src),
            write_to=str(dest),
            scale=scale,
            background_color=background_color,
        )


# ---------------------------------------------------------------------------
# resvg
# ---------------------------------------------------------------------------


class ResvgRenderer:
    """resvg binary backend."""

    name: str = "resvg"

    _version_cache: str | None = None

    @property
    def version(self) -> str:
        if self._version_cache is None:
            self._version_cache = _probe_version(
                self.name,
                ["resvg", "--version"],
                install_hint=(
                    "Install resvg:\n  macOS: brew install resvg\n  Rust:  cargo install resvg"
                ),
            )
        return self._version_cache

    def render(self, src: Path, dest: Path, *, scale: float, bg: str) -> None:
        _ = self.version
        cmd = ["resvg", "--zoom", str(scale), str(src), str(dest)]
        if bg == "white":
            cmd = ["resvg", "--zoom", str(scale), "--background", "white", str(src), str(dest)]
        subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# inkscape (headless)
# ---------------------------------------------------------------------------


class InkscapeRenderer:
    """Inkscape headless backend."""

    name: str = "inkscape"

    _version_cache: str | None = None

    @property
    def version(self) -> str:
        if self._version_cache is None:
            self._version_cache = _probe_version(
                self.name,
                ["inkscape", "--version"],
                install_hint=(
                    "Install Inkscape:\n"
                    "  macOS: brew install --cask inkscape\n"
                    "  Debian/Ubuntu: sudo apt install inkscape"
                ),
            )
        return self._version_cache

    def render(self, src: Path, dest: Path, *, scale: float, bg: str) -> None:
        _ = self.version
        dpi = int(scale * 96)  # 96 DPI is SVG default 1× base
        cmd = [
            "inkscape",
            "--export-type=png",
            f"--export-dpi={dpi}",
            f"--export-filename={dest}",
            str(src),
        ]
        if bg == "white":
            cmd.insert(-1, "--export-background=white")
        subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Registry and helpers
# ---------------------------------------------------------------------------

RENDERERS: dict[str, SvgRenderer] = {
    "rsvg-convert": RsvgRenderer(),
    "cairosvg": CairoSvgRenderer(),
    "resvg": ResvgRenderer(),
    "inkscape": InkscapeRenderer(),
}


def get_renderer(name: str) -> SvgRenderer:
    """Return the SvgRenderer for *name*.

    Raises:
        RendererUnavailableError: *name* is not a known renderer key.
    """
    renderer = RENDERERS.get(name)
    if renderer is None:
        known = ", ".join(sorted(RENDERERS))
        raise RendererUnavailableError(
            f"Unknown SVG renderer {name!r}. Known renderers: {known}.\n"
            f"Set svg.renderer in your mdd config to one of: {known}"
        )
    return renderer


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _probe_version(
    renderer_name: str,
    cmd: list[str],
    install_hint: str,
) -> str:
    """Run *cmd* to get the version string.

    Returns the first non-empty line of stdout, or falls back to stderr.
    Raises RendererUnavailableError if the binary is not found.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        output = (result.stdout or result.stderr or "").strip()
        return next((ln for ln in output.splitlines() if ln.strip()), "unknown")
    except FileNotFoundError as exc:
        raise RendererUnavailableError(
            f"SVG renderer {renderer_name!r} not found on PATH.\n{install_hint}"
        ) from exc
