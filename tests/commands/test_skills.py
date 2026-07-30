"""Tests for mdd.commands.skills."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mdd.cli import main as cli_main
from mdd.commands import skills as skills_mod
from mdd.commands.skills import (
    _bundle_root,  # pyright: ignore[reportPrivateUsage]
    _bundled_skill_path,  # pyright: ignore[reportPrivateUsage]
    _default_target,  # pyright: ignore[reportPrivateUsage]
    _entry_status,  # pyright: ignore[reportPrivateUsage]
    _is_our_symlink,  # pyright: ignore[reportPrivateUsage]
    bundled_skill_names,
    register_skill_root,
    skill_roots,
)

# Collection-time snapshot of the core bundle, for parametrized tests. The
# per-test fixtures below restore the registry, so this stays the core set.
_BUNDLED_SKILL_NAMES = bundled_skill_names()


def _write_skill(root: Path, name: str, body: str = "stub") -> Path:
    """Create a minimal skill directory under *root* and return it."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    _ = (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {body}\n---\n\n{body}\n", encoding="utf-8"
    )
    return skill_dir


@pytest.fixture
def isolated_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the skill-root registry and its cache around a test.

    ``register_skill_root`` mutates module state; without this a test that
    registers a ``tmp_path`` root would leak a dangling root into every
    later test.
    """
    monkeypatch.setattr(skills_mod, "_SKILL_ROOTS", [_bundle_root()])
    monkeypatch.setattr(skills_mod, "_skill_index_cache", None)


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


# ---------------------------------------------------------------------------
# register_skill_root seam
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("isolated_roots")
class TestRegisterSkillRoot:
    """The seam a composing distribution uses to ship its own skills."""

    def test_core_root_is_preregistered_first(self) -> None:
        assert skill_roots()[0] == _bundle_root()

    def test_reexported_from_the_commands_package(self) -> None:
        """The seam a wrapper imports, alongside ``mdd.mirror.register_backend``."""
        import mdd.commands as commands_pkg

        assert commands_pkg.register_skill_root is register_skill_root
        assert commands_pkg.skill_roots is skill_roots

    def test_registers_after_import(self, tmp_path: Path) -> None:
        """Discovery is lazy: a root registered post-import must be seen.

        Regression guard for the original bug — the name tuple was computed
        at import time, so nothing registered later was ever visible.
        """
        assert "wrapper-only-skill" not in bundled_skill_names()
        _ = _write_skill(tmp_path, "wrapper-only-skill")
        register_skill_root(tmp_path)
        assert "wrapper-only-skill" in bundled_skill_names()
        assert skill_roots() == (_bundle_root(), tmp_path)

    def test_accepts_a_str_path(self, tmp_path: Path) -> None:
        _ = _write_skill(tmp_path, "wrapper-only-skill")
        register_skill_root(str(tmp_path))
        assert _bundled_skill_path("wrapper-only-skill") == tmp_path / "wrapper-only-skill"

    def test_ignores_a_missing_root(self, tmp_path: Path) -> None:
        register_skill_root(tmp_path / "nope")
        assert bundled_skill_names() == _BUNDLED_SKILL_NAMES

    def test_ignores_directories_without_skill_md(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-skill").mkdir()
        register_skill_root(tmp_path)
        assert "not-a-skill" not in bundled_skill_names()

    def test_last_registered_root_wins(self, tmp_path: Path) -> None:
        """A wrapper may deliberately override a core skill by name."""
        name = _BUNDLED_SKILL_NAMES[0]
        override = _write_skill(tmp_path, name, body="override")
        register_skill_root(tmp_path)

        assert bundled_skill_names().count(name) == 1
        assert _bundled_skill_path(name) == override
        resolved = (_bundled_skill_path(name) / "SKILL.md").read_text(encoding="utf-8")
        assert "override" in resolved, "list/install must resolve to the wrapper copy"

    def test_later_of_three_roots_wins(self, tmp_path: Path) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        first = tmp_path / "first"
        second = tmp_path / "second"
        _ = _write_skill(first, name)
        last = _write_skill(second, name)
        register_skill_root(first)
        register_skill_root(second)
        assert _bundled_skill_path(name) == last

    def test_unknown_name_falls_back_to_core_root(self) -> None:
        assert _bundled_skill_path("no-such-skill") == _bundle_root() / "no-such-skill"

    def test_list_shows_the_extra_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _ = _write_skill(tmp_path, "wrapper-only-skill")
        register_skill_root(tmp_path)

        rc = _list(["--target", str(tmp_path / "target")])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"[1] {_bundle_root()}" in out
        assert f"[2] {tmp_path}" in out
        # The wrapper's skill is listed and tagged with the root it came from.
        assert "wrapper-only-skill" in out
        wrapper_line = next(
            line for line in out.splitlines() if line.strip().startswith("wrapper-only-skill")
        )
        assert "[2]" in wrapper_line
        core_line = next(
            line for line in out.splitlines() if line.strip().startswith(_BUNDLED_SKILL_NAMES[0])
        )
        assert "[1]" in core_line

    def test_list_tags_a_shadowed_skill_with_the_winning_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An accidental shadow has to be diagnosable from `list` alone."""
        name = _BUNDLED_SKILL_NAMES[0]
        _ = _write_skill(tmp_path, name)
        register_skill_root(tmp_path)

        rc = _list(["--target", str(tmp_path / "target")])
        assert rc == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if name in line]
        skill_lines = [line for line in lines if line.strip().startswith(name)]
        assert len(skill_lines) == 1
        assert "[2]" in skill_lines[0]

    def test_install_picks_the_overriding_copy(self, tmp_path: Path) -> None:
        name = _BUNDLED_SKILL_NAMES[0]
        override = _write_skill(tmp_path / "wrapper", name, body="override")
        register_skill_root(tmp_path / "wrapper")

        target = tmp_path / "target"
        rc = _install(["--target", str(target)])
        assert rc == 0
        link = target / name
        assert link.is_symlink()
        assert link.resolve() == override.resolve()

    def test_install_and_uninstall_cover_the_extra_root(self, tmp_path: Path) -> None:
        _ = _write_skill(tmp_path / "wrapper", "wrapper-only-skill")
        register_skill_root(tmp_path / "wrapper")

        target = tmp_path / "target"
        assert _install(["--target", str(target)]) == 0
        assert (target / "wrapper-only-skill").is_symlink()

        assert _uninstall(["--target", str(target)]) == 0
        assert not (target / "wrapper-only-skill").exists()

    def test_install_reports_a_missing_bundle_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A root that vanishes between discovery and install is an error, not a crash."""
        wrapper = tmp_path / "wrapper"
        _ = _write_skill(wrapper, "wrapper-only-skill")
        register_skill_root(wrapper)
        assert "wrapper-only-skill" in bundled_skill_names()
        shutil.rmtree(wrapper)

        rc = _install(["--target", str(tmp_path / "target")])
        assert rc == 1
        assert "bundled skill directory not found" in capsys.readouterr().out

    def test_list_flags_a_missing_bundle_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        wrapper = tmp_path / "wrapper"
        _ = _write_skill(wrapper, "wrapper-only-skill")
        register_skill_root(wrapper)
        assert "wrapper-only-skill" in bundled_skill_names()
        shutil.rmtree(wrapper)

        assert _list(["--target", str(tmp_path / "target")]) == 0
        assert "[bundle missing!]" in capsys.readouterr().out


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
