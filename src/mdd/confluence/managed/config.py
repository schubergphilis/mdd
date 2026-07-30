"""Managed-publishers config: typed models, parsing, merging, file loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from mdd.utils.frontmatter import FrontmatterModel, parse_yaml_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping


class PublisherEntry(FrontmatterModel):
    """One external-publisher record from the config."""

    name: str
    account_ids: list[str] = Field(default_factory=list)
    body_marker_patterns: list[str] = Field(default_factory=list)
    source_url: str = ""
    message: str = ""


class ManagedSpaceEntry(FrontmatterModel):
    space_key: str
    publisher_name: str


class ManagedSubtreeEntry(FrontmatterModel):
    space_key: str
    root_page_id: str
    publisher_name: str


class ManagedConfig(FrontmatterModel):
    """Merged managed-publishers configuration."""

    external_publishers: list[PublisherEntry] = Field(default_factory=list)
    managed_spaces: list[ManagedSpaceEntry] = Field(default_factory=list)
    managed_subtrees: list[ManagedSubtreeEntry] = Field(default_factory=list)

    # --- Derived lookups ---

    def publisher_by_name(self, name: str) -> PublisherEntry | None:
        for p in self.external_publishers:
            if p.name == name:
                return p
        return None

    def publisher_for_space(self, space_key: str) -> PublisherEntry | None:
        for s in self.managed_spaces:
            if s.space_key == space_key:
                return self.publisher_by_name(s.publisher_name)
        return None

    def publisher_for_subtree(self, ancestor_ids: list[str]) -> PublisherEntry | None:
        for sub in self.managed_subtrees:
            if sub.root_page_id in ancestor_ids:
                return self.publisher_by_name(sub.publisher_name)
        return None

    def publisher_for_account(self, account_id: str) -> PublisherEntry | None:
        for p in self.external_publishers:
            if account_id in p.account_ids:
                return p
        return None

    def publisher_for_body(self, body_storage: str) -> PublisherEntry | None:
        for p in self.external_publishers:
            for pattern in p.body_marker_patterns:
                try:
                    if re.search(pattern, body_storage):
                        return p
                except re.error:
                    pass
        return None


_BUNDLED_CONFIG = (
    Path(__file__).parent.parent.parent.parent.parent / "configs" / "external-publishers.yaml"
)

# Alternate bundled path: when installed as a package, the configs/ dir lives
# two levels above the package root.  We resolve by trying both.
_BUNDLED_CONFIG_ALT = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "configs"
    / "external-publishers.yaml"
)

_USER_CONFIG = Path.home() / ".config" / "mdd" / "external-publishers.yaml"
_LOCAL_CONFIG = Path("configs") / "external-publishers.local.yaml"


def _parse_config(data: Mapping[str, object]) -> ManagedConfig:
    """Parse a raw YAML mapping into a :class:`ManagedConfig`.

    Propagates :class:`pydantic.ValidationError` on unknown keys or
    bad shapes: config files surface validation failures rather than
    silently dropping entries.
    """
    return ManagedConfig.model_validate(data)


def _merge_configs(base: ManagedConfig, override: ManagedConfig) -> ManagedConfig:
    """Merge override into base.

    - managed_spaces: override entries appended (no de-dup on space_key).
    - managed_subtrees: override entries appended.
    - external_publishers: if a publisher with the same name exists in base,
      its account_ids list is extended with override's account_ids; any
      new publisher names are appended wholesale.
    """
    pub_index: dict[str, PublisherEntry] = {p.name: p for p in base.external_publishers}
    for op in override.external_publishers:
        if op.name in pub_index:
            existing = pub_index[op.name]
            merged_ids = list(dict.fromkeys(existing.account_ids + op.account_ids))
            merged_patterns = list(
                dict.fromkeys(existing.body_marker_patterns + op.body_marker_patterns)
            )
            pub_index[op.name] = PublisherEntry(
                name=existing.name,
                account_ids=merged_ids,
                body_marker_patterns=merged_patterns,
                source_url=op.source_url or existing.source_url,
                message=op.message or existing.message,
            )
        else:
            pub_index[op.name] = op

    return ManagedConfig(
        external_publishers=list(pub_index.values()),
        managed_spaces=base.managed_spaces + override.managed_spaces,
        managed_subtrees=base.managed_subtrees + override.managed_subtrees,
    )


def _load_yaml_file(path: Path) -> Mapping[str, object]:
    """Read *path* and return the top-level mapping, or {} on read / parse error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_yaml_mapping(text) or {}


def load_managed_config(
    *,
    config_path: Path | None = None,
    user_config_path: Path | None = None,
    local_config_path: Path | None = None,
) -> ManagedConfig:
    """Load and merge the managed-publishers configuration.

    Priority (highest first):
    - *local_config_path* (or ``./configs/external-publishers.local.yaml``)
    - *user_config_path*  (or ``~/.config/mdd/external-publishers.yaml``)
    - *config_path*       (or the bundled ``configs/external-publishers.yaml``)

    Raises:
        pydantic.ValidationError: when a config file contains unknown
            keys or wrongly-typed values.  Config-file shape errors are
            surfaced rather than silently dropped.

    Returns:
        A merged :class:`ManagedConfig`.
    """
    if config_path is not None:
        bundled_path = config_path
    else:
        bundled_path = _BUNDLED_CONFIG
        if not bundled_path.exists():
            bundled_path = _BUNDLED_CONFIG_ALT

    base = _parse_config(_load_yaml_file(bundled_path))

    user_path = user_config_path if user_config_path is not None else _USER_CONFIG
    if user_path.exists():
        user_config = _parse_config(_load_yaml_file(user_path))
        base = _merge_configs(base, user_config)

    local_path = local_config_path if local_config_path is not None else _LOCAL_CONFIG
    if local_path.exists():
        local_config = _parse_config(_load_yaml_file(local_path))
        base = _merge_configs(base, local_config)

    return base


# Re-export ValidationError for callers that want to catch a config-load error
# without taking a direct pydantic dependency.  Used by `__init__.py`.
__all__ = [
    "ManagedConfig",
    "ManagedSpaceEntry",
    "ManagedSubtreeEntry",
    "PublisherEntry",
    "ValidationError",
    "load_managed_config",
]
