"""svg.py — SvgToPngConverter: rasterize .svg files to .svg.png siblings.

For each Foo.svg:
  - Produces Foo.svg.png  (PNG at configured scale × nominal SVG size)
  - Produces Foo.svg.meta.yaml  (cache sidecar recording SHA, renderer, params)

Caching: skip re-render when source SHA, renderer+version, scale, and
background all match the sidecar. Atomic write via .tmp rename.

Renderer is configurable via svg.renderer in user config (default: rsvg-convert).
Missing renderer raises SystemExit(1) with an install hint.
"""

import hashlib
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mdd.converters.models import SvgConfig, SvgWrapper
from mdd.converters.protocol import ConvertResult
from mdd.utils.frontmatter import parse_yaml_mapping
from mdd.utils.logging import get_logger
from mdd.utils.svg_runner import RendererUnavailableError, SvgRenderer, get_renderer

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DIMENSION = 4096  # pixels; cap raster output to this in each dimension

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _load_svg_config() -> SvgConfig:
    """Return the typed ``svg:`` config from the first mdd config file found.

    Search order:
      1. ./configs/mdd.yaml
      2. ~/.config/mdd/config.yaml

    Returns a default-valued :class:`SvgConfig` if no config file is
    found, the file is unreadable, the file contains no ``svg:`` block,
    or the block is empty.  Surfaces ``ValidationError`` (e.g. typo'd
    keys) as a ``log.warning(...)`` and falls back to defaults — the
    converter still runs, but the user-edited typo is logged loudly.
    """
    candidates = [
        Path("configs") / "mdd.yaml",
        Path.home() / ".config" / "mdd" / "config.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        cfg = _load_svg_config_from(path)
        if cfg is not None:
            return cfg
    return SvgConfig()


def _load_svg_config_from(path: Path) -> SvgConfig | None:
    """Load and validate the ``svg:`` block from *path*.

    Returns ``None`` when the file is unreadable, isn't a YAML mapping,
    or carries no ``svg:`` block.  Returns a default-valued config when
    the block is present but empty.  Logs and returns ``None`` on
    :class:`ValidationError` so the search falls through to the next
    candidate path (or defaults).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    mapping = parse_yaml_mapping(text)
    if mapping is None or "svg" not in mapping:
        return None
    try:
        wrapper = SvgWrapper.model_validate(dict(mapping))
    except ValidationError as exc:
        log.warning("Ignoring invalid svg config in %s: %s", path, exc)
        return None
    return wrapper.svg if wrapper.svg is not None else SvgConfig()


# ---------------------------------------------------------------------------
# SVG dimension detection
# ---------------------------------------------------------------------------


_DEFAULT_SVG_DIMENSIONS = (100.0, 100.0)
_CSS_UNIT_SUFFIXES = ("rem", "em", "px", "cm", "in", "%")


def _local_tag(element: ET.Element) -> str:
    """Return the unqualified XML tag name (strip ``{namespace}`` prefix)."""
    tag = element.tag
    return tag.split("}", 1)[1] if "}" in tag else tag


def _parse_css_length(value: str) -> float | None:
    """Parse a CSS length like ``"300px"`` or ``"10.5"`` to a float; None on failure."""
    s = value.strip()
    for suffix in _CSS_UNIT_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    try:
        return float(s)
    except ValueError:
        return None


def _dimensions_from_viewbox(value: str) -> tuple[float, float] | None:
    """Return ``(width, height)`` parsed from a viewBox string, or None."""
    parts = value.strip().split()
    if len(parts) != 4:
        return None
    try:
        return (float(parts[2]), float(parts[3]))
    except ValueError:
        return None


def _dimensions_from_svg_root(root: ET.Element) -> tuple[float, float] | None:
    """Extract dimensions from an SVG root: width/height first, else viewBox."""
    if _local_tag(root) != "svg":
        return None
    w = _parse_css_length(root.get("width", ""))
    h = _parse_css_length(root.get("height", ""))
    if w is not None and h is not None:
        return (w, h)
    return _dimensions_from_viewbox(root.get("viewBox", ""))


def _parse_svg_dimensions(svg_path: Path) -> tuple[float, float]:
    """Return (width, height) from the SVG root element in user units.

    Falls back to (100, 100) if not parseable.
    """
    try:
        root = ET.parse(str(svg_path)).getroot()  # noqa: S314  # stdlib ET disables external-entity (XXE) resolution; reads dimensions only
    except ET.ParseError:
        return _DEFAULT_SVG_DIMENSIONS
    return _dimensions_from_svg_root(root) or _DEFAULT_SVG_DIMENSIONS


# ---------------------------------------------------------------------------
# Sidecar read / write
# ---------------------------------------------------------------------------

_SIDECAR_SUFFIX = ".meta.yaml"


def _sidecar_path(svg_path: Path) -> Path:
    return svg_path.parent / (svg_path.name + _SIDECAR_SUFFIX)


def _read_sidecar(svg_path: Path) -> dict[str, Any]:
    """Read the sidecar YAML's top-level ``svg:`` block; return {} if missing or malformed.

    Sidecars are mdd-written (see :func:`_write_sidecar`), so the
    payload carries render-state fields the user never edits
    (``source_sha256``, ``rendered_at``, ``renderer_version``, …) on
    top of the renderer/scale/background tuple.  We deliberately keep
    this an untyped ``dict`` rather than threading those fields through
    :class:`SvgConfig` — the cache-hit comparison in :func:`_cache_hit`
    is happy with ``.get()`` lookups, and turning the sidecar into a
    strict model would break the schema-drift tolerance the cache
    deliberately allows.
    """
    sc = _sidecar_path(svg_path)
    if not sc.exists():
        return {}
    try:
        text = sc.read_text(encoding="utf-8")
    except OSError:
        return {}
    mapping = parse_yaml_mapping(text)
    if mapping is None:
        return {}
    block = mapping.get("svg")
    if not isinstance(block, dict):
        return {}
    # The sidecar's inner block is ``dict[str, object]`` by construction
    # (mdd-written by ``_write_sidecar``); the cast turns pyright's
    # ``dict[Unknown, Unknown]`` narrowing from ``isinstance(block, dict)``
    # into a typed value the cache-hit comparison can index.
    return dict(block)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]


def _write_sidecar(
    svg_path: Path,
    *,
    source_sha256: str,
    renderer_name: str,
    renderer_version: str,
    png_scale: float,
    background: str,
) -> None:
    sc = _sidecar_path(svg_path)
    rendered_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "svg": {
            "source_sha256": source_sha256,
            "renderer": renderer_name,
            "renderer_version": renderer_version,
            "png_scale": png_scale,
            "background": background,
            "rendered_at": rendered_at,
        }
    }
    tmp = sc.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    tmp.rename(sc)


# ---------------------------------------------------------------------------
# SHA helper
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Cache check
# ---------------------------------------------------------------------------


def _cache_hit(
    svg_path: Path,
    *,
    source_sha256: str,
    renderer_name: str,
    renderer_version: str,
    png_scale: float,
    background: str,
) -> bool:
    """Return True iff the sidecar records a matching render."""
    png_path = svg_path.parent / (svg_path.name + ".png")
    if not png_path.exists():
        return False
    sc = _read_sidecar(svg_path)
    if not sc:
        return False
    return (
        sc.get("source_sha256") == source_sha256
        and sc.get("renderer") == renderer_name
        and sc.get("renderer_version") == renderer_version
        and sc.get("png_scale") == png_scale
        and sc.get("background") == background
    )


# ---------------------------------------------------------------------------
# Dimension-cap computation
# ---------------------------------------------------------------------------


def _compute_effective_scale(
    nominal_w: float,
    nominal_h: float,
    scale: float,
    *,
    warnings: list[str],
) -> float:
    """Return the scale to use, capping to MAX_DIMENSION with a warning."""
    scaled_w = nominal_w * scale
    scaled_h = nominal_h * scale
    if scaled_w > MAX_DIMENSION or scaled_h > MAX_DIMENSION:
        cap_scale = min(MAX_DIMENSION / nominal_w, MAX_DIMENSION / nominal_h)
        warnings.append(
            f"SVG scaled size ({scaled_w:.0f}×{scaled_h:.0f}) exceeds "
            f"{MAX_DIMENSION}×{MAX_DIMENSION} cap; rendering at "
            f"{cap_scale:.4f}× (was {scale:.4f}×)."
        )
        return cap_scale
    return scale


# ---------------------------------------------------------------------------
# SvgToPngConverter
# ---------------------------------------------------------------------------


class SvgToPngConverter:
    """Convert .svg files to .svg.png siblings using a configurable rasterizer.

    Config keys (under svg.* in mdd config):
        renderer:    rsvg-convert | cairosvg | resvg | inkscape  (default: rsvg-convert)
        png_scale:   float   (default: 2.0)
        background:  transparent | white  (default: transparent)
    """

    extensions: tuple[str, ...] = (".svg",)
    output_suffix: str = ".png"  # appended to full filename: Foo.svg → Foo.svg.png

    def __init__(self) -> None:
        self._cfg: SvgConfig | None = None
        self._renderer: SvgRenderer | None = None

    def _config(self) -> SvgConfig:
        if self._cfg is None:
            self._cfg = _load_svg_config()
        return self._cfg

    def _get_renderer(self) -> SvgRenderer:
        if self._renderer is None:
            name = self._config().renderer
            try:
                r = get_renderer(name)
                # Probe version now; raises RendererUnavailableError if missing.
                _ = r.version
                self._renderer = r
            except RendererUnavailableError as exc:
                log.error("%s", exc)
                sys.exit(1)
        return self._renderer

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        """Rasterize *src* SVG to PNG.

        The PNG is placed adjacent to *src* unless *dest* is given.
        """
        if dest is None:
            dest = src.parent / (src.name + self.output_suffix)

        warnings: list[str] = []
        cfg = self._config()

        scale = cfg.png_scale
        background = cfg.background

        renderer = self._get_renderer()

        # --- SHA ---
        sha = _file_sha256(src)

        # --- Cache hit? ---
        if _cache_hit(
            src,
            source_sha256=sha,
            renderer_name=renderer.name,
            renderer_version=renderer.version,
            png_scale=scale,
            background=background,
        ):
            return ConvertResult(
                output_path=dest,
                attachments_dir=None,
                metadata={
                    "source_sha256": sha,
                    "renderer": renderer.name,
                    "renderer_version": renderer.version,
                    "png_scale": scale,
                    "background": background,
                },
                warnings=warnings,
            )

        # --- Dimension cap ---
        nominal_w, nominal_h = _parse_svg_dimensions(src)
        effective_scale = _compute_effective_scale(nominal_w, nominal_h, scale, warnings=warnings)

        # --- Validate SVG structure (multiple roots) ---
        _check_single_root(src, warnings=warnings)

        # --- Render ---
        tmp = dest.with_suffix(".png.tmp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            renderer.render(src, tmp, scale=effective_scale, bg=background)
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            raise RuntimeError(f"SVG rasterization failed for {src}: {exc}") from exc
        tmp.rename(dest)

        # --- Write sidecar ---
        _write_sidecar(
            src,
            source_sha256=sha,
            renderer_name=renderer.name,
            renderer_version=renderer.version,
            png_scale=scale,
            background=background,
        )

        return ConvertResult(
            output_path=dest,
            attachments_dir=None,
            metadata={
                "source_sha256": sha,
                "renderer": renderer.name,
                "renderer_version": renderer.version,
                "png_scale": scale,
                "background": background,
            },
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# SVG validation helper
# ---------------------------------------------------------------------------


def _check_single_root(svg_path: Path, *, warnings: list[str]) -> None:
    """Hard-error if the file has multiple SVG root elements.

    A file may have namespace-qualified <svg> elements nested inside, which
    is valid.  We only care about multiple top-level SVG elements at the
    document root (technically invalid XML anyway).
    """
    try:
        tree = ET.parse(str(svg_path))  # noqa: S314  # stdlib ET disables external-entity (XXE) resolution; checks root only
        root = tree.getroot()
        tag = _local_tag(root)
        if tag != "svg":
            warnings.append(f"Root element is <{tag}>, not <svg>; rasterization may fail.")
        # ET.parse guarantees a single root; multi-root is XML-invalid and will
        # raise ParseError. We surface the warning above instead.
    except ET.ParseError as exc:
        raise ValueError(f"SVG file {svg_path} is not valid XML: {exc}") from exc
