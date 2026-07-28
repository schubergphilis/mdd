"""Tests for mdd.search.sources — the root-source registry (spec S19/S44)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from mdd.search.roots import resolve_roots, roots_for_source
from mdd.search.sources import (
    CONFLUENCE,
    SOURCES,
    RootSource,
    known_types_hint,
    register_root_source,
    registered_root_sources,
    root_source_for,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# A stand-in for what a wrapper registers (sbp-mdd registers `lucid` in
# exactly this shape, from its CLI entry point).
WIDGET = RootSource(
    source_type="widget",
    config_name="widget",
    section="widget",
    collection="folders",
    label="Widget",
)


@pytest.fixture
def widget_source() -> Iterator[RootSource]:
    """Register WIDGET for one test, then restore the built-in registry."""
    register_root_source(WIDGET)
    try:
        yield WIDGET
    finally:
        del SOURCES[WIDGET.source_type]


class TestRegistry:
    def test_builtins_are_registered(self) -> None:
        assert [s.source_type for s in registered_root_sources()] == [
            "confluence",
            "sharepoint",
            "docs",
        ]

    def test_lookup_is_case_insensitive(self) -> None:
        assert root_source_for("Confluence") is CONFLUENCE

    def test_unknown_type_raises_with_known_types(self) -> None:
        with pytest.raises(KeyError, match="confluence"):
            _ = root_source_for("nope")

    def test_duplicate_registration_raises(self) -> None:
        with pytest.raises(ValueError, match="already registered"):
            register_root_source(CONFLUENCE)

    def test_known_types_hint_lists_registered(self) -> None:
        hint = known_types_hint()
        assert "confluence" in hint
        assert "sharepoint" in hint
        assert "docs" in hint

    def test_core_ships_no_lucid_source(self) -> None:
        """The core has no Lucid integration, so it registers no Lucid roots."""
        assert "lucid" not in SOURCES


class TestRegisteredSourceParticipates:
    """A registered source is loaded and filtered like any built-in."""

    def _write_config(self, tmp_path: Path, mirror: Path) -> Path:
        config = tmp_path / "widget.yaml"
        config.write_text(
            textwrap.dedent(
                f"""\
                widget:
                  folders:
                    MyTeam:
                      output_dir: {mirror}
                """
            )
        )
        return config

    def test_roots_are_loaded(self, tmp_path: Path, widget_source: RootSource) -> None:
        mirror = tmp_path / "widget-mirror"
        mirror.mkdir()
        roots = roots_for_source(widget_source, self._write_config(tmp_path, mirror))
        assert len(roots) == 1
        assert roots[0].source_type == "widget"
        assert roots[0].mirror_name == "widget/MyTeam"
        assert roots[0].path == mirror

    def test_resolve_roots_includes_and_filters_it(
        self, tmp_path: Path, widget_source: RootSource
    ) -> None:
        mirror = tmp_path / "widget-mirror"
        mirror.mkdir()
        config_paths = {
            source.source_type: tmp_path / f"no-such-{source.source_type}.yaml"
            for source in registered_root_sources()
        }
        config_paths[widget_source.source_type] = self._write_config(tmp_path, mirror)

        assert [r.source_type for r in resolve_roots(config_paths=config_paths)] == ["widget"]
        assert resolve_roots(
            config_paths=config_paths, source_filters={"widget": ["myteam"]}
        ) == resolve_roots(config_paths=config_paths)
        assert resolve_roots(config_paths=config_paths, source_filters={"widget": ["other"]}) == []
