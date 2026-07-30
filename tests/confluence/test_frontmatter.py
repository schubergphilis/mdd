"""Tests for mdd.confluence.frontmatter"""

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from mdd.confluence.frontmatter import read, write


class TestRead:
    def test_file_with_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        path.write_text(
            "---\ntitle: Hello\ncount: 5\n---\nBody text\n",
            encoding="utf-8",
        )
        fm, body = read(path)
        assert fm == {"title": "Hello", "count": 5}
        assert "Body text" in body

    def test_file_without_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        path.write_text("Just a body\n", encoding="utf-8")
        fm, body = read(path)
        assert fm == {}
        assert body == "Just a body\n"

    def test_nested_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        path.write_text(
            "---\nconfluence:\n  page_id: '12345'\n  title: My Page\n---\nContent\n",
            encoding="utf-8",
        )
        fm, _body = read(path)
        assert isinstance(fm.get("confluence"), dict)
        conf = fm["confluence"]
        assert isinstance(conf, dict)
        assert conf["page_id"] == "12345"

    def test_empty_frontmatter_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        path.write_text("---\n---\nContent\n", encoding="utf-8")
        fm, _body = read(path)
        # yaml.safe_load("") returns None; should fall back to {}
        assert isinstance(fm, dict)


class TestWrite:
    def test_write_creates_file_with_fences(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        write(path, {"title": "Test"}, "Body content\n")
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "title: Test" in content
        assert "---\n" in content
        assert "Body content" in content

    def test_write_is_atomic_via_tmp(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        write(path, {"x": 1}, "body")
        # No .tmp file should remain
        tmp_file = path.with_suffix(".md.tmp")
        assert not tmp_file.exists()
        assert path.exists()

    def test_tmp_file_cleaned_up_on_write_failure(self, tmp_path: Path) -> None:
        """If writing the tmp file raises, no orphan .tmp must remain."""
        path = tmp_path / "page.md"
        tmp_file = path.with_suffix(".md.tmp")

        # Patch Path.open on the specific tmp_path instance to raise after the file
        # has been created (simulate a mid-write failure by patching fh.write).
        original_path_open = Path.open

        def failing_open(self: Path, *args: object, **kwargs: object) -> object:
            if self == tmp_file:
                raise OSError("disk full")
            return original_path_open(self, *args, **kwargs)  # type: ignore[arg-type]

        with patch.object(Path, "open", failing_open), pytest.raises(OSError, match="disk full"):
            write(path, {"x": 1}, "body")

        assert not tmp_file.exists()

    def test_tmp_file_cleaned_up_on_replace_failure(self, tmp_path: Path) -> None:
        """If os.replace raises, no orphan .tmp must remain."""

        path = tmp_path / "page.md"
        tmp_file = path.with_suffix(".md.tmp")

        with (
            patch("os.replace", side_effect=OSError("cross-device")),
            pytest.raises(OSError, match="cross-device"),
        ):
            write(path, {"x": 1}, "body")

        assert not tmp_file.exists()


class TestRoundTrip:
    def test_roundtrip_simple(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        fm_in = {"confluence": {"page_id": "99", "title": "Test"}, "labels": ["a", "b"]}
        body_in = "\nSome markdown\n"
        write(path, fm_in, body_in)
        fm_out, body_out = read(path)
        assert fm_out["confluence"] == fm_in["confluence"]  # type: ignore[index]
        assert "Some markdown" in body_out

    def test_roundtrip_preserves_none_values(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        fm_in: dict[str, object] = {"parent_id": None, "title": "Root"}
        write(path, fm_in, "content")
        fm_out, _ = read(path)
        assert fm_out.get("parent_id") is None

    def test_roundtrip_nested_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "page.md"
        fm_in = {
            "confluence": {
                "page_id": "123",
                "attachments": [{"filename": "img.png", "sha256": "abc", "version": 1}],
            }
        }
        write(path, fm_in, "text")
        fm_out, _ = read(path)
        conf_raw = fm_out.get("confluence")
        assert isinstance(conf_raw, dict)
        conf_d = cast("dict[str, object]", conf_raw)  # pyright: ignore[reportUnknownArgumentType]
        atts_raw: object = conf_d.get("attachments")
        assert isinstance(atts_raw, list)
        atts: list[object] = cast("list[object]", atts_raw)
        assert len(atts) >= 1
        first_raw: object = atts[0]
        assert isinstance(first_raw, dict)
        assert first_raw.get("filename") == "img.png"  # pyright: ignore[reportUnknownMemberType]
