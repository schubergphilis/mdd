"""Tests for mdd.commands.skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.cli import main as cli_main
from mdd.commands.skills import (
    _BUNDLED_SKILL_NAMES,  # pyright: ignore[reportPrivateUsage]
    _bundle_root,  # pyright: ignore[reportPrivateUsage]
    _bundled_skill_path,  # pyright: ignore[reportPrivateUsage]
    _default_target,  # pyright: ignore[reportPrivateUsage]
    _entry_status,  # pyright: ignore[reportPrivateUsage]
    _is_our_symlink,  # pyright: ignore[reportPrivateUsage]
)


def _list(args: list[str]) -> int:
    return cli_main(["skills", "list", *args])


def _install(args: list[str]) -> int:
    return cli_main(["skills", "install", *args])


def _uninstall(args: list[str]) -> int:
    return cli_main(["skills", "uninstall", *args])


# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------


class TestBundleRoot:
    def test_returns_path(self) -> None:
        root = _bundle_root()
        assert isinstance(root, Path)

    def test_bundled_skills_exist(self) -> None:
        """Every discovered skill name must have a SKILL.md in the bundle."""
        assert _BUNDLED_SKILL_NAMES, "no skills discovered in the bundle"
        for name in _BUNDLED_SKILL_NAMES:
            skill_dir = _bundled_skill_path(name)
            assert skill_dir.exists(), f"Bundle missing skill directory: {skill_dir}"
            skill_md = skill_dir / "SKILL.md"
            assert skill_md.exists(), f"Bundle missing SKILL.md: {skill_md}"

    def test_every_bundle_subdirectory_is_discovered(self) -> None:
        """Discovery must not silently skip a shipped skill.

        The list used to be a hard-coded tuple; this is the guard that
        replaces it. A directory in the bundle with no SKILL.md is a
        packaging mistake, not a skill to ignore quietly.
        """
        subdirs = {
            entry.name
            for entry in _bundle_root().iterdir()
            if entry.is_dir() and not entry.name.startswith(("_", "."))
        }
        assert subdirs == set(_BUNDLED_SKILL_NAMES)


class TestSkillMdFrontmatter:
    """Each SKILL.md must have the required frontmatter and sections."""

    @pytest.mark.parametrize("name", _BUNDLED_SKILL_NAMES)
    def test_has_required_frontmatter_fields(self, name: str) -> None:
        skill_md = _bundled_skill_path(name) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        assert "name:" in content, f"{name}/SKILL.md missing 'name:' frontmatter"
        assert "description:" in content, f"{name}/SKILL.md missing 'description:' frontmatter"

    @pytest.mark.parametrize("name", _BUNDLED_SKILL_NAMES)
    def test_has_required_sections(self, name: str) -> None:
        skill_md = _bundled_skill_path(name) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        assert "## When to use" in content, f"{name}/SKILL.md missing '## When to use'"
        assert "## When NOT to use" in content, f"{name}/SKILL.md missing '## When NOT to use'"
        assert "## Common flows" in content, f"{name}/SKILL.md missing '## Common flows'"

    @pytest.mark.parametrize("name", _BUNDLED_SKILL_NAMES)
    def test_name_matches_directory(self, name: str) -> None:
        """The 'name:' frontmatter value must match the directory name."""
        skill_md = _bundled_skill_path(name) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("name:"):
                value = stripped.removeprefix("name:").strip()
                assert value == name, (
                    f"{name}/SKILL.md: frontmatter 'name: {value}' "
                    f"does not match directory name '{name}'"
                )
                break


# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------


class TestDefaultTarget:
    def test_default_is_home_claude_skills(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_HOME", raising=False)
        target = _default_target()
        assert target == Path.home() / ".claude" / "skills"

    def test_claude_home_env_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path))
        target = _default_target()
        assert target == tmp_path / "skills"


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------


class TestEntryStatus:
    def test_available_when_missing(self, tmp_path: Path) -> None:
        status = _entry_status(tmp_path, "mdd-confluence-skill")
        assert status == "available"

    def test_installed_when_our_symlink(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        bundled = _bundled_skill_path(name)
        link = tmp_path / name
        link.symlink_to(bundled, target_is_directory=True)
        assert _entry_status(tmp_path, name) == "installed"

    def test_user_modified_when_not_symlink(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        (tmp_path / name).mkdir()
        assert _entry_status(tmp_path, name) == "user-modified"

    def test_user_modified_when_foreign_symlink(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        other = tmp_path / "other"
        other.mkdir()
        link = tmp_path / name
        link.symlink_to(other, target_is_directory=True)
        assert _entry_status(tmp_path, name) == "user-modified"


# ---------------------------------------------------------------------------
# _is_our_symlink
# ---------------------------------------------------------------------------


class TestIsOurSymlink:
    def test_true_for_our_bundle(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        bundled = _bundled_skill_path(name)
        link = tmp_path / name
        link.symlink_to(bundled, target_is_directory=True)
        assert _is_our_symlink(link, name) is True

    def test_false_for_non_symlink(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        d = tmp_path / name
        d.mkdir()
        assert _is_our_symlink(d, name) is False

    def test_false_for_foreign_symlink(self, tmp_path: Path) -> None:
        name = "mdd-confluence-skill"
        other = tmp_path / "other"
        other.mkdir()
        link = tmp_path / name
        link.symlink_to(other, target_is_directory=True)
        assert _is_our_symlink(link, name) is False


# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------


class TestCmdList:
    def test_shows_available_for_empty_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _list(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "available" in out
        for name in _BUNDLED_SKILL_NAMES:
            assert name in out

    def test_shows_installed_after_install(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install(["--target", str(tmp_path)])
        capsys.readouterr()
        rc = _list(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "installed" in out

    def test_shows_user_modified(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        (tmp_path / name).mkdir()
        rc = _list(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "user-modified" in out

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _list(["--nope"])
        assert exc_info.value.code == 2

    def test_missing_target_value_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _list(["--target"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# install subcommand
# ---------------------------------------------------------------------------


class TestCmdInstall:
    def test_creates_symlinks(self, tmp_path: Path) -> None:
        rc = _install(["--target", str(tmp_path)])
        assert rc == 0
        for name in _BUNDLED_SKILL_NAMES:
            link = tmp_path / name
            assert link.is_symlink(), f"{name} should be a symlink"
            assert _is_our_symlink(link, name), f"{name} symlink should point at our bundle"

    def test_idempotent(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _install(["--target", str(tmp_path)])
        capsys.readouterr()
        rc = _install(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "already installed" in out

    def test_skips_user_modified_without_force(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        (tmp_path / name).mkdir()
        rc = _install(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "skipped: user-modified" in out
        assert (tmp_path / name).is_dir()
        assert not (tmp_path / name).is_symlink()

    def test_force_overwrites_user_modified(self, tmp_path: Path) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        (tmp_path / name).mkdir()
        rc = _install(["--target", str(tmp_path), "--force"])
        assert rc == 0
        assert (tmp_path / name).is_symlink()

    def test_creates_target_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "skills"
        rc = _install(["--target", str(nested)])
        assert rc == 0
        assert nested.exists()

    def test_replaces_foreign_symlink(self, tmp_path: Path) -> None:
        """A symlink pointing at a different location should be replaced."""
        name = _BUNDLED_SKILL_NAMES[0]
        other = tmp_path / "other"
        other.mkdir()
        link = tmp_path / name
        link.symlink_to(other, target_is_directory=True)

        rc = _install(["--target", str(tmp_path)])
        assert rc == 0
        assert _is_our_symlink(link, name)

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _install(["--nope"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# uninstall subcommand
# ---------------------------------------------------------------------------


class TestCmdUninstall:
    def test_removes_our_symlinks(self, tmp_path: Path) -> None:
        _install(["--target", str(tmp_path)])
        rc = _uninstall(["--target", str(tmp_path)])
        assert rc == 0
        for name in _BUNDLED_SKILL_NAMES:
            assert not (tmp_path / name).exists()

    def test_leaves_user_modified(self, tmp_path: Path) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        user_dir = tmp_path / name
        user_dir.mkdir()
        rc = _uninstall(["--target", str(tmp_path)])
        assert rc == 0
        assert user_dir.exists()

    def test_leaves_foreign_symlinks(self, tmp_path: Path) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        other = tmp_path / "other"
        other.mkdir()
        link = tmp_path / name
        link.symlink_to(other, target_is_directory=True)
        rc = _uninstall(["--target", str(tmp_path)])
        assert rc == 0
        assert link.is_symlink()

    def test_noop_on_missing_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "nonexistent"
        rc = _uninstall(["--target", str(missing)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "does not exist" in out

    def test_noop_when_nothing_installed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _uninstall(["--target", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing removed" in out

    def test_unknown_option_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _uninstall(["--nope"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


class TestCmdSkills:
    def test_no_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["skills"])
        assert exc_info.value.code == 2

    def test_unknown_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["skills", "bogus"])
        assert exc_info.value.code == 2

    def test_list_dispatches(self, tmp_path: Path) -> None:
        rc = cli_main(["skills", "list", "--target", str(tmp_path)])
        assert rc == 0

    def test_install_dispatches(self, tmp_path: Path) -> None:
        rc = cli_main(["skills", "install", "--target", str(tmp_path)])
        assert rc == 0

    def test_uninstall_dispatches(self, tmp_path: Path) -> None:
        rc = cli_main(["skills", "uninstall", "--target", str(tmp_path)])
        assert rc == 0
