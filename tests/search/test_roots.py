"""Tests for mdd.search.roots — mirror root resolution."""

from __future__ import annotations

import textwrap
import warnings
from typing import TYPE_CHECKING

from mdd.search.roots import resolve_roots, roots_for_source
from mdd.search.sources import CONFLUENCE, DOCS, SHAREPOINT, registered_root_sources

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# roots_for_source
# ---------------------------------------------------------------------------


class TestConfluenceRoots:
    def test_returns_roots_for_existing_dirs(self, tmp_path: Path) -> None:
        mirror = tmp_path / "confluence-mirror"
        mirror.mkdir()
        config = tmp_path / "confluence.yaml"
        config.write_text(
            textwrap.dedent(
                f"""\
                confluence:
                  spaces:
                    ENGINEERING:
                      output_dir: {mirror}
                """
            )
        )
        roots = roots_for_source(CONFLUENCE, config)
        assert len(roots) == 1
        assert roots[0].source_type == "confluence"
        assert roots[0].identifier == "ENGINEERING"
        assert roots[0].mirror_name == "confluence/ENGINEERING"
        assert roots[0].path == mirror

    def test_skips_missing_dirs_with_warning(self, tmp_path: Path) -> None:
        config = tmp_path / "confluence.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                confluence:
                  spaces:
                    MISSING:
                      output_dir: /this/does/not/exist/hopefully
                """
            )
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            roots = roots_for_source(CONFLUENCE, config)
        assert roots == []
        assert any(
            "MISSING" in str(warning.message) or "not exist" in str(warning.message).lower()
            for warning in w
        )
        assert any("Confluence" in str(warning.message) for warning in w)

    def test_returns_empty_when_no_config(self, tmp_path: Path) -> None:
        # Pass a path that doesn't exist
        roots = roots_for_source(CONFLUENCE, tmp_path / "nonexistent.yaml")
        assert roots == []

    def test_returns_empty_when_no_spaces_key(self, tmp_path: Path) -> None:
        config = tmp_path / "confluence.yaml"
        config.write_text("confluence:\n  url: https://example.com\n")
        roots = roots_for_source(CONFLUENCE, config)
        assert roots == []

    def test_multiple_spaces(self, tmp_path: Path) -> None:
        d1 = tmp_path / "space1"
        d1.mkdir()
        d2 = tmp_path / "space2"
        d2.mkdir()
        config = tmp_path / "confluence.yaml"
        config.write_text(
            textwrap.dedent(
                f"""\
                confluence:
                  spaces:
                    ENG:
                      output_dir: {d1}
                    HR:
                      output_dir: {d2}
                """
            )
        )
        roots = roots_for_source(CONFLUENCE, config)
        identifiers = {r.identifier for r in roots}
        assert identifiers == {"ENG", "HR"}


class TestSharepointRoots:
    def test_returns_roots_for_existing_dirs(self, tmp_path: Path) -> None:
        mirror = tmp_path / "sp-mirror"
        mirror.mkdir()
        config = tmp_path / "sharepoint.yaml"
        config.write_text(
            textwrap.dedent(
                f"""\
                sharepoint:
                  sites:
                    Engineering:
                      output_dir: {mirror}
                """
            )
        )
        roots = roots_for_source(SHAREPOINT, config)
        assert len(roots) == 1
        assert roots[0].source_type == "sharepoint"
        assert roots[0].identifier == "Engineering"
        assert roots[0].mirror_name == "sharepoint/Engineering"

    def test_skips_missing_dirs(self, tmp_path: Path) -> None:
        config = tmp_path / "sharepoint.yaml"
        config.write_text(
            "sharepoint:\n  sites:\n    Appraisals:\n      output_dir: /no/such/path\n"
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            roots = roots_for_source(SHAREPOINT, config)
        assert roots == []
        assert len(w) >= 1

    def test_returns_empty_when_no_config(self, tmp_path: Path) -> None:
        roots = roots_for_source(SHAREPOINT, tmp_path / "nonexistent.yaml")
        assert roots == []


class TestDocsRoots:
    """The `docs` source has no nested collection key — the section is the mapping."""

    def test_reads_flat_section(self, tmp_path: Path) -> None:
        mirror = tmp_path / "docs-mirror"
        mirror.mkdir()
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                f"""\
                docs:
                  my-repo:
                    output_dir: {mirror}
                """
            )
        )
        roots = roots_for_source(DOCS, config)
        assert len(roots) == 1
        assert roots[0].source_type == "docs"
        assert roots[0].identifier == "my-repo"
        assert roots[0].mirror_name == "docs/my-repo"


# ---------------------------------------------------------------------------
# resolve_roots
# ---------------------------------------------------------------------------


class TestResolveRoots:
    def _config_paths(self, tmp_path: Path, **overrides: Path) -> dict[str, Path]:
        """Pin every registered source, so auto-discovery can't leak the dev box in."""
        paths = {
            source.source_type: tmp_path / f"no-such-{source.source_type}.yaml"
            for source in registered_root_sources()
        }
        paths.update(overrides)
        return paths

    def _make_confluence_config(self, tmp_path: Path, spaces: dict[str, Path]) -> Path:
        lines = ["confluence:", "  spaces:"]
        for key, path in spaces.items():
            lines.append(f"    {key}:")
            lines.append(f"      output_dir: {path}")
        config = tmp_path / "confluence.yaml"
        config.write_text("\n".join(lines) + "\n")
        return config

    def _make_sharepoint_config(self, tmp_path: Path, sites: dict[str, Path]) -> Path:
        lines = ["sharepoint:", "  sites:"]
        for key, path in sites.items():
            lines.append(f"    {key}:")
            lines.append(f"      output_dir: {path}")
        config = tmp_path / "sharepoint.yaml"
        config.write_text("\n".join(lines) + "\n")
        return config

    def test_combines_confluence_and_sharepoint(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        s_dir = tmp_path / "s"
        s_dir.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        s_conf = self._make_sharepoint_config(tmp_path, {"Labs": s_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf, sharepoint=s_conf)
        )
        types = {r.source_type for r in roots}
        assert types == {"confluence", "sharepoint"}

    def test_space_filter_restricts_confluence(self, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        d2 = tmp_path / "d2"
        d2.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": d1, "HR": d2})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf),
            source_filters={"confluence": ["ENG"]},
        )
        assert [r.identifier for r in roots] == ["ENG"]

    def test_filter_matching_is_case_insensitive(self, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": d1})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf),
            source_filters={"confluence": ["eng"]},
        )
        assert [r.identifier for r in roots] == ["ENG"]

    def test_site_filter_restricts_sharepoint(self, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d1.mkdir()
        d2 = tmp_path / "d2"
        d2.mkdir()
        s_conf = self._make_sharepoint_config(tmp_path, {"Labs": d1, "Engineering": d2})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, sharepoint=s_conf),
            source_filters={"sharepoint": ["Labs"]},
        )
        assert [r.identifier for r in roots] == ["Labs"]

    def test_site_filter_excludes_other_sources(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        s_dir = tmp_path / "s"
        s_dir.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        s_conf = self._make_sharepoint_config(tmp_path, {"AI": s_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf, sharepoint=s_conf),
            source_filters={"sharepoint": ["AI"]},
        )
        assert {r.source_type for r in roots} == {"sharepoint"}
        assert [r.identifier for r in roots] == ["AI"]

    def test_space_filter_excludes_other_sources(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        s_dir = tmp_path / "s"
        s_dir.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        s_conf = self._make_sharepoint_config(tmp_path, {"Labs": s_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf, sharepoint=s_conf),
            source_filters={"confluence": ["Labs"]},
        )
        # "Labs" is a sharepoint site, not a confluence space — no roots match.
        assert roots == []

    def test_combined_space_and_site_filter(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        s_dir = tmp_path / "s"
        s_dir.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        s_conf = self._make_sharepoint_config(tmp_path, {"AI": s_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf, sharepoint=s_conf),
            source_filters={"confluence": ["ENG"], "sharepoint": ["AI"]},
        )
        assert {r.source_type for r in roots} == {"confluence", "sharepoint"}

    def test_empty_filter_lists_do_not_filter(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf),
            source_filters={"confluence": [], "sharepoint": []},
        )
        assert [r.identifier for r in roots] == ["ENG"]

    def test_filter_keeps_extra_paths(self, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        c_dir.mkdir()
        extra = tmp_path / "extra"
        extra.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": c_dir})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf),
            source_filters={"sharepoint": ["AI"]},
            extra_paths=[extra],
        )
        # confluence dropped (no --space), sharepoint absent — only the extra path remains.
        assert [r.source_type for r in roots] == ["extra"]
        assert roots[0].path == extra

    def test_extra_paths_added(self, tmp_path: Path) -> None:
        extra = tmp_path / "extra"
        extra.mkdir()
        roots = resolve_roots(config_paths=self._config_paths(tmp_path), extra_paths=[extra])
        assert any(r.path == extra for r in roots)

    def test_extra_path_missing_warns(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-dir"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            roots = resolve_roots(config_paths=self._config_paths(tmp_path), extra_paths=[missing])
        assert not any(r.path == missing for r in roots)
        assert len(w) >= 1

    def test_exclude_paths_removes_root(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        c_conf = self._make_confluence_config(tmp_path, {"ENG": d})
        roots = resolve_roots(
            config_paths=self._config_paths(tmp_path, confluence=c_conf), exclude_paths=[d]
        )
        assert not any(r.path.resolve() == d.resolve() for r in roots)

    def test_returns_empty_with_no_config(self, tmp_path: Path) -> None:
        # No config for any registered source and no explicit paths
        roots = resolve_roots(config_paths=self._config_paths(tmp_path))
        assert roots == []
