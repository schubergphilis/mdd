"""Tests for the shared write path: mirror refusal and the atomic replace."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mdd.prose.config import ProseConfig
from mdd.prose.write import atomic_write, mirror_finding, mirror_reason

if TYPE_CHECKING:
    from pathlib import Path

CONFLUENCE = "---\nconfluence:\n  page_id: '123'\n---\n\nBody.\n"
SHAREPOINT = "---\nsharepoint:\n  sync:\n    md_sha256_at_sync: abc\n---\n\nBody.\n"


def test_authored_file_is_not_a_mirror() -> None:
    assert mirror_reason("---\ntitle: a\n---\n\nBody.\n") is None
    assert mirror_reason("Body only.\n") is None


def test_confluence_page_id_marks_a_mirror() -> None:
    assert mirror_reason(CONFLUENCE) == "confluence.page_id"


def test_sharepoint_sync_block_marks_a_mirror() -> None:
    assert mirror_reason(SHAREPOINT) == "sharepoint.sync"


def test_confluence_section_without_a_page_id_is_not_a_mirror() -> None:
    assert mirror_reason("---\nconfluence:\n  space: DOCS\n---\n") is None


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(CONFLUENCE.replace("\n", "\r\n"), id="crlf"),
        pytest.param(CONFLUENCE.replace("\n", "\r"), id="cr-only"),
        pytest.param("\ufeff" + CONFLUENCE, id="bom"),
        pytest.param("\ufeff" + CONFLUENCE.replace("\n", "\r\n"), id="bom-crlf"),
    ],
)
def test_mirror_is_recognised_whatever_the_line_endings(text: str) -> None:
    assert mirror_reason(text) == "confluence.page_id"


def test_sharepoint_mirror_with_cr_only_line_endings() -> None:
    assert mirror_reason(SHAREPOINT.replace("\n", "\r")) == "sharepoint.sync"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("---\n: : :\n---\n", id="bad-yaml"),
        pytest.param("---\n- a list\n---\n\nBody.\n", id="not-a-mapping"),
        pytest.param("---\nconfluence:\n  page_id: 1\n", id="never-closes"),
        pytest.param("---\r\n: : :\r\n---\r\n", id="bad-yaml-crlf"),
    ],
)
def test_unreadable_frontmatter_is_refused_as_a_possible_mirror(text: str) -> None:
    reason = mirror_reason(text)
    assert reason is not None
    assert "cannot be parsed" in reason


def test_empty_frontmatter_is_not_a_mirror() -> None:
    assert mirror_reason("---\n---\n\nBody.\n") is None
    assert mirror_reason("---\n\n---\n\nBody.\n") is None


def test_mirror_finding_names_the_override(tmp_path: Path) -> None:
    finding = mirror_finding(tmp_path / "a.md", "reflow", "confluence.page_id", ProseConfig())
    assert finding.rule == "mirrored-file"
    assert "--allow-mirror" in finding.message
    assert "reflow" in finding.message


def test_atomic_write_replaces_the_file(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("old\n", encoding="utf-8")
    atomic_write(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_preserves_crlf(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    atomic_write(target, "a\r\nb\r\n")
    assert target.read_bytes() == b"a\r\nb\r\n"


def test_atomic_write_cleans_up_its_temp_file_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "a.md"
    with pytest.raises(OSError, match="No such file"):
        atomic_write(target, "x")
    assert not list(tmp_path.iterdir())
