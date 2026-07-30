"""Tests for ManagedConfig loading and per-user merge."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from mdd.confluence.managed import (
    ManagedConfig,
    ManagedSpaceEntry,
    ManagedSubtreeEntry,
    PublisherEntry,
    load_managed_config,
)
from mdd.confluence.managed.config import (
    _merge_configs,  # pyright: ignore[reportPrivateUsage]
    _parse_config,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# _parse_config
# ---------------------------------------------------------------------------


class TestParseConfig:
    def test_empty_dict(self) -> None:
        config = _parse_config({})
        assert config.external_publishers == []
        assert config.managed_spaces == []
        assert config.managed_subtrees == []

    def test_full_config(self) -> None:
        data = {
            "external_publishers": [
                {
                    "name": "sphinx",
                    "account_ids": ["bot-id-1", "bot-id-2"],
                    "body_marker_patterns": ["View source.*sbpcf"],
                    "source_url": "https://example.com",
                    "message": "Edit at {source_url}",
                }
            ],
            "managed_spaces": [{"space_key": "MCQF", "publisher_name": "sphinx"}],
            "managed_subtrees": [
                {
                    "space_key": "saas",
                    "root_page_id": "844137445",
                    "publisher_name": "techdocs",
                }
            ],
        }
        config = _parse_config(data)

        assert len(config.external_publishers) == 1
        pub = config.external_publishers[0]
        assert pub.name == "sphinx"
        assert pub.account_ids == ["bot-id-1", "bot-id-2"]
        assert pub.body_marker_patterns == ["View source.*sbpcf"]
        assert pub.source_url == "https://example.com"
        assert "Edit at" in pub.message

        assert len(config.managed_spaces) == 1
        assert config.managed_spaces[0].space_key == "MCQF"
        assert config.managed_spaces[0].publisher_name == "sphinx"

        assert len(config.managed_subtrees) == 1
        assert config.managed_subtrees[0].root_page_id == "844137445"

    def test_missing_required_name_raises(self) -> None:
        # Config files surface shape errors outward — the old
        # silent-drop-the-entry behaviour is gone.
        data: dict[str, Any] = {
            "external_publishers": [{"account_ids": ["bot"]}],  # missing name
        }
        with pytest.raises(ValidationError):
            _ = _parse_config(data)

    def test_unknown_top_level_key_raises(self) -> None:
        # `extra="forbid"` catches typos in user-edited config: a key like
        # ``mananged_spaces`` would silently disable every restriction today.
        data: dict[str, Any] = {"mananged_spaces": []}
        with pytest.raises(ValidationError):
            _ = _parse_config(data)


# ---------------------------------------------------------------------------
# _merge_configs
# ---------------------------------------------------------------------------


class TestMergeConfigs:
    def test_new_publisher_is_appended(self) -> None:
        base = ManagedConfig(
            external_publishers=[PublisherEntry(name="sphinx", account_ids=["aid1"])]
        )
        override = ManagedConfig(
            external_publishers=[PublisherEntry(name="techdocs", account_ids=["aid2"])]
        )
        merged = _merge_configs(base, override)
        names = [p.name for p in merged.external_publishers]
        assert "sphinx" in names
        assert "techdocs" in names

    def test_existing_publisher_account_ids_extended(self) -> None:
        base = ManagedConfig(
            external_publishers=[PublisherEntry(name="sphinx", account_ids=["aid1"])]
        )
        override = ManagedConfig(
            external_publishers=[PublisherEntry(name="sphinx", account_ids=["aid2"])]
        )
        merged = _merge_configs(base, override)
        assert len(merged.external_publishers) == 1
        assert "aid1" in merged.external_publishers[0].account_ids
        assert "aid2" in merged.external_publishers[0].account_ids

    def test_duplicate_account_ids_deduped(self) -> None:
        base = ManagedConfig(
            external_publishers=[PublisherEntry(name="sphinx", account_ids=["aid1"])]
        )
        override = ManagedConfig(
            external_publishers=[PublisherEntry(name="sphinx", account_ids=["aid1", "aid2"])]
        )
        merged = _merge_configs(base, override)
        assert merged.external_publishers[0].account_ids.count("aid1") == 1

    def test_spaces_appended(self) -> None:
        base = ManagedConfig(
            managed_spaces=[ManagedSpaceEntry(space_key="A", publisher_name="pub1")]
        )
        override = ManagedConfig(
            managed_spaces=[ManagedSpaceEntry(space_key="B", publisher_name="pub2")]
        )
        merged = _merge_configs(base, override)
        assert len(merged.managed_spaces) == 2

    def test_subtrees_appended(self) -> None:
        base = ManagedConfig(
            managed_subtrees=[
                ManagedSubtreeEntry(space_key="A", root_page_id="1", publisher_name="p1")
            ]
        )
        override = ManagedConfig(
            managed_subtrees=[
                ManagedSubtreeEntry(space_key="B", root_page_id="2", publisher_name="p2")
            ]
        )
        merged = _merge_configs(base, override)
        assert len(merged.managed_subtrees) == 2

    def test_override_source_url_wins(self) -> None:
        base = ManagedConfig(
            external_publishers=[
                PublisherEntry(
                    name="sphinx",
                    account_ids=["aid1"],
                    source_url="https://original.com",
                )
            ]
        )
        override = ManagedConfig(
            external_publishers=[
                PublisherEntry(
                    name="sphinx",
                    account_ids=[],
                    source_url="https://new.com",
                )
            ]
        )
        merged = _merge_configs(base, override)
        assert merged.external_publishers[0].source_url == "https://new.com"


# ---------------------------------------------------------------------------
# load_managed_config
# ---------------------------------------------------------------------------


class TestLoadManagedConfig:
    def test_loads_bundled_config(self) -> None:
        """The bundled config parses into well-formed publisher entries.

        Which publishers ship is site policy and differs per distribution,
        so this asserts the shape rather than the names.
        """
        config = load_managed_config()
        assert config.external_publishers, "bundled config declares no publishers"
        for publisher in config.external_publishers:
            assert publisher.name
            assert publisher.source_url
            assert "{source_url}" in publisher.message

    def test_user_config_merged(self, tmp_path: Path) -> None:
        """A user entry extends the account_ids of a matching bundled publisher."""
        existing = load_managed_config().external_publishers[0].name
        user_cfg = tmp_path / "user.yaml"
        user_cfg.write_text(
            f"""
external_publishers:
  - name: {existing}
    account_ids:
      - "my-real-bot-id"
"""
        )
        config = load_managed_config(user_config_path=user_cfg)
        merged = next((p for p in config.external_publishers if p.name == existing), None)
        assert merged is not None
        assert "my-real-bot-id" in merged.account_ids

    def test_local_config_merged(self, tmp_path: Path) -> None:
        local_cfg = tmp_path / "local.yaml"
        local_cfg.write_text(
            """
external_publishers:
  - name: new-publisher
    account_ids:
      - "new-bot-id"
    source_url: https://new.example.com
    message: Edit at {source_url}
"""
        )
        config = load_managed_config(local_config_path=local_cfg)
        names = [p.name for p in config.external_publishers]
        assert "new-publisher" in names

    def test_missing_user_config_is_ignored(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        config = load_managed_config(user_config_path=missing)
        assert config.external_publishers  # bundled config still loaded

    def test_custom_bundled_path(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled.yaml"
        bundled.write_text(
            """
external_publishers:
  - name: custom-pub
    account_ids: []
    source_url: https://custom.example.com
    message: custom message
"""
        )
        config = load_managed_config(config_path=bundled)
        names = [p.name for p in config.external_publishers]
        assert "custom-pub" in names


# ---------------------------------------------------------------------------
# ManagedConfig lookup helpers
# ---------------------------------------------------------------------------


class TestManagedConfigLookups:
    def _make(self) -> ManagedConfig:
        return ManagedConfig(
            external_publishers=[
                PublisherEntry(name="sphinx", account_ids=["bot1"], source_url="https://s.com"),
                PublisherEntry(name="techdocs", account_ids=["bot2"], source_url="https://t.com"),
            ],
            managed_spaces=[ManagedSpaceEntry(space_key="MCQF", publisher_name="sphinx")],
            managed_subtrees=[
                ManagedSubtreeEntry(
                    space_key="SAAS", root_page_id="root-id", publisher_name="techdocs"
                )
            ],
        )

    def test_publisher_by_name_found(self) -> None:
        config = self._make()
        pub = config.publisher_by_name("sphinx")
        assert pub is not None
        assert pub.name == "sphinx"

    def test_publisher_by_name_not_found(self) -> None:
        config = self._make()
        assert config.publisher_by_name("unknown") is None

    def test_publisher_for_space_match(self) -> None:
        config = self._make()
        pub = config.publisher_for_space("MCQF")
        assert pub is not None
        assert pub.name == "sphinx"

    def test_publisher_for_space_no_match(self) -> None:
        config = self._make()
        assert config.publisher_for_space("ENG") is None

    def test_publisher_for_subtree_match(self) -> None:
        config = self._make()
        pub = config.publisher_for_subtree(["parent-id", "root-id"])
        assert pub is not None
        assert pub.name == "techdocs"

    def test_publisher_for_subtree_no_match(self) -> None:
        config = self._make()
        assert config.publisher_for_subtree(["some-other-id"]) is None

    def test_publisher_for_account_match(self) -> None:
        config = self._make()
        pub = config.publisher_for_account("bot1")
        assert pub is not None
        assert pub.name == "sphinx"

    def test_publisher_for_account_no_match(self) -> None:
        config = self._make()
        assert config.publisher_for_account("human-user") is None

    def test_publisher_for_body_match(self) -> None:
        config = ManagedConfig(
            external_publishers=[
                PublisherEntry(name="sphinx", body_marker_patterns=["View source.*sbpcf"])
            ]
        )
        pub = config.publisher_for_body("<p>View source on GitLab sbpcf project</p>")
        assert pub is not None
        assert pub.name == "sphinx"

    def test_publisher_for_body_no_match(self) -> None:
        config = ManagedConfig(
            external_publishers=[
                PublisherEntry(name="sphinx", body_marker_patterns=["View source.*sbpcf"])
            ]
        )
        assert config.publisher_for_body("<p>Normal content</p>") is None
