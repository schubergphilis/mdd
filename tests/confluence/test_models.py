"""Tests for the typed Confluence frontmatter and v2 API models (spec S40)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdd.confluence.models import (
    ConfluenceAttachment,
    ConfluenceBlock,
    ConfluenceFrontmatter,
    ConfluenceV2PageMinimal,
)

# ---------------------------------------------------------------------------
# ConfluenceFrontmatter / ConfluenceBlock — user-edited (extra="forbid" on block)
# ---------------------------------------------------------------------------


class TestConfluenceFrontmatter:
    def test_round_trip(self) -> None:
        data = {
            "confluence": {
                "space_key": "ENG",
                "page_id": "123",
                "title": "Test Page",
                "version": 5,
                "status": "CURRENT",
                "labels": ["a", "b"],
                "attachments": [
                    {"filename": "image.png", "sha256": "abc", "version": 1},
                ],
            }
        }
        fm = ConfluenceFrontmatter.model_validate(data)
        assert fm.confluence is not None
        assert fm.confluence.space_key == "ENG"
        assert fm.confluence.page_id == "123"
        assert fm.confluence.version == 5
        assert fm.confluence.attachments is not None
        assert len(fm.confluence.attachments) == 1
        assert fm.confluence.attachments[0].filename == "image.png"

    def test_unknown_key_in_block_raises(self) -> None:
        # `spcae_key` typo — strict extras at the ConfluenceBlock level.
        with pytest.raises(ValidationError) as exc:
            _ = ConfluenceFrontmatter.model_validate(
                {"confluence": {"spcae_key": "TEST", "page_id": "1"}}
            )
        assert "spcae_key" in str(exc.value)

    def test_flexible_version_coercion(self) -> None:
        # User quotes the version field — pydantic v2 coerces lazily.
        fm = ConfluenceFrontmatter.model_validate(
            {"confluence": {"space_key": "ENG", "version": "5"}}
        )
        assert fm.confluence is not None
        assert fm.confluence.version == 5

    def test_unknown_top_level_key_allowed(self) -> None:
        # The envelope is permissive: user-owned top-level keys do not raise.
        fm = ConfluenceFrontmatter.model_validate(
            {"confluence": {"space_key": "ENG"}, "my_tool_metadata": {"k": "v"}}
        )
        assert fm.confluence is not None
        assert fm.confluence.space_key == "ENG"

    def test_no_confluence_block(self) -> None:
        fm = ConfluenceFrontmatter.model_validate({"title": "Manual page"})
        assert fm.confluence is None

    def test_empty(self) -> None:
        fm = ConfluenceFrontmatter.model_validate({})
        assert fm.confluence is None

    def test_attachment_unknown_key_ignored(self) -> None:
        # Attachment entries are machine-written manifest data whose field set
        # grows over time (S16); unknown keys are tolerated, not fatal.
        att = ConfluenceAttachment.model_validate({"filename": "x", "future_field": "abc"})
        assert att.filename == "x"

    def test_attachment_converter_fields_round_trip(self) -> None:
        # Spec S16 converter-cache fields written by export.py.
        att = ConfluenceAttachment.model_validate(
            {
                "filename": "diagram.svg",
                "sha256": "abc",
                "version": 1,
                "converted_to": "diagram.svg.png",
                "converter": "SvgToPngConverter",
                "converter_version": "SvgToPngConverter",
            }
        )
        assert att.converted_to == "diagram.svg.png"
        assert att.converter == "SvgToPngConverter"
        assert att.converter_version == "SvgToPngConverter"

    def test_attachments_skipped_true(self) -> None:
        fm = ConfluenceFrontmatter.model_validate(
            {"confluence": {"space_key": "ENG", "attachments_skipped": True}}
        )
        assert fm.confluence is not None
        assert fm.confluence.attachments_skipped is True


# ---------------------------------------------------------------------------
# ConfluenceBlock direct usage
# ---------------------------------------------------------------------------


class TestConfluenceBlock:
    def test_kitchen_sink_fields_round_trip(self) -> None:
        # All known writer fields should validate without surprise.
        block = ConfluenceBlock.model_validate(
            {
                "url": "https://example.atlassian.net/wiki/spaces/ENG/pages/1/Test",
                "page_id": "1",
                "space_key": "ENG",
                "space_id": "s1",
                "parent_id": None,
                "title": "Test",
                "status": "current",
                "version": 1,
                "version_message": None,
                "created_at": "2024-01-01T00:00:00Z",
                "created_by": {"account_id": "abc", "display_name": "User"},
                "updated_at": "2024-01-01T00:00:00Z",
                "updated_by": {"account_id": "abc", "display_name": "User"},
                "labels": [],
                "exported_at": "2024-01-01T12:00:00Z",
                "source_format": "storage",
                "attachments": [],
            }
        )
        assert block.page_id == "1"
        assert block.space_key == "ENG"
        assert block.attachments == []

    def test_status_passthrough(self) -> None:
        block = ConfluenceBlock.model_validate({"status": "archived"})
        assert block.status == "archived"


# ---------------------------------------------------------------------------
# ConfluenceV2PageMinimal — API response model (extra="ignore")
# ---------------------------------------------------------------------------


class TestConfluenceV2PageMinimal:
    def test_v2_camelCase_fields(self) -> None:
        data = {
            "id": "123",
            "title": "Hi",
            "status": "current",
            "spaceId": "s1",
            "parentId": "999",
            "version": {"number": 3, "authorId": "user-1", "createdAt": "2024-01-01T00:00:00Z"},
            "_links": {"webui": "/wiki/x"},
            "body": {"storage": {"value": "<p>Hello</p>"}},
        }
        page = ConfluenceV2PageMinimal.model_validate(data)
        assert page.id == "123"
        assert page.space_id == "s1"
        assert page.parent_id == "999"
        assert page.version is not None
        assert page.version.number == 3
        assert page.version.author_id == "user-1"
        assert page.links is not None
        assert page.links.webui == "/wiki/x"
        assert page.body is not None
        assert page.body.storage is not None
        assert page.body.storage.value == "<p>Hello</p>"

    def test_unknown_fields_ignored(self) -> None:
        # The v2 surface evolves: extras like ``ownerId`` MUST NOT raise.
        page = ConfluenceV2PageMinimal.model_validate(
            {"id": "1", "ownerId": "x", "lastOwnerId": "y", "createdAt": "2024-01-01"}
        )
        assert page.id == "1"

    def test_minimal_response(self) -> None:
        # An almost-empty response (e.g. archive endpoint slim payload) still parses.
        page = ConfluenceV2PageMinimal.model_validate({"id": "1"})
        assert page.id == "1"
        assert page.status == "current"
        assert page.version is None
