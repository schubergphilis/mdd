"""Tests for mdd.utils.blacklist."""

import subprocess
import textwrap
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mdd.utils.blacklist import (
    BlacklistConfigError,
    BlacklistError,
    SourceSystem,
    _matches,  # pyright: ignore[reportPrivateUsage]
    _pattern_source,  # pyright: ignore[reportPrivateUsage]
    check_confluence,
    check_sharepoint,
    detect_source_system,
    gate_push,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_blacklist_discovery(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Stop the real repo-bundled and ~/.config blacklists from leaking in.

    Without this, ``find_blacklist_files`` loads the actual checked-out
    ``configs/data-protection.yaml`` (and any user file), which would union
    with the per-test fixture and break "safe site" / "missing key" assertions.
    """
    monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: None)
    monkeypatch.setattr("mdd.utils.config.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_git_result(url: str) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = url + "\n"
    m.stderr = ""
    return m


def _make_git_fail() -> MagicMock:
    m = MagicMock()
    m.returncode = 128
    m.stdout = ""
    m.stderr = "fatal: No such remote 'origin'"
    return m


# ---------------------------------------------------------------------------
# _matches
# ---------------------------------------------------------------------------


class TestMatches:
    def test_exact_match_case_insensitive(self) -> None:
        assert _matches("Council", ["council"]) == "council"

    def test_exact_match_no_hit(self) -> None:
        assert _matches("Labs", ["Council"]) is None

    def test_prefix_wildcard_match(self) -> None:
        assert _matches("Appraisals - Alice", ["Appraisal*"]) == "Appraisal*"

    def test_prefix_wildcard_no_hit(self) -> None:
        assert _matches("Labs", ["Appraisal*"]) is None

    def test_leading_star_treated_as_literal(self) -> None:
        # A leading * has no special semantics — it's a literal string match.
        assert _matches("*something", ["*something"]) == "*something"
        assert _matches("something", ["*something"]) is None

    def test_internal_star_treated_as_literal(self) -> None:
        assert _matches("foo*bar", ["foo*bar"]) == "foo*bar"
        assert _matches("foobar", ["foo*bar"]) is None


# ---------------------------------------------------------------------------
# check_confluence
# ---------------------------------------------------------------------------


@pytest.fixture
def blacklist_file(tmp_path: Path) -> Path:
    f = tmp_path / "data-protection.yaml"
    f.write_text(
        textwrap.dedent(
            """\
            confluence:
              blacklisted_spaces:
                - HRPRIV
                - "Legal*"
            sharepoint:
              blacklisted_sites:
                - Council
                - "Appraisal*"
            """
        )
    )
    return f


class TestCheckConfluence:
    def test_missing_confluence_key_raises_config_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bl.yaml"
        f.write_text("sharepoint:\n  blacklisted_sites: []\n")
        with pytest.raises(BlacklistConfigError, match="confluence"):
            check_confluence("HRPRIV", blacklist_file=f)

    def test_blacklisted_space_raises_blacklist_error(self, blacklist_file: Path) -> None:
        with pytest.raises(BlacklistError, match="HRPRIV"):
            check_confluence("HRPRIV", blacklist_file=blacklist_file)

    def test_safe_space_returns_none(self, blacklist_file: Path) -> None:
        # Should not raise
        check_confluence("ENGINEERING", blacklist_file=blacklist_file)

    def test_prefix_match_raises_blacklist_error(self, blacklist_file: Path) -> None:
        with pytest.raises(BlacklistError, match="Legal"):
            check_confluence("LegalAdvice", blacklist_file=blacklist_file)

    def test_refusal_names_the_declaring_file(self, blacklist_file: Path) -> None:
        """The operator has to know which of the merged files to edit."""
        with pytest.raises(BlacklistError, match=str(blacklist_file)):
            check_confluence("HRPRIV", blacklist_file=blacklist_file)

    def test_no_blacklist_file_anywhere_raises_config_error(self) -> None:
        """Fail closed: an absent data-protection config is not an allow-all."""
        with pytest.raises(BlacklistConfigError, match="No data-protection blacklist found"):
            check_confluence("ENGINEERING")

    def test_no_blacklist_message_is_actionable(self) -> None:
        """The refusal has to tell someone with no config what file to write.

        A packaged install carries no bundled blacklist, so this message is
        the whole of what such a user gets. It must name the per-user path and
        both required sections, and must not offer a flag the gated commands
        do not have.
        """
        with pytest.raises(BlacklistConfigError) as exc_info:
            check_confluence("ENGINEERING")
        msg = str(exc_info.value)
        assert "~/.config/mdd/data-protection.yaml" in msg
        assert "blacklisted_spaces: []" in msg
        assert "blacklisted_sites: []" in msg
        # Only `mdd search` accepts --blacklist; suggesting it here sends a
        # sync-space or sync-site user after a flag that does not exist.
        assert "--blacklist" not in msg


class TestPatternSource:
    """Naming the declaring file is best-effort and must never mask the refusal."""

    def test_names_the_file_that_declares_the_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_file = tmp_path / "repo.yaml"
        repo_file.write_text("confluence:\n  blacklisted_spaces:\n    - REPOONLY\n")
        explicit = tmp_path / "extra.yaml"
        explicit.write_text("confluence:\n  blacklisted_spaces:\n    - EXTRAONLY\n")
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: repo_file)
        assert _pattern_source("confluence", "blacklisted_spaces", "REPOONLY", explicit) == str(
            repo_file
        )
        assert _pattern_source("confluence", "blacklisted_spaces", "EXTRAONLY", explicit) == str(
            explicit
        )

    def test_no_file_found_falls_back_to_generic_phrase(self) -> None:
        assert (
            _pattern_source("confluence", "blacklisted_spaces", "HRPRIV", None)
            == "the data-protection config"
        )

    def test_unparseable_file_is_skipped(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.yaml"
        broken.write_text("confluence: [this is not a mapping\n")
        assert (
            _pattern_source("confluence", "blacklisted_spaces", "HRPRIV", broken)
            == "the data-protection config"
        )

    def test_malformed_section_is_skipped(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("confluence: a string, not a mapping\n")
        assert (
            _pattern_source("confluence", "blacklisted_spaces", "HRPRIV", bad)
            == "the data-protection config"
        )

    def test_pattern_absent_from_every_file_falls_back(self, blacklist_file: Path) -> None:
        assert (
            _pattern_source("confluence", "blacklisted_spaces", "NOTTHERE", blacklist_file)
            == "the data-protection config"
        )


class TestCheckConfluenceUnknownSpace:
    """An empty space key means the caller could not identify the space."""

    def test_unknown_space_refused_when_any_space_is_blacklisted(
        self, blacklist_file: Path
    ) -> None:
        with pytest.raises(BlacklistError, match="Could not determine which Confluence space"):
            check_confluence("", blacklist_file=blacklist_file)

    def test_unknown_space_allowed_when_blacklist_is_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "bl.yaml"
        f.write_text("confluence:\n  blacklisted_spaces: []\n")
        # Nothing is protected, so nothing needs identifying.
        check_confluence("", blacklist_file=f)

    def test_unknown_space_still_needs_a_declared_section(self, tmp_path: Path) -> None:
        f = tmp_path / "bl.yaml"
        f.write_text("sharepoint:\n  blacklisted_sites: []\n")
        with pytest.raises(BlacklistConfigError, match="confluence"):
            check_confluence("", blacklist_file=f)


# ---------------------------------------------------------------------------
# check_sharepoint
# ---------------------------------------------------------------------------


class TestAdditiveMerge:
    """Blacklist entries from multiple files must be unioned."""

    def test_entries_from_repo_and_explicit_both_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_file = tmp_path / "repo-blacklist.yaml"
        repo_file.write_text(
            "confluence:\n  blacklisted_spaces:\n    - REPOONLY\n"
            "sharepoint:\n  blacklisted_sites:\n    - RepoSite\n"
        )
        explicit = tmp_path / "extra.yaml"
        explicit.write_text(
            "confluence:\n  blacklisted_spaces:\n    - EXTRAONLY\n"
            "sharepoint:\n  blacklisted_sites:\n    - ExtraSite\n"
        )
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: repo_file)
        with pytest.raises(BlacklistError, match="REPOONLY"):
            check_confluence("REPOONLY", blacklist_file=explicit)
        with pytest.raises(BlacklistError, match="EXTRAONLY"):
            check_confluence("EXTRAONLY", blacklist_file=explicit)
        with pytest.raises(BlacklistError, match="RepoSite"):
            check_sharepoint("RepoSite", blacklist_file=explicit)
        with pytest.raises(BlacklistError, match="ExtraSite"):
            check_sharepoint("ExtraSite", blacklist_file=explicit)

    def test_explicit_file_only_one_section_still_uses_repo_for_other(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit file may declare only one section; the other comes from repo."""
        repo_file = tmp_path / "repo-blacklist.yaml"
        repo_file.write_text(
            "confluence:\n  blacklisted_spaces: []\n"
            "sharepoint:\n  blacklisted_sites:\n    - RepoSite\n"
        )
        explicit = tmp_path / "extra.yaml"
        explicit.write_text("confluence:\n  blacklisted_spaces:\n    - HRPRIV\n")
        monkeypatch.setattr("mdd.utils.config._repo_blacklist_path", lambda: repo_file)
        with pytest.raises(BlacklistError, match="HRPRIV"):
            check_confluence("HRPRIV", blacklist_file=explicit)
        with pytest.raises(BlacklistError, match="RepoSite"):
            check_sharepoint("RepoSite", blacklist_file=explicit)


class TestCheckSharepoint:
    def test_missing_sharepoint_key_raises_config_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bl.yaml"
        f.write_text("confluence:\n  blacklisted_spaces: []\n")
        with pytest.raises(BlacklistConfigError, match="sharepoint"):
            check_sharepoint("Council", blacklist_file=f)

    def test_blacklisted_site_raises_blacklist_error(self, blacklist_file: Path) -> None:
        with pytest.raises(BlacklistError, match="Council"):
            check_sharepoint("Council", blacklist_file=blacklist_file)

    def test_safe_site_returns_none(self, blacklist_file: Path) -> None:
        check_sharepoint("Engineering", blacklist_file=blacklist_file)

    def test_prefix_match_raises_blacklist_error(self, blacklist_file: Path) -> None:
        with pytest.raises(BlacklistError, match="Appraisal"):
            check_sharepoint("Appraisals - Bob", blacklist_file=blacklist_file)

    def test_refusal_names_the_declaring_file(self, blacklist_file: Path) -> None:
        with pytest.raises(BlacklistError, match=str(blacklist_file)):
            check_sharepoint("Council", blacklist_file=blacklist_file)


# ---------------------------------------------------------------------------
# detect_source_system
# ---------------------------------------------------------------------------


class TestDetectSourceSystem:
    def test_confluence_from_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        url = "git@gitlab.example.com:mdd/confluence/MYSPACE.git"
        git_result = _make_git_result(url)

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        system, identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.CONFLUENCE
        assert identifier == "MYSPACE"

    def test_sharepoint_from_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        git_result = _make_git_result("https://gitlab.example.com/mdd/sharepoint/Labs")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        system, identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.SHAREPOINT
        assert identifier == "Labs"

    def test_other_when_no_remote(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        system, identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.OTHER
        assert identifier is None

    def test_frontmatter_fallback_confluence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        md = tmp_path / "index.md"
        md.write_text("---\nconfluence:\n  space: TESTSPACE\n---\n\n# Hello\n")
        system, _identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.CONFLUENCE

    def test_frontmatter_fallback_sharepoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        md = tmp_path / "README.md"
        md.write_text("---\nsharepoint:\n  site: Engineering\n---\n\n# Hello\n")
        system, _identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.SHAREPOINT

    def test_frontmatter_mdd_source_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mdd-source: none frontmatter returns NONE opt-out."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        md = tmp_path / "README.md"
        md.write_text("---\nmdd-source: none\ntitle: My Repo\n---\n\n# Hello\n")
        system, identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.NONE
        assert identifier is None

    def test_git_not_on_path_raises_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FileNotFoundError from git subprocess becomes BlacklistConfigError."""

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistConfigError, match="git is not on PATH"):
            detect_source_system(tmp_path)

    def test_git_timeout_raises_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TimeoutExpired from git subprocess becomes BlacklistConfigError."""

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=10)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistConfigError, match="timed out"):
            detect_source_system(tmp_path)

    def test_non_mdd_confluence_segment_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A /confluence/<x> path not under /mdd/ must not be treated as a mirror."""
        url = "https://gitlab.example.com/someuser/confluence/foo"
        git_result = _make_git_result(url)

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        system, identifier = detect_source_system(tmp_path)
        # Should fall through to OTHER (no .md files in tmp_path)
        assert system == SourceSystem.OTHER
        assert identifier is None

    def test_mdd_confluence_extra_not_matched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A segment named 'confluence-extra' must not be matched as confluence."""
        url = "https://gitlab.example.com/mdd/confluence-extra/foo"
        git_result = _make_git_result(url)

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        system, identifier = detect_source_system(tmp_path)
        assert system == SourceSystem.OTHER
        assert identifier is None


# ---------------------------------------------------------------------------
# gate_push
# ---------------------------------------------------------------------------


class TestGatePush:
    def test_gate_push_blocks_blacklisted_confluence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        git_result = _make_git_result("git@gitlab.example.com:mdd/confluence/HRPRIV.git")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistError, match="HRPRIV"):
            gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_allows_safe_sharepoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        git_result = _make_git_result("https://gitlab.example.com/mdd/sharepoint/Engineering")

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return git_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        # Should not raise
        gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_other_system_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """Unidentified repos (OTHER) are rejected — fail closed."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistConfigError, match="Could not identify the source system"):
            gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_mdd_source_none_allows_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """Explicit opt-out via mdd-source: none frontmatter skips the blacklist gate."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        readme = tmp_path / "README.md"
        readme.write_text("---\nmdd-source: none\ntitle: My Repo\n---\n\n# My Repo\n")
        # Should not raise
        gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_confluence_no_identifier_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """Confluence detected via frontmatter but no space key — fail closed."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        md = tmp_path / "index.md"
        md.write_text("---\nconfluence:\n  space: TESTSPACE\n---\n\n# Hello\n")
        with pytest.raises(BlacklistConfigError, match="space key"):
            gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_sharepoint_no_identifier_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """SharePoint detected via frontmatter but no site name — fail closed."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)
        md = tmp_path / "README.md"
        md.write_text("---\nsharepoint:\n  site: Engineering\n---\n\n# Hello\n")
        with pytest.raises(BlacklistConfigError, match="site name"):
            gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_git_not_on_path_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """git not on PATH propagates as BlacklistConfigError."""

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistConfigError, match="git is not on PATH"):
            gate_push(tmp_path, blacklist_file=blacklist_file)

    def test_gate_push_git_timeout_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blacklist_file: Path
    ) -> None:
        """git timeout propagates as BlacklistConfigError."""

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=10)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(BlacklistConfigError, match="timed out"):
            gate_push(tmp_path, blacklist_file=blacklist_file)


# ---------------------------------------------------------------------------
# nested-key false positive
# ---------------------------------------------------------------------------


class TestNestedKeyFalsePositive:
    """Frontmatter detection must only inspect top-level YAML keys."""

    def _fail_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make git remote get-url return non-zero so frontmatter scan is reached."""
        fail_result = _make_git_fail()

        def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
            return fail_result

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_nested_confluence_key_not_detected_as_confluence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A nested 'confluence' key must NOT cause CONFLUENCE detection."""
        self._fail_git(monkeypatch)
        md = tmp_path / "index.md"
        # The 'confluence' key is nested inside 'metadata', not top-level.
        md.write_text("---\nmetadata:\n  confluence: false\ntitle: My Doc\n---\n\n# Hello\n")
        system, _id = detect_source_system(tmp_path)
        # Must NOT be detected as Confluence — it's a nested key.
        assert system != SourceSystem.CONFLUENCE

    def test_nested_sharepoint_key_not_detected_as_sharepoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A nested 'sharepoint' key must NOT cause SHAREPOINT detection."""
        self._fail_git(monkeypatch)
        md = tmp_path / "README.md"
        md.write_text("---\ninfo:\n  sharepoint: false\ntitle: My Doc\n---\n\n# Hello\n")
        system, _id = detect_source_system(tmp_path)
        assert system != SourceSystem.SHAREPOINT

    def test_top_level_confluence_still_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A top-level 'confluence' key must still be detected."""
        self._fail_git(monkeypatch)
        md = tmp_path / "page.md"
        md.write_text("---\nconfluence:\n  page_id: '42'\n---\n\n# Hello\n")
        system, _id = detect_source_system(tmp_path)
        assert system == SourceSystem.CONFLUENCE

    def test_invalid_yaml_frontmatter_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files with invalid YAML frontmatter must be skipped gracefully."""
        self._fail_git(monkeypatch)
        md = tmp_path / "broken.md"
        md.write_text("---\n: invalid: yaml: [\n---\n\n# Hello\n")
        # Should not raise — invalid YAML is silently skipped
        system, _id = detect_source_system(tmp_path)
        assert system == SourceSystem.OTHER
