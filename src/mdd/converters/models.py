"""Typed models for converter config files.

This module exposes the user-edited config surface for converter
modules.  The SVG rasterizer and the mermaid renderer have user-tunable
config; the other converters take all their parameters via constructor
arguments.

The on-disk shape carried by ``configs/mdd.yaml`` and
``~/.config/mdd/config.yaml`` is::

    svg:
      renderer: rsvg-convert
      png_scale: 2.0
      background: transparent
    mermaid:
      renderer: mermaidx
      args: ["-i", "{input}", "-o", "{output}", "-b", "transparent"]

i.e. an outer envelope keyed on ``svg`` / ``mermaid``.  :class:`SvgWrapper`
and :class:`MermaidWrapper` model that envelope; :class:`SvgConfig` and
:class:`MermaidConfig` model the inner blocks.

Strictness posture:

- :class:`SvgConfig` inherits ``extra="forbid"`` from
  :class:`mdd.utils.frontmatter.FrontmatterModel` so typos in
  hand-edited keys (``pngscale`` instead of ``png_scale``) raise a
  ``ValidationError`` loudly.
- :class:`SvgWrapper` overrides to ``extra="allow"`` because the
  top-level mdd config file legitimately carries unrelated keys
  (Confluence, SharePoint, Lucid, etc.); only the ``svg`` block is
  typed here.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from mdd.utils.frontmatter import FrontmatterModel

# ---------------------------------------------------------------------------
# SVG converter config
# ---------------------------------------------------------------------------


class SvgConfig(FrontmatterModel):
    """The ``svg:`` block in an mdd config file.

    All fields have defaults so a missing or empty block decodes into
    the same shape as the documented defaults baked into
    :mod:`mdd.converters.svg`.
    """

    renderer: str = "rsvg-convert"
    png_scale: float = 2.0
    background: str = "transparent"


class SvgWrapper(FrontmatterModel):
    """Outer envelope ``{svg: SvgConfig}`` carried by mdd config files.

    Top-level extras are allowed because the same config file holds
    blocks for unrelated tooling (confluence, sharepoint, lucid, ai,
    etc.).  Strictness lives on :class:`SvgConfig`, not on the
    envelope.
    """

    model_config = ConfigDict(extra="allow")

    svg: SvgConfig | None = None


# ---------------------------------------------------------------------------
# Mermaid renderer config
# ---------------------------------------------------------------------------


MERMAIDX_RENDERER = "mermaidx"


def _default_mermaid_args() -> list[str]:
    # Argument template for an external renderer, shaped for mermaid-cli.
    # ``{input}`` / ``{output}`` are substituted with the temporary ``.mmd``
    # file and the target ``.svg`` path at run time; a transparent background
    # matches the SVG rasterizer's default. Unused by the in-process renderer.
    return ["-i", "{input}", "-o", "{output}", "-b", "transparent"]


class MermaidConfig(FrontmatterModel):
    """The ``mermaid:`` block in an mdd config file.

    ``renderer`` is either :data:`MERMAIDX_RENDERER` — the in-process
    ``mermaidx`` package, installed with the ``mdd[mermaid]`` extra — or the
    name of an executable looked up on ``PATH`` (``mmdc`` from
    ``@mermaid-js/mermaid-cli``, say), in which case ``args`` is its
    argument template.
    """

    renderer: str = MERMAIDX_RENDERER
    args: list[str] = Field(default_factory=_default_mermaid_args)


class MermaidWrapper(FrontmatterModel):
    """Outer envelope ``{mermaid: MermaidConfig}`` carried by mdd config files.

    Same posture as :class:`SvgWrapper`: extras allowed on the envelope,
    strictness on the inner block.
    """

    model_config = ConfigDict(extra="allow")

    mermaid: MermaidConfig | None = None
