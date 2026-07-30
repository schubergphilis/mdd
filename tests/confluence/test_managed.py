"""Tests for managed-elsewhere detection cascade."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from mdd.confluence.managed import (
    ManagedClassification,
    ManagedConfig,
    ManagedReason,
    ManagedSpaceEntry,
    ManagedSubtreeEntry,
    PageInfo,
    PublisherEntry,
    build_page_info_from_page_data,
    classify_page,
    managed_export_header,
)
from mdd.confluence.managed.classify import _user_can_update  # pyright: ignore[reportPrivateUsage]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_publisher(
    name: str = "testpub",
    account_ids: list[str] | None = None,
    body_patterns: list[str] | None = None,
    source_url: str = "https://example.com",
    message: str = "managed by {publisher_name}",
) -> PublisherEntry:
    return PublisherEntry(
        name=name,
        account_ids=account_ids or [],
        body_marker_patterns=body_patterns or [],
        source_url=source_url,
        message=message,
    )


def _make_config(
    publishers: list[PublisherEntry] | None = None,
    spaces: list[ManagedSpaceEntry] | None = None,
    subtrees: list[ManagedSubtreeEntry] | None = None,
) -> ManagedConfig:
    return ManagedConfig(
        external_publishers=publishers or [],
        managed_spaces=spaces or [],
        managed_subtrees=subtrees or [],
    )


def _make_page(
    page_id: str = "111",
    space_key: str = "ENG",
    ancestor_ids: list[str] | None = None,
    version_author_id: str = "",
    body_storage: str = "<p>Some content</p>",
) -> PageInfo:
    return PageInfo(
        page_id=page_id,
        space_key=space_key,
        ancestor_ids=ancestor_ids or [],
        version_author_id=version_author_id,
        body_storage=body_storage,
    )


def _mock_client_no_restrictions() -> MagicMock:
    """Return a mock client where get_current_user and get_page_restrictions are stubbed."""
    client = MagicMock()
    client.get_current_user.return_value = {"accountId": "current-user-id"}
    # Unrestricted page
    client.get_page_restrictions.return_value = {
        "update": {
            "restrictions": {
                "user": {"results": []},
                "group": {"results": []},
            }
        }
    }
    return client


# ---------------------------------------------------------------------------
# Layer 1: managed_spaces
# ---------------------------------------------------------------------------


class TestManagedSpaces:
    def test_space_key_matches(self) -> None:
        pub = _make_publisher(name="sphinx")
        config = _make_config(
            publishers=[pub],
            spaces=[ManagedSpaceEntry(space_key="MCQF", publisher_name="sphinx")],
        )
        page = _make_page(space_key="MCQF")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.MANAGED_SPACE
        assert result.publisher_name == "sphinx"

    def test_space_key_no_match(self) -> None:
        pub = _make_publisher(name="sphinx")
        config = _make_config(
            publishers=[pub],
            spaces=[ManagedSpaceEntry(space_key="MCQF", publisher_name="sphinx")],
        )
        page = _make_page(space_key="ENG")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed


# ---------------------------------------------------------------------------
# Layer 2: managed_subtrees
# ---------------------------------------------------------------------------


class TestManagedSubtrees:
    def test_ancestor_root_in_subtree(self) -> None:
        pub = _make_publisher(name="techdocs")
        config = _make_config(
            publishers=[pub],
            subtrees=[
                ManagedSubtreeEntry(
                    space_key="SAAS", root_page_id="844137445", publisher_name="techdocs"
                )
            ],
        )
        # Page has the subtree root in its ancestors
        page = _make_page(space_key="SAAS", ancestor_ids=["844137445", "999111"])
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.MANAGED_SUBTREE
        assert result.publisher_name == "techdocs"

    def test_ancestor_not_in_subtree(self) -> None:
        pub = _make_publisher(name="techdocs")
        config = _make_config(
            publishers=[pub],
            subtrees=[
                ManagedSubtreeEntry(
                    space_key="SAAS", root_page_id="844137445", publisher_name="techdocs"
                )
            ],
        )
        page = _make_page(space_key="SAAS", ancestor_ids=["999000"])
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed

    def test_space_layer_takes_precedence_over_subtree(self) -> None:
        """MANAGED_SPACE fires before MANAGED_SUBTREE."""
        pub = _make_publisher(name="sphinx")
        config = _make_config(
            publishers=[pub],
            spaces=[ManagedSpaceEntry(space_key="MCQF", publisher_name="sphinx")],
            subtrees=[
                ManagedSubtreeEntry(space_key="MCQF", root_page_id="root1", publisher_name="sphinx")
            ],
        )
        page = _make_page(space_key="MCQF", ancestor_ids=["root1"])
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.MANAGED_SPACE


# ---------------------------------------------------------------------------
# Layer 3: publisher account
# ---------------------------------------------------------------------------


class TestPublisherAccount:
    def test_author_is_known_bot(self) -> None:
        pub = _make_publisher(name="sphinx", account_ids=["bot-account-123"])
        config = _make_config(publishers=[pub])
        page = _make_page(version_author_id="bot-account-123")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.PUBLISHER_ACCOUNT_MATCH
        assert result.publisher_name == "sphinx"

    def test_author_is_not_bot(self) -> None:
        pub = _make_publisher(name="sphinx", account_ids=["bot-account-123"])
        config = _make_config(publishers=[pub])
        page = _make_page(version_author_id="human-user-456")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed

    def test_empty_author_id_skips_layer(self) -> None:
        pub = _make_publisher(name="sphinx", account_ids=["bot-account-123"])
        config = _make_config(publishers=[pub])
        page = _make_page(version_author_id="")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed


# ---------------------------------------------------------------------------
# Layer 4: body marker patterns
# ---------------------------------------------------------------------------


class TestBodyMarker:
    def test_body_matches_pattern(self) -> None:
        pub = _make_publisher(
            name="sphinx",
            body_patterns=["View source on GitLab.*docs-pipeline"],
        )
        config = _make_config(publishers=[pub])
        body = "<p>View source on GitLab at docs-pipeline project</p>"
        page = _make_page(body_storage=body)
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.BODY_MARKER
        assert result.publisher_name == "sphinx"

    def test_body_no_match(self) -> None:
        pub = _make_publisher(
            name="sphinx",
            body_patterns=["View source on GitLab.*docs-pipeline"],
        )
        config = _make_config(publishers=[pub])
        body = "<p>This page was written by a human</p>"
        page = _make_page(body_storage=body)
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed

    def test_invalid_regex_is_skipped(self) -> None:
        """A broken pattern should not crash the cascade."""
        pub = _make_publisher(name="sphinx", body_patterns=["[invalid("])
        config = _make_config(publishers=[pub])
        page = _make_page(body_storage="[invalid(")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed


# ---------------------------------------------------------------------------
# Layer 5: page restrictions
# ---------------------------------------------------------------------------


class TestPageRestrictions:
    def test_user_in_update_list_is_not_restricted(self) -> None:
        """If the current user is in the update restriction list, page is pushable."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": [{"accountId": "my-account-id", "displayName": "Me"}]},
                    "group": {"results": []},
                }
            }
        }
        result = _user_can_update("page123", "my-account-id", client)
        assert result is True

    def test_user_not_in_update_list_is_restricted(self) -> None:
        """User absent from the update restriction list → restricted."""
        client = MagicMock()
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": [{"accountId": "bot-account-123", "displayName": "Bot"}]},
                    "group": {"results": []},
                }
            }
        }
        result = _user_can_update("page123", "my-account-id", client)
        assert result is False

    def test_empty_restrictions_means_unrestricted(self) -> None:
        """Empty restrictions list → anyone can update."""
        client = MagicMock()
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": []},
                    "group": {"results": []},
                }
            }
        }
        result = _user_can_update("page123", "my-account-id", client)
        assert result is True

    def test_api_error_is_fail_open(self) -> None:
        """Restriction check errors → fail-open (assume allowed)."""
        client = MagicMock()
        client.get_page_restrictions.side_effect = Exception("network error")
        result = _user_can_update("page123", "my-account-id", client)
        assert result is True

    def test_classify_fires_read_only_layer(self) -> None:
        """classify_page returns READ_ONLY when user cannot update."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": [{"accountId": "bot-account", "displayName": "Bot"}]},
                    "group": {"results": []},
                }
            }
        }
        config = _make_config()  # no publishers / spaces / subtrees
        page = _make_page()
        result = classify_page(
            page, config, client, current_account_id="my-account-id", check_restrictions=True
        )
        assert result.is_managed
        assert result.reason == ManagedReason.READ_ONLY
        assert result.publisher_name is None

    def test_check_restrictions_false_skips_layer_5(self) -> None:
        """check_restrictions=False skips the restriction API call."""
        client = MagicMock()
        client.get_current_user.return_value = {"accountId": "my-account-id"}
        # get_page_restrictions would fire READ_ONLY, but check_restrictions=False
        client.get_page_restrictions.return_value = {
            "update": {
                "restrictions": {
                    "user": {"results": [{"accountId": "other-bot"}]},
                    "group": {"results": []},
                }
            }
        }
        config = _make_config()
        page = _make_page()
        result = classify_page(
            page, config, client, current_account_id="my-account-id", check_restrictions=False
        )
        assert not result.is_managed
        client.get_page_restrictions.assert_not_called()


# ---------------------------------------------------------------------------
# Priority: earlier layers short-circuit later layers
# ---------------------------------------------------------------------------


class TestCascadePriority:
    def test_space_beats_account(self) -> None:
        pub_space = _make_publisher(name="space-pub", account_ids=["other-bot"])
        pub_account = _make_publisher(name="account-pub", account_ids=["the-author"])
        config = _make_config(
            publishers=[pub_space, pub_account],
            spaces=[ManagedSpaceEntry(space_key="ENG", publisher_name="space-pub")],
        )
        page = _make_page(space_key="ENG", version_author_id="the-author")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.MANAGED_SPACE
        assert result.publisher_name == "space-pub"

    def test_account_beats_body(self) -> None:
        pub = _make_publisher(
            name="test",
            account_ids=["the-author"],
            body_patterns=["some marker"],
        )
        config = _make_config(publishers=[pub])
        page = _make_page(
            version_author_id="the-author",
            body_storage="<p>some marker in body</p>",
        )
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.reason == ManagedReason.PUBLISHER_ACCOUNT_MATCH

    def test_not_managed_when_no_signals(self) -> None:
        config = _make_config()
        page = _make_page()
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert not result.is_managed
        assert result.reason is None


# ---------------------------------------------------------------------------
# Message rendering
# ---------------------------------------------------------------------------


class TestMessageRendering:
    def test_message_substitution(self) -> None:
        pub = _make_publisher(
            name="mypub",
            source_url="https://example.com/repo",
            message="Edit at {source_url} via {publisher_name}",
        )
        config = _make_config(
            publishers=[pub],
            spaces=[ManagedSpaceEntry(space_key="A", publisher_name="mypub")],
        )
        page = _make_page(space_key="A")
        result = classify_page(
            page, config, _mock_client_no_restrictions(), check_restrictions=False
        )

        assert result.is_managed
        assert result.message == "Edit at https://example.com/repo via mypub"


# ---------------------------------------------------------------------------
# managed_export_header
# ---------------------------------------------------------------------------


class TestManagedExportHeader:
    def test_header_with_source_url(self) -> None:
        cl = ManagedClassification(
            is_managed=True,
            reason=ManagedReason.MANAGED_SPACE,
            publisher_name="sphinx",
            source_url="https://example.com",
            message=None,
        )
        header = managed_export_header(cl, "2026-05-08")
        assert "**Confluence export (managed by sphinx)**" in header
        assert "https://example.com" in header
        assert "Edit there; this mirror is read-only." in header
        assert "2026-05-08" in header

    def test_header_without_source_url(self) -> None:
        cl = ManagedClassification(
            is_managed=True,
            reason=ManagedReason.READ_ONLY,
            publisher_name=None,
            source_url=None,
            message=None,
        )
        header = managed_export_header(cl, "2026-05-08")
        assert "**Confluence export (managed by unknown publisher)**" in header

    def test_header_prefix_matches_strip_rule(self) -> None:
        """The managed header starts with > **Confluence export so strip_export_header works."""
        cl = ManagedClassification(
            is_managed=True,
            reason=ManagedReason.MANAGED_SPACE,
            publisher_name="sphinx",
            source_url="https://example.com",
            message=None,
        )
        header = managed_export_header(cl, "2026-05-08")
        # strip_export_header looks for "> **Confluence export"
        assert header.strip().startswith("> **Confluence export")


# ---------------------------------------------------------------------------
# build_page_info_from_page_data
# ---------------------------------------------------------------------------


class TestBuildPageInfo:
    def test_extracts_fields(self) -> None:
        page_data: dict[str, Any] = {
            "id": "999",
            "spaceKey": "SAAS",
            "parentId": "100",
            "version": {"authorId": "bot-123"},
        }
        info = build_page_info_from_page_data(page_data, "<p>body</p>")
        assert info.page_id == "999"
        assert info.space_key == "SAAS"
        assert info.ancestor_ids == ["100"]
        assert info.version_author_id == "bot-123"
        assert info.body_storage == "<p>body</p>"

    def test_extracts_ancestors_list(self) -> None:
        page_data: dict[str, Any] = {
            "id": "999",
            "spaceKey": "SAAS",
            "ancestors": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            "version": {"authorId": "bot-123"},
        }
        info = build_page_info_from_page_data(page_data, "")
        assert info.ancestor_ids == ["1", "2", "3"]

    def test_missing_fields_return_defaults(self) -> None:
        info = build_page_info_from_page_data({}, "")
        assert info.page_id == ""
        assert info.space_key == ""
        assert info.ancestor_ids == []
        assert info.version_author_id == ""
