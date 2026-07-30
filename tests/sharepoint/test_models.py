"""Tests for the typed SharePoint frontmatter models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdd.sharepoint.models import (
    SharepointBlock,
    SharepointFrontmatter,
    SharepointSync,
)

# ---------------------------------------------------------------------------
# SharepointFrontmatter / SharepointBlock — user-edited (extra="forbid" on block)
# ---------------------------------------------------------------------------


class TestSharepointFrontmatter:
    def test_round_trip(self) -> None:
        data = {
            "sharepoint": {
                "site": "MySite",
                "repo": "my-site",
                "source_path": "Docs/Foo.docx",
                "source_mtime": "2026-01-01T00:00:00+00:00",
                "exported_at": "2026-01-02T00:00:00+00:00",
                "converter": "docling-docx",
                "sync": {
                    "office_sha256_at_sync": "aabbcc",
                    "md_sha256_at_sync": "ddeeff",
                    "last_sync": "2026-01-02T00:00:00+00:00",
                    "converter": "docling-docx",
                    "converter_version": "2.4.0",
                    "update_office": True,
                },
            },
        }
        fm = SharepointFrontmatter.model_validate(data)
        assert fm.sharepoint is not None
        assert fm.sharepoint.site == "MySite"
        assert fm.sharepoint.source_path == "Docs/Foo.docx"
        assert fm.sharepoint.sync is not None
        assert fm.sharepoint.sync.office_sha256_at_sync == "aabbcc"
        assert fm.sharepoint.sync.update_office is True

    def test_unknown_key_in_block_raises(self) -> None:
        # `spcae_key` typo on the sharepoint block — strict extras.
        with pytest.raises(ValidationError) as exc:
            _ = SharepointFrontmatter.model_validate(
                {"sharepoint": {"spcae_key": "X", "site": "MySite"}}
            )
        assert "spcae_key" in str(exc.value)

    def test_unknown_key_in_sync_raises(self) -> None:
        # Typo in the sync sub-block also raises (extra="forbid" inherits).
        with pytest.raises(ValidationError) as exc:
            _ = SharepointFrontmatter.model_validate(
                {
                    "sharepoint": {
                        "sync": {
                            "office_sha256_at_synch": "aa",  # typo
                        }
                    }
                }
            )
        assert "office_sha256_at_synch" in str(exc.value)

    def test_flexible_update_office_coercion(self) -> None:
        # Pydantic v2 lax mode coerces "true" → True.
        fm = SharepointFrontmatter.model_validate(
            {"sharepoint": {"sync": {"update_office": "true"}}}
        )
        assert fm.sharepoint is not None
        assert fm.sharepoint.sync is not None
        assert fm.sharepoint.sync.update_office is True

    def test_unknown_top_level_key_allowed(self) -> None:
        # The envelope is permissive: Quarto / Jekyll / confluence metadata survives.
        fm = SharepointFrontmatter.model_validate(
            {
                "sharepoint": {"site": "MySite"},
                "title": "My Doc",
                "confluence": {"page_id": "1"},
            }
        )
        assert fm.sharepoint is not None
        assert fm.sharepoint.site == "MySite"

    def test_no_sharepoint_block(self) -> None:
        fm = SharepointFrontmatter.model_validate({"title": "Plain"})
        assert fm.sharepoint is None

    def test_empty(self) -> None:
        fm = SharepointFrontmatter.model_validate({})
        assert fm.sharepoint is None

    def test_first_sync_no_sync_block(self) -> None:
        # The first export writes a sharepoint block without a sync sub-block.
        fm = SharepointFrontmatter.model_validate(
            {
                "sharepoint": {
                    "site": "MySite",
                    "repo": "my-site",
                    "source_path": "Foo.docx",
                    "source_mtime": "2026-01-01T00:00:00+00:00",
                    "exported_at": "2026-01-01T00:00:00+00:00",
                    "converter": "docling-docx",
                }
            }
        )
        assert fm.sharepoint is not None
        assert fm.sharepoint.sync is None


class TestSharepointSync:
    def test_all_fields_optional(self) -> None:
        # An empty sync block is valid (first sync — values populated later).
        sync = SharepointSync.model_validate({})
        assert sync.office_sha256_at_sync is None
        assert sync.update_office is False

    def test_unknown_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            _ = SharepointSync.model_validate({"office_sha_256": "abc"})


class TestSharepointBlock:
    def test_kitchen_sink_fields_round_trip(self) -> None:
        block = SharepointBlock.model_validate(
            {
                "site": "MySite",
                "repo": "my-site",
                "source_path": "Foo.docx",
                "source_mtime": "2026-01-01T00:00:00+00:00",
                "exported_at": "2026-01-01T00:00:00+00:00",
                "converter": "docling-docx",
                "sync": {
                    "office_sha256_at_sync": "aa",
                    "md_sha256_at_sync": "bb",
                    "last_sync": "2026-01-01T00:00:00+00:00",
                    "converter": "docling-docx",
                    "converter_version": "2.4.0",
                    "update_office": False,
                },
            }
        )
        assert block.site == "MySite"
        assert block.sync is not None
        assert block.sync.update_office is False
