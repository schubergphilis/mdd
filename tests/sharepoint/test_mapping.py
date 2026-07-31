"""Tests for mdd.sharepoint.mapping — normalization and mapping override."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from mdd.sharepoint.mapping import MappingEntry, load_mapping, normalize, repo_name

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestNormalize:
    def test_spaces_replaced(self) -> None:
        assert normalize("HR Documentation") == "HR-Documentation"

    def test_slash_replaced(self) -> None:
        assert normalize("AI / ML Team") == "AI-ML-Team"

    def test_parens_preserved(self) -> None:
        # Parens are not in the forbidden set
        assert normalize("Q4 (2025) Plans") == "Q4-(2025)-Plans"

    def test_case_preserved(self) -> None:
        result = normalize("HR Documentation")
        assert "HR" in result
        assert "Documentation" in result

    def test_leading_trailing_dash_stripped(self) -> None:
        # Input starting/ending with special char
        assert not normalize("/ Test /").startswith("-")
        assert not normalize("/ Test /").endswith("-")

    def test_run_of_spaces(self) -> None:
        assert normalize("A  B") == "A-B"

    def test_multiple_special_chars_become_one_dash(self) -> None:
        assert normalize("A / \\ : * B") == "A-B"

    def test_already_clean(self) -> None:
        assert normalize("Engineering") == "Engineering"

    def test_backslash_replaced(self) -> None:
        assert normalize("A\\B") == "A-B"

    def test_colon_replaced(self) -> None:
        assert normalize("Q4: Plans") == "Q4-Plans"

    def test_question_mark_replaced(self) -> None:
        assert normalize("What?") == "What"

    def test_angle_brackets_replaced(self) -> None:
        assert normalize("A<B>C") == "A-B-C"

    def test_pipe_replaced(self) -> None:
        assert normalize("A|B") == "A-B"

    def test_trim_whitespace(self) -> None:
        assert normalize("  Engineering  ") == "Engineering"


class TestLoadMapping:
    # --- Legacy list format ---

    def test_empty_list_returns_empty_dict(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        mapping_file.write_text("sites: []\n")
        result = load_mapping(mapping_file)
        assert result == {}

    def test_legacy_explicit_entry_loaded(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        data = {"sites": [{"site_name": "AI / ML Team", "repo_name": "AI-ML-Team"}]}
        mapping_file.write_text(yaml.safe_dump(data))
        result = load_mapping(mapping_file)
        assert "AI / ML Team" in result
        assert result["AI / ML Team"].repo_name == "AI-ML-Team"

    def test_legacy_multiple_entries(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        data = {
            "sites": [
                {"site_name": "HR Documentation", "repo_name": "HR-Documentation"},
                {"site_name": "Engineering", "repo_name": "Engineering"},
            ]
        }
        mapping_file.write_text(yaml.safe_dump(data))
        result = load_mapping(mapping_file)
        assert len(result) == 2
        assert result["HR Documentation"].repo_name == "HR-Documentation"

    # --- dict-keyed format ---

    def test_spec_empty_dict_returns_empty(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        mapping_file.write_text("sites: {}\n")
        result = load_mapping(mapping_file)
        assert result == {}

    def test_spec_dict_format_loaded(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        content = "sites:\n  HR Documentation:\n    repo: HR-Documentation\n"
        mapping_file.write_text(content)
        result = load_mapping(mapping_file)
        assert "HR Documentation" in result
        assert result["HR Documentation"].repo_name == "HR-Documentation"

    def test_spec_dict_format_multiple_entries(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        content = (
            "sites:\n"
            "  HR Documentation:\n"
            "    repo: HR-Documentation\n"
            "  Engineering:\n"
            "    repo: Engineering\n"
        )
        mapping_file.write_text(content)
        result = load_mapping(mapping_file)
        assert len(result) == 2
        assert result["Engineering"].repo_name == "Engineering"

    def test_spec_dict_missing_repo_key_skipped(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "sharepoint-mapping.yaml"
        content = "sites:\n  HR Documentation: {}\n"
        mapping_file.write_text(content)
        result = load_mapping(mapping_file)
        assert result == {}

    # --- Common ---

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = load_mapping(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_no_arg_no_default_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure no local configs/sharepoint-mapping.yaml and no user config
        monkeypatch.chdir(tmp_path)
        result = load_mapping()
        assert result == {}

    def test_local_default_picked_up(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        mapping_file = configs_dir / "sharepoint-mapping.yaml"
        content = "sites:\n  Test:\n    repo: test-repo\n"
        mapping_file.write_text(content)
        result = load_mapping()
        assert "Test" in result

    def test_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "bad.yaml"
        mapping_file.write_text("{ invalid yaml }: [")
        result = load_mapping(mapping_file)
        assert result == {}

    def test_non_dict_yaml_returns_empty(self, tmp_path: Path) -> None:
        mapping_file = tmp_path / "list.yaml"
        mapping_file.write_text("- just a list\n")
        result = load_mapping(mapping_file)
        assert result == {}


class TestRepoName:
    def test_explicit_entry_wins(self) -> None:
        mapping = {"AI / ML Team": MappingEntry(site_name="AI / ML Team", repo_name="AI-ML-Team")}
        result = repo_name("AI / ML Team", mapping)
        assert result == "AI-ML-Team"

    def test_falls_back_to_normalize(self) -> None:
        result = repo_name("HR Documentation", {})
        assert result == "HR-Documentation"

    def test_fallback_for_unmapped_site(self) -> None:
        mapping = {"Other Site": MappingEntry(site_name="Other Site", repo_name="Other-Site")}
        result = repo_name("New Site", mapping)
        assert result == "New-Site"
