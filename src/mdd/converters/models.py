"""Typed models for converter config files (spec S40).

This module exposes the user-edited config surface for converter
modules.  Today only the SVG converter has user-tunable config; the
other converters take all their parameters via constructor arguments.

The on-disk shape carried by ``configs/mdd.yaml`` and
``~/.config/mdd/config.yaml`` is::

    svg:
      renderer: rsvg-convert
      png_scale: 2.0
      background: transparent

i.e. an outer envelope keyed on ``svg``.  :class:`SvgWrapper` models
that envelope; :class:`SvgConfig` models the inner block.

Strictness posture (spec S40 §Strictness posture):

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

from pydantic import ConfigDict

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
