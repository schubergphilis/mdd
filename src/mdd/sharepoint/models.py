"""Typed models for SharePoint frontmatter.

This module exposes typed pydantic models that replace the
hand-rolled ``yaml.safe_load`` + ``isinstance(parsed, dict)`` +
``dict(cast(...))`` pattern used by every reader of a SharePoint
``.md`` file's frontmatter.

Three models compose into the envelope shape written by
:mod:`mdd.sharepoint.frontmatter`::

    ---
    sharepoint:
      site:          MySite
      repo:          my-site
      source_path:   Docs/Foo.docx
      source_mtime:  2026-01-01T00:00:00+00:00
      exported_at:   2026-01-02T00:00:00+00:00
      converter:     docling-docx
      sync:
        office_sha256_at_sync: aabbcc...
        md_sha256_at_sync:     ddeeff...
        last_sync:             2026-01-02T00:00:00+00:00
        converter:             docling-docx
        converter_version:     "2.4.0"
        update_office:         false
    ---

All three inherit ``extra="forbid"`` from
:class:`mdd.utils.frontmatter.FrontmatterModel` (strict on
user-edited keys), except the outer envelope which overrides to
``extra="allow"`` so unrelated top-level frontmatter keys (Quarto
title/author, Jekyll layout, hand-written confluence blocks) survive
untouched.
"""

from __future__ import annotations

from pydantic import ConfigDict

from mdd.utils.frontmatter import FrontmatterModel


class SharepointSync(FrontmatterModel):
    """The ``sharepoint.sync`` sub-block written by the apply pipeline.

    Stamped by :func:`mdd.sharepoint.apply.sync_block.update_sync_block_in_md`
    after every successful office↔md sync.  Read by
    :func:`mdd.sharepoint.diff.read_sync_state` to decide what the next
    sync should do.

    All string fields default to ``None`` so a first-encounter file
    (no prior sync) still validates.  ``update_office`` defaults to
    ``False`` (the conservative default): md→office rendering only
    happens when the user opts in.
    """

    office_sha256_at_sync: str | None = None
    md_sha256_at_sync: str | None = None
    last_sync: str | None = None
    converter: str | None = None
    converter_version: str | None = None
    update_office: bool = False


class SharepointBlock(FrontmatterModel):
    """The ``sharepoint:`` block in a markdown file's YAML frontmatter.

    Field set covers every writer in the codebase (see
    ``sharepoint/export.py`` and ``sharepoint/frontmatter.py``).
    Strictness comes from ``extra="forbid"``: unknown keys raise, so
    typos like ``souce_path`` surface as a ``ValidationError`` instead
    of being silently ignored.
    """

    site: str = ""
    repo: str = ""
    source_path: str = ""
    source_mtime: str = ""
    exported_at: str = ""
    converter: str = ""
    sync: SharepointSync | None = None


class SharepointFrontmatter(FrontmatterModel):
    """Whole-file frontmatter envelope (only the ``sharepoint:`` block is typed).

    The envelope is intentionally permissive: top-level keys other
    than ``sharepoint`` are allowed (users may keep Quarto title /
    author, Jekyll layout, hand-written ``confluence:`` blocks
    alongside the SharePoint metadata).  Strictness lives on
    :class:`SharepointBlock`, not on the envelope.
    """

    model_config = ConfigDict(extra="allow")

    sharepoint: SharepointBlock | None = None


class SharepointCliSection(FrontmatterModel):
    """The ``sharepoint:`` block in the ``--config`` YAML file.

    Distinct from :class:`SharepointBlock`: this models the CLI's
    startup config (``configs/sharepoint.yaml`` or an explicit
    ``--config`` path), not the per-file frontmatter block written into
    each markdown mirror file.
    """

    sync_root: str | None = None


class SharepointCliConfig(FrontmatterModel):
    """The whole ``--config`` YAML file consumed by ``mdd sharepoint``.

    Permissive at the top level so other config sections (e.g. a shared
    ``config.yaml`` also read by other commands) survive untouched;
    strictness lives on :class:`SharepointCliSection`.
    """

    model_config = ConfigDict(extra="allow")

    sharepoint: SharepointCliSection | None = None
