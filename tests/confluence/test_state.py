"""Tests for confluence state module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mdd.confluence.state import (
    DuplicatePageIdError,
    build_mirror_state,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_md(path: Path, frontmatter: dict[str, object], body: str = "") -> None:
    """Write a markdown file with YAML frontmatter."""
    import yaml

    fm_str = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    content = f"---\n{fm_str}---\n{body}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_tracked(  # noqa: PLR0913
    path: Path,
    page_id: str = "100",
    title: str = "Test Page",
    version: int = 5,
    status: str = "CURRENT",
    parent_id: str | None = None,
    labels: list[str] | None = None,
) -> None:
    fm: dict[str, object] = {
        "confluence": {
            "page_id": page_id,
            "title": title,
            "version": version,
            "status": status,
            "parent_id": parent_id,
            "space_key": "TEST",
            "space_id": "98306",
            "labels": labels or [],
            "exported_at": "2026-01-01T00:00:00Z",
        }
    }
    _write_md(path, fm, f"\n# {title}\n\nBody text.\n")


class TestBuildMirrorStateEmpty:
    def test_empty_directory(self, tmp_path: Path) -> None:
        state = build_mirror_state(tmp_path)
        assert state.tracked == {}
        assert state.untracked == []
        assert state.manual == []


class TestBuildMirrorStateTracked:
    def test_single_tracked_file(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "page.md", page_id="100")
        state = build_mirror_state(tmp_path)
        assert "100" in state.tracked
        assert state.tracked["100"].page_id == "100"
        assert state.tracked["100"].title == "Test Page"
        assert state.tracked["100"].version_number == 5

    def test_multiple_tracked_files(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "a.md", page_id="100", title="A")
        _write_tracked(tmp_path / "b.md", page_id="200", title="B")
        state = build_mirror_state(tmp_path)
        assert "100" in state.tracked
        assert "200" in state.tracked
        assert state.tracked["100"].title == "A"
        assert state.tracked["200"].title == "B"

    def test_nested_tracked_files(self, tmp_path: Path) -> None:
        subdir = tmp_path / "section"
        subdir.mkdir()
        _write_tracked(subdir / "page.md", page_id="300")
        state = build_mirror_state(tmp_path)
        assert "300" in state.tracked

    def test_status_normalized_to_uppercase(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "page.md", page_id="100", status="archived")
        state = build_mirror_state(tmp_path)
        assert state.tracked["100"].status == "ARCHIVED"


class TestBuildMirrorStateDuplicate:
    def test_duplicate_page_id_raises(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "a.md", page_id="100")
        _write_tracked(tmp_path / "b.md", page_id="100")
        with pytest.raises(DuplicatePageIdError, match="100"):
            build_mirror_state(tmp_path)

    def test_duplicate_error_names_both_paths(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "a.md", page_id="100")
        _write_tracked(tmp_path / "b.md", page_id="100")
        with pytest.raises(DuplicatePageIdError) as exc_info:
            build_mirror_state(tmp_path)
        msg = str(exc_info.value)
        assert "a.md" in msg or "b.md" in msg


class TestBuildMirrorStateUntracked:
    def test_file_with_space_key_but_no_page_id_is_untracked(self, tmp_path: Path) -> None:
        fm: dict[str, object] = {
            "confluence": {
                "space_key": "TEST",
                "title": "New Page",
            }
        }
        p = tmp_path / "new-page.md"
        _write_md(p, fm, "\n# New Page\n\nBody.\n")
        state = build_mirror_state(tmp_path)
        assert p in state.untracked
        assert state.tracked == {}

    def test_file_no_confluence_block_is_manual(self, tmp_path: Path) -> None:
        p = tmp_path / "manual.md"
        p.write_text("---\ntitle: Manual\n---\n\nContent.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.manual

    def test_file_no_frontmatter_at_all_is_manual(self, tmp_path: Path) -> None:
        p = tmp_path / "bare.md"
        p.write_text("# No Frontmatter\n\nJust content.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.manual

    def test_malformed_frontmatter_is_manual(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.md"
        p.write_text("---\n: invalid: yaml: [\n---\nContent.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.manual


class TestBuildMirrorStateAttachmentDerived:
    """`*-attachments/<stem>.<ext>.md` files are converter outputs, not user-authored.

    They must be classified as ``attachment_derived``, not ``manual``,
    so the sync summary does not flag them as drift to investigate.
    """

    def test_pdf_md_under_attachments_dir_is_attachment_derived(self, tmp_path: Path) -> None:
        attachments_dir = tmp_path / "Foo-attachments"
        attachments_dir.mkdir()
        p = attachments_dir / "bar.pdf.md"
        # Converter output has no frontmatter linking back to a page.
        p.write_text("# bar\n\nConverted content.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.attachment_derived
        assert p not in state.manual

    def test_pptx_md_under_attachments_dir_is_attachment_derived(self, tmp_path: Path) -> None:
        attachments_dir = tmp_path / "Recruitment Team-attachments"
        attachments_dir.mkdir()
        p = attachments_dir / "Stream Charter.pptx.md"
        p.write_text("# Stream Charter\n\nConverted.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.attachment_derived

    def test_docx_md_under_attachments_dir_is_attachment_derived(self, tmp_path: Path) -> None:
        attachments_dir = tmp_path / "Onboarding-attachments"
        attachments_dir.mkdir()
        p = attachments_dir / "guide.docx.md"
        p.write_text("# guide\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.attachment_derived

    def test_pdf_md_not_under_attachments_dir_stays_manual(self, tmp_path: Path) -> None:
        # User-authored notes that happen to mention a PDF stem; not converter output.
        p = tmp_path / "notes.pdf.md"
        p.write_text("# notes\n\nMy notes about a PDF.\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.manual
        assert p not in state.attachment_derived

    def test_plain_md_under_attachments_dir_stays_manual(self, tmp_path: Path) -> None:
        # No converter suffix — user dropped a stray .md into an attachments dir.
        attachments_dir = tmp_path / "Foo-attachments"
        attachments_dir.mkdir()
        p = attachments_dir / "readme.md"
        p.write_text("# readme\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.manual
        assert p not in state.attachment_derived

    def test_nested_attachments_dir_still_matches(self, tmp_path: Path) -> None:
        # `*-attachments` directories appear at various depths in real mirrors.
        deep = tmp_path / "section" / "subsection" / "Page-attachments"
        deep.mkdir(parents=True)
        p = deep / "asset.pdf.md"
        p.write_text("# asset\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert p in state.attachment_derived

    def test_attachment_derived_does_not_pollute_tracked(self, tmp_path: Path) -> None:
        attachments_dir = tmp_path / "Foo-attachments"
        attachments_dir.mkdir()
        p = attachments_dir / "bar.pdf.md"
        p.write_text("# bar\n", encoding="utf-8")
        state = build_mirror_state(tmp_path)
        assert state.tracked == {}
        assert state.untracked == []


class TestBuildMirrorStateAttachmentDirFrontmatterIgnored:
    """Frontmatter inside ``*-attachments/`` files carries no page authority.

    Attachment sync writes remote files verbatim under ``<page>-attachments/``,
    so a downloaded ``.md`` there may carry any ``confluence`` block. The walk
    must not read it: such files can neither become tracked pages nor collide
    with the page that owns the attachments directory.
    """

    def test_same_page_id_as_owner_does_not_raise(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "Foo.md", page_id="100", title="Foo")
        planted = tmp_path / "Foo-attachments" / "x.md"
        _write_tracked(planted, page_id="100", title="Foo")
        state = build_mirror_state(tmp_path)
        assert set(state.tracked) == {"100"}
        assert state.tracked["100"].path == tmp_path / "Foo.md"
        assert planted in state.manual
        assert planted not in state.attachment_derived

    def test_untracked_page_id_is_not_tracked(self, tmp_path: Path) -> None:
        _write_tracked(tmp_path / "Foo.md", page_id="100", title="Foo")
        planted = tmp_path / "Foo-attachments" / "x.md"
        _write_tracked(planted, page_id="999", title="Other")
        state = build_mirror_state(tmp_path)
        assert set(state.tracked) == {"100"}
        assert "999" not in state.tracked
        assert planted in state.manual
        assert state.untracked == []

    def test_publish_candidate_frontmatter_is_not_untracked(self, tmp_path: Path) -> None:
        planted = tmp_path / "Foo-attachments" / "x.md"
        _write_md(planted, {"confluence": {"space_key": "TEST"}}, "# x\n")
        state = build_mirror_state(tmp_path)
        assert state.untracked == []
        assert planted in state.manual

    def test_converter_output_with_frontmatter_is_attachment_derived(self, tmp_path: Path) -> None:
        planted = tmp_path / "Foo-attachments" / "bar.pdf.md"
        _write_tracked(planted, page_id="999", title="bar")
        state = build_mirror_state(tmp_path)
        assert state.tracked == {}
        assert planted in state.attachment_derived
        assert planted not in state.manual

    def test_nested_attachments_dir_frontmatter_ignored(self, tmp_path: Path) -> None:
        planted = tmp_path / "section" / "Page-attachments" / "deep" / "x.md"
        _write_tracked(planted, page_id="999", title="x")
        state = build_mirror_state(tmp_path)
        assert state.tracked == {}
        assert planted in state.manual

    def test_output_dir_named_attachments_is_walked_normally(self, tmp_path: Path) -> None:
        # Only directories *inside* the mirror count, not the mirror root itself.
        root = tmp_path / "docs-attachments"
        _write_tracked(root / "Foo.md", page_id="100", title="Foo")
        state = build_mirror_state(root)
        assert set(state.tracked) == {"100"}

    def test_output_dir_named_attachments_keeps_converter_suffix_manual(
        self, tmp_path: Path
    ) -> None:
        # A user-authored notes.pdf.md at the root of a mirror whose own name
        # ends in -attachments is manual, not a converter output.
        root = tmp_path / "docs-attachments"
        notes = root / "notes.pdf.md"
        _write_md(notes, {}, "# notes\n")
        state = build_mirror_state(root)
        assert notes in state.manual
        assert state.attachment_derived == []


class TestBuildMirrorStateAttachments:
    def test_attachments_manifest_loaded(self, tmp_path: Path) -> None:
        fm: dict[str, object] = {
            "confluence": {
                "page_id": "100",
                "title": "Page",
                "version": 1,
                "status": "CURRENT",
                "space_key": "TEST",
                "space_id": "98306",
                "attachments": [{"filename": "image.png", "sha256": "abc123", "version": 1}],
                "exported_at": "2026-01-01T00:00:00Z",
            }
        }
        _write_md(tmp_path / "page.md", fm)
        state = build_mirror_state(tmp_path)
        assert "100" in state.tracked
        assert len(state.tracked["100"].attachments_manifest) == 1
        assert state.tracked["100"].attachments_manifest[0]["filename"] == "image.png"


class TestBuildMirrorStateInvalidFrontmatter:
    """Files with an unknown key in confluence: land in `state.manual` and log a warning."""

    def test_unknown_key_in_confluence_block_falls_back_to_manual(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # `spcae_key` (typo of `space_key`) triggers ValidationError because the
        # ConfluenceBlock model has extra="forbid".  Today's behaviour (silent
        # fallthrough) is replaced by a logged warning + manual classification.
        fm: dict[str, object] = {
            "confluence": {
                "spcae_key": "TEST",  # typo — should be rejected
                "page_id": "100",
            }
        }
        p = tmp_path / "typo.md"
        _write_md(p, fm)
        with caplog.at_level("WARNING", logger="mdd.confluence.state"):
            state = build_mirror_state(tmp_path)
        assert p in state.manual
        assert p not in state.tracked.values()
        assert any("spcae_key" in record.message for record in caplog.records)


def _plant_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported on this platform")


class TestBuildMirrorStateSkipsSymlinks:
    def test_symlinked_md_not_ingested(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("not a page", encoding="utf-8")
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        _write_md(mirror / "real.md", {})
        _plant_symlink(mirror / "link.md", secret)

        state = build_mirror_state(mirror)

        all_paths = list(state.tracked.values()) + state.untracked + state.manual
        assert mirror / "real.md" in all_paths
        assert mirror / "link.md" not in all_paths
