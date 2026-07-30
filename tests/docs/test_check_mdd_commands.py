"""Tests for scripts/check-mdd-commands.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "check-mdd-commands.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_mdd_commands", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_mdd_commands"] = module
    spec.loader.exec_module(module)
    return module


# Kept as a plain module reference (like tests/docs/test_sync_docs.py's `sync_docs`), not
# rebound into narrowly-typed local variables: a loaded module's attributes are ``Any`` to
# the type checker, and re-declaring them with a concrete ``Callable``/return type would
# just paper over that with a wrong static type instead of a correct one.
check_mdd_commands = _load_module()


# ---------------------------------------------------------------------------
# The real command tree.
# ---------------------------------------------------------------------------


def test_tree_contains_known_commands() -> None:
    """The introspected tree must contain real commands, or introspection broke."""
    tree = check_mdd_commands.build_command_tree()
    assert ("convert",) in tree
    assert ("confluence", "sync-space") in tree
    assert "sync-space" in tree[("confluence",)].children
    assert "--dry-run" in tree[("convert",)].options


def test_tree_leaf_has_no_children() -> None:
    tree = check_mdd_commands.build_command_tree()
    assert tree[("convert",)].children == frozenset()


# ---------------------------------------------------------------------------
# Scanning: what counts as a candidate invocation.
# ---------------------------------------------------------------------------


def _scan(text: str) -> list[tuple[int, str]]:
    hits = check_mdd_commands._scan_text(Path("doc.md"), text)
    return [(inv.line, inv.text) for inv in hits]


def test_inline_code_span_is_scanned() -> None:
    assert _scan("Run `mdd convert <path>` first.") == [(1, "mdd convert <path>")]


def test_bare_word_reference_is_not_a_command() -> None:
    assert _scan("`mdd` does near-lossless roundtrips between formats.") == []


def test_path_segment_is_not_a_command() -> None:
    assert _scan("See `src/mdd` and `mdd.commands.convert` for the module layout.") == []


def test_bare_prose_outside_code_span_is_skipped() -> None:
    assert _scan("Just run mdd frobnicate to see what happens.") == []


def test_fenced_bash_block_is_scanned() -> None:
    text = "```bash\n$ mdd convert docs/\n```\n"
    assert _scan(text) == [(2, "mdd convert docs/")]


def test_fenced_block_without_language_is_scanned() -> None:
    text = '```\nuv run mdd search "laptop"\n```\n'
    assert _scan(text) == [(2, 'mdd search "laptop"')]


def test_fenced_python_block_is_not_scanned() -> None:
    text = "```python\nfrom mdd.cli import main\n```\n"
    assert _scan(text) == []


def test_line_continuation_is_joined() -> None:
    text = "```bash\nmdd confluence sync-space FOO \\\n  --dry-run\n```\n"
    assert _scan(text) == [(2, "mdd confluence sync-space FOO --dry-run")]


def test_prefixes_are_stripped() -> None:
    assert _scan("`uv tool run mdd convert <path>`") == [(1, "mdd convert <path>")]
    assert _scan("`$ mdd convert <path>`") == [(1, "mdd convert <path>")]


# ---------------------------------------------------------------------------
# Validation against the command tree.
# ---------------------------------------------------------------------------


def test_real_command_passes() -> None:
    tree = check_mdd_commands.build_command_tree()
    assert check_mdd_commands.validate_invocation(("confluence", "sync-space"), tree) is None
    assert (
        check_mdd_commands.validate_invocation(("confluence", "sync-space", "<space-key>"), tree)
        is None
    )
    assert (
        check_mdd_commands.validate_invocation(
            ("confluence", "sync-space", "<KEY>", "--dry-run"), tree
        )
        is None
    )


def test_version_and_help_pass() -> None:
    tree = check_mdd_commands.build_command_tree()
    assert check_mdd_commands.validate_invocation(("--version",), tree) is None
    assert check_mdd_commands.validate_invocation(("--help",), tree) is None
    assert check_mdd_commands.validate_invocation(("-h",), tree) is None


def test_unknown_top_level_command_fails() -> None:
    tree = check_mdd_commands.build_command_tree()
    result = check_mdd_commands.validate_invocation(("frobnicate",), tree)
    assert result is not None
    assert result.bad_token == "frobnicate"


def test_unknown_subcommand_of_known_group_fails() -> None:
    tree = check_mdd_commands.build_command_tree()
    result = check_mdd_commands.validate_invocation(("confluence", "sync-spaceX"), tree)
    assert result is not None
    assert result.error == "unknown subcommand"
    assert result.bad_token == "sync-spaceX"


def test_unknown_long_option_fails() -> None:
    tree = check_mdd_commands.build_command_tree()
    result = check_mdd_commands.validate_invocation(("convert", "<path>", "--reverse"), tree)
    assert result is not None
    assert result.error == "unknown option"
    assert result.bad_token == "--reverse"


def test_leaf_command_positional_args_are_not_validated() -> None:
    """Once a command has no subparsers, remaining tokens are just its arguments."""
    tree = check_mdd_commands.build_command_tree()
    result = check_mdd_commands.validate_invocation(
        ("confluence", "rename-page", "docs/Architecture.md", '"Architecture (2026)"'), tree
    )
    assert result is None


def test_pipe_alternation_of_real_subcommands_passes() -> None:
    tree = check_mdd_commands.build_command_tree()
    assert check_mdd_commands.validate_invocation(("ai", "rewrite|index|review"), tree) is None


def test_pipe_alternation_with_unreal_subcommand_fails() -> None:
    tree = check_mdd_commands.build_command_tree()
    result = check_mdd_commands.validate_invocation(("ai", "rewrite|chat"), tree)
    assert result is not None


# ---------------------------------------------------------------------------
# End to end over small fake corpora.
# ---------------------------------------------------------------------------


def test_end_to_end_flags_a_broken_command_string(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text("Run `mdd confluence sync-spaceX <space-key>` to sync.\n", encoding="utf-8")
    invocations = check_mdd_commands.scan_file(doc)
    tree = check_mdd_commands.build_command_tree()
    violations = [
        inv
        for inv in invocations
        if check_mdd_commands.validate_invocation(inv.tokens, tree) is not None
    ]
    assert len(violations) == 1
    assert violations[0].line == 1


def test_end_to_end_passes_a_correct_command_string(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text("Run `mdd confluence sync-space <space-key>` to sync.\n", encoding="utf-8")
    invocations = check_mdd_commands.scan_file(doc)
    tree = check_mdd_commands.build_command_tree()
    violations = [
        inv
        for inv in invocations
        if check_mdd_commands.validate_invocation(inv.tokens, tree) is not None
    ]
    assert violations == []


def test_discover_files_skips_missing_directories(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("`mdd help`\n", encoding="utf-8")
    files = check_mdd_commands.discover_files(tmp_path)
    assert files == [tmp_path / "README.md"]


# ---------------------------------------------------------------------------
# The default scope excludes the design record; --all includes it, advisory only.
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_default_scope_excludes_spec_and_research(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "spec" / "S99-x.md", "`mdd bogus-command`\n")
    _write(tmp_path / "docs" / "research" / "R99-x.md", "`mdd bogus-command`\n")
    _write(tmp_path / "docs" / "guide" / "01-x.md", "`mdd convert <path>`\n")
    files = check_mdd_commands.discover_files(tmp_path)
    assert tmp_path / "docs" / "guide" / "01-x.md" in files
    assert not any(f.parent.name in {"spec", "research"} for f in files)


def test_include_advisory_adds_spec_and_research(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "spec" / "S99-x.md", "`mdd bogus-command`\n")
    _write(tmp_path / "docs" / "research" / "R99-x.md", "`mdd bogus-command`\n")
    files = check_mdd_commands.discover_files(tmp_path, include_advisory=True)
    assert tmp_path / "docs" / "spec" / "S99-x.md" in files
    assert tmp_path / "docs" / "research" / "R99-x.md" in files


def test_main_default_fails_on_a_guide_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "docs" / "guide" / "01-x.md", "`mdd bogus-command`\n")
    monkeypatch.setattr(check_mdd_commands, "REPO_ROOT", tmp_path)
    assert check_mdd_commands.main([]) == 1


def test_main_default_ignores_a_spec_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "docs" / "spec" / "S99-x.md", "`mdd bogus-command`\n")
    monkeypatch.setattr(check_mdd_commands, "REPO_ROOT", tmp_path)
    assert check_mdd_commands.main([]) == 0


def test_main_all_reports_but_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "docs" / "spec" / "S99-x.md", "`mdd bogus-command`\n")
    monkeypatch.setattr(check_mdd_commands, "REPO_ROOT", tmp_path)
    exit_code = check_mdd_commands.main(["--all"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "ADVISORY" in out
    assert "bogus-command" in out
