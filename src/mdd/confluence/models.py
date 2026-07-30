"""Typed models for Confluence frontmatter and v2 API responses.

This module exposes two families of models:

- **User-edited frontmatter** (``ConfluenceFrontmatter``,
  ``ConfluenceBlock``, ``ConfluenceAttachment``).  Inherits
  ``extra="forbid"`` from :class:`mdd.utils.frontmatter.FrontmatterModel`
  so typos in hand-edited YAML keys raise loudly.
- **Confluence v2 API responses** (``ConfluenceV2PageMinimal`` and
  its sub-models).  Overrides to ``extra="ignore"`` because the v2
  page surface is large and evolves; we only model the fields the
  migrated read paths actually consume.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from mdd.utils.frontmatter import FrontmatterModel

# ---------------------------------------------------------------------------
# User-edited frontmatter models
# ---------------------------------------------------------------------------


class ConfluenceAttachment(FrontmatterModel):
    """One ``attachments[]`` entry inside the ``confluence:`` block.

    Unlike the rest of the user-edited frontmatter, attachment entries
    are *machine-written* manifest data that ``confluence/export.py``
    regenerates on every sync, and the field set grows over time (the
    ``converted_*`` trio was a later addition).  So this model overrides to
    ``extra="ignore"``: an older mdd reading a newer file (or vice
    versa) tolerates unmodelled keys instead of raising mid-sync.  Typo
    detection still applies to the hand-edited keys on
    :class:`ConfluenceBlock`.
    """

    model_config = ConfigDict(extra="ignore")

    filename: str = ""
    media_type: str = ""
    size: int = 0
    sha256: str = ""
    version: int = 0

    # Converter cache — written by export.py when an
    # attachment is converted to markdown (e.g. SVG → PNG, docx → md).
    converted_to: str | None = None
    converter: str | None = None
    converter_version: str | None = None


class ConfluenceBlock(FrontmatterModel):
    """The ``confluence:`` block in a markdown file's YAML frontmatter.

    Fields are intentionally permissive (most have defaults) so a
    partially-published page (``mdd confluence create-page`` failed
    halfway) is still parseable.  Strictness comes from ``extra="forbid"``:
    unknown keys raise, so typos like ``spcae_key: ENG`` surface as a
    ``ValidationError`` instead of being silently ignored.

    Field set covers every known writer in the codebase (see
    ``confluence/export.py``, ``confluence/create.py``,
    ``confluence/update.py``, ``confluence/mutate.py``).  Adding a new
    frontmatter field means extending this model.
    """

    # Core identity / placement
    space_key: str = ""
    space_id: str = ""
    page_id: str | None = None
    parent_id: str | None = None
    title: str = ""
    status: str = "CURRENT"
    version: int = 0
    labels: list[str] = Field(default_factory=list)
    attachments: list[ConfluenceAttachment] | None = None
    attachments_skipped: bool = False

    # Audit / URL fields written by export and refreshed by create / mutate.
    url: str = ""
    exported_at: str = ""
    updated_at: str = ""
    # `updated_by` is sometimes a string (display name) and sometimes a dict
    # (account_id / display_name).  Both writers exist in the codebase; the
    # model accepts either shape until a separate cleanup picks one.
    updated_by: object = None
    created_at: str = ""
    created_by: object = None  # same string-or-dict shape as updated_by
    version_message: str | None = None
    source_format: str = ""

    # Managed-elsewhere stamping.
    managed_by: str = ""
    managed_source_url: str = ""
    managed_reason: str = ""

    # publish-office state.  Free-form until it gets typed models of its own.
    publish_office: object = None
    publish_office_state: object = None


class ConfluenceFrontmatter(FrontmatterModel):
    """Whole-file frontmatter envelope (only the ``confluence:`` block is typed).

    The envelope is intentionally permissive: top-level keys other
    than ``confluence`` are allowed (users may add their own
    metadata for unrelated tooling).  Strictness lives on
    :class:`ConfluenceBlock`, not on the envelope.
    """

    model_config = ConfigDict(extra="allow")

    confluence: ConfluenceBlock | None = None


# ---------------------------------------------------------------------------
# Confluence v2 API response models (minimal — see module docstring)
# ---------------------------------------------------------------------------


class _V2APIModel(FrontmatterModel):
    """Base for v2 API response models — extras ignored so the surface can evolve."""

    model_config = ConfigDict(extra="ignore")


class ConfluenceV2BodyStorage(_V2APIModel):
    value: str = ""


class ConfluenceV2Body(_V2APIModel):
    storage: ConfluenceV2BodyStorage | None = None


class ConfluenceV2Version(_V2APIModel):
    number: int = 1
    author_id: str | None = Field(default=None, alias="authorId")
    created_at: str | None = Field(default=None, alias="createdAt")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ConfluenceV2Links(_V2APIModel):
    webui: str = ""


class ConfluenceV2PageMinimal(_V2APIModel):
    """The slice of the v2 ``/pages/{id}`` response that mdd reads today.

    Unknown fields are silently ignored: the v2 surface adds keys
    frequently (e.g. ``ownerId``, ``lastOwnerId``, ``createdAt``),
    and a strict model would break sync on every API release.
    """

    id: str = ""
    title: str = ""
    status: str = "current"
    space_id: str = Field(default="", alias="spaceId")
    space_key: str = Field(default="", alias="spaceKey")
    parent_id: str | None = Field(default=None, alias="parentId")
    version: ConfluenceV2Version | None = None
    body: ConfluenceV2Body | None = None
    links: ConfluenceV2Links | None = Field(default=None, alias="_links")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
