"""Tests for the typed frontmatter base layer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdd.utils.frontmatter import (
    FrontmatterModel,
    parse_json_mapping,
    parse_yaml_mapping,
    split_frontmatter,
)

# ---------------------------------------------------------------------------
# FrontmatterModel
# ---------------------------------------------------------------------------


class _Sample(FrontmatterModel):
    name: str
    count: int = 0
    tags: list[str] = []  # noqa: RUF012 — pydantic handles per-instance mutation


class TestFrontmatterModel:
    def test_basic_construction(self) -> None:
        m = _Sample.model_validate({"name": "x", "count": 3})
        assert m.name == "x"
        assert m.count == 3

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            _ = _Sample.model_validate({"name": "x", "spcae_key": "typo"})
        assert "spcae_key" in str(exc.value)

    def test_flexible_int_coercion(self) -> None:
        m = _Sample.model_validate({"name": "x", "count": "5"})
        assert m.count == 5

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValidationError):
            _ = _Sample.model_validate({"count": 1})


# ---------------------------------------------------------------------------
# split_frontmatter
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    def test_basic_split(self) -> None:
        text = "---\ntitle: x\n---\nbody\n"
        result = split_frontmatter(text)
        assert result == ("title: x", "body\n")

    def test_no_opening_fence(self) -> None:
        assert split_frontmatter("# Just markdown\n") is None

    def test_empty_string(self) -> None:
        assert split_frontmatter("") is None

    def test_crlf_opening_fence(self) -> None:
        text = "---\r\ntitle: x\n---\nbody"
        # The body / yaml block is preserved as-is once past the opening fence.
        result = split_frontmatter(text)
        assert result is not None
        yaml_block, body = result
        assert "title: x" in yaml_block
        assert body == "body"

    def test_trailing_fence_without_newline(self) -> None:
        text = "---\ntitle: x\n---"
        result = split_frontmatter(text)
        assert result == ("title: x", "")

    def test_unterminated_returns_none(self) -> None:
        assert split_frontmatter("---\ntitle: x\nbody only\n") is None


# ---------------------------------------------------------------------------
# parse_yaml_mapping
# ---------------------------------------------------------------------------


class TestParseYamlMapping:
    def test_basic_mapping(self) -> None:
        m = parse_yaml_mapping("a: 1\nb: x\n")
        assert m == {"a": 1, "b": "x"}

    def test_empty_string(self) -> None:
        assert parse_yaml_mapping("") is None

    def test_whitespace_only(self) -> None:
        assert parse_yaml_mapping("   \n  \n") is None

    def test_list_returns_none(self) -> None:
        assert parse_yaml_mapping("- a\n- b\n") is None

    def test_scalar_returns_none(self) -> None:
        assert parse_yaml_mapping("just-a-string") is None

    def test_null_returns_none(self) -> None:
        assert parse_yaml_mapping("null\n") is None

    def test_parse_error_returns_none(self) -> None:
        assert parse_yaml_mapping(": invalid: yaml: [") is None


# ---------------------------------------------------------------------------
# parse_json_mapping
# ---------------------------------------------------------------------------


class TestParseJsonMapping:
    def test_basic_mapping(self) -> None:
        m = parse_json_mapping('{"a": 1, "b": "x"}')
        assert m == {"a": 1, "b": "x"}

    def test_list_returns_none(self) -> None:
        assert parse_json_mapping("[1, 2, 3]") is None

    def test_scalar_returns_none(self) -> None:
        assert parse_json_mapping('"just a string"') is None

    def test_parse_error_returns_none(self) -> None:
        assert parse_json_mapping("{not valid json") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_json_mapping("") is None
