"""mdd skills — install / list / uninstall bundled Claude Code skills (spec S23)."""

from __future__ import annotations

import argparse
import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from mdd.cli import CommonParents, SubParsers

# ---------------------------------------------------------------------------
# Bundle discovery
# ---------------------------------------------------------------------------


def _bundle_root() -> Path:
    """Return the path to the bundled ``src/mdd/skills/`` directory.

    Uses ``importlib.resources`` so this works both from a source tree
    (``uv run``) and from an installed wheel.
    """
    ref = files("mdd") / "skills"
    return Path(str(ref))


# Skill roots in registration order. The core bundle is pre-registered as
# the first entry; a distribution that composes the CLI (spec S44) appends
# its own root from its entry point, and later entries win on a name
# collision so a wrapper can deliberately override a core skill.
_SKILL_ROOTS: list[Path] = [_bundle_root()]

# Lazily-built ``{skill name: owning root}`` map. ``None`` means "not
# discovered yet". Invalidated by :func:`register_skill_root`, because
# discovery has to survive a registration that happens after import.
_skill_index_cache: dict[str, Path] | None = None


def register_skill_root(path: Path | str) -> None:
    """Register an additional directory of bundled skills.

    The counterpart of :func:`mdd.mirror.register_backend` and
    ``build_dispatcher(extra_commands=...)`` for the skills bundle: a
    composing distribution calls
    ``register_skill_root(files("my_dist") / "skills")`` from its entry
    point, before building the dispatcher, and its skills then show up in
    ``mdd skills list`` / ``install`` / ``uninstall`` alongside the core's.

    Registration order is significant: **the last-registered root wins** on
    a name collision. The core bundle is registered first, so a wrapper can
    ship its own version of a core skill by using the same directory name.
    ``mdd skills list`` prints the owning root for every skill so an
    unintended shadow stays diagnosable.
    """
    global _skill_index_cache
    _SKILL_ROOTS.append(Path(path))
    _skill_index_cache = None


def skill_roots() -> tuple[Path, ...]:
    """Return the registered skill roots, in registration order."""
    return tuple(_SKILL_ROOTS)


def _discover_bundled_skills() -> dict[str, Path]:
    """Map each bundled skill's directory name to the root that owns it.

    Discovered rather than listed, because a hard-coded tuple drifts the
    moment the bundle changes — and it does change: the set of roots is a
    registration seam (:func:`register_skill_root`), so a wrapper
    distribution ships skills of its own on top of the core's, and may
    override a core skill by reusing its name (spec S23). A directory
    counts as a skill when it contains ``SKILL.md``.

    Roots are walked in registration order and later roots overwrite
    earlier ones, implementing the last-registered-wins rule.
    """
    found: dict[str, Path] = {}
    for root in _SKILL_ROOTS:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if (entry / "SKILL.md").is_file():
                found[entry.name] = root
    return {name: found[name] for name in sorted(found)}


def _skill_index() -> dict[str, Path]:
    """Return the cached ``{skill name: owning root}`` map, building it lazily."""
    global _skill_index_cache
    if _skill_index_cache is None:
        _skill_index_cache = _discover_bundled_skills()
    return _skill_index_cache


def bundled_skill_names() -> tuple[str, ...]:
    """Return the names of every bundled skill, sorted, across all roots."""
    return tuple(_skill_index())


def _bundled_skill_path(name: str) -> Path:
    """Return the Path for a specific bundled skill directory.

    Resolves through the same last-registered-wins index that
    :func:`bundled_skill_names` reports, so ``install`` can never pick a
    different copy than ``list`` displayed. Unknown names fall back to the
    core root, which yields a nonexistent path the callers report as
    "bundle missing".
    """
    root = _skill_index().get(name, _SKILL_ROOTS[0])
    return root / name


# ---------------------------------------------------------------------------
# Default target directory
# ---------------------------------------------------------------------------


def _default_target() -> Path:
    """Return ``~/.claude/skills/`` or ``$CLAUDE_HOME/skills/`` if set."""
    claude_home = os.environ.get("CLAUDE_HOME")
    if claude_home:
        return Path(claude_home) / "skills"
    return Path.home() / ".claude" / "skills"


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def _is_our_symlink(link: Path, skill_name: str) -> bool:
    """Return True if *link* is a symlink that resolves to our bundled skill."""
    if not link.is_symlink():
        return False
    try:
        target = link.resolve()
    except OSError:
        return False
    bundled = _bundled_skill_path(skill_name).resolve()
    return target == bundled


def _entry_status(target_dir: Path, skill_name: str) -> str:
    """Return a one-word status: 'installed', 'user-modified', or 'available'."""
    entry = target_dir / skill_name
    if not entry.exists() and not entry.is_symlink():
        return "available"
    if _is_our_symlink(entry, skill_name):
        return "installed"
    return "user-modified"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _resolve_target(target: Path | None) -> Path:
    return target if target is not None else _default_target()


class _SkillsListArgs(argparse.Namespace):
    target: Path | None


class _SkillsInstallArgs(argparse.Namespace):
    target: Path | None
    force: bool


class _SkillsUninstallArgs(argparse.Namespace):
    target: Path | None


def _print_root_legend(roots: tuple[Path, ...]) -> dict[Path, str]:
    """Print the numbered skill-root legend and return the per-root markers.

    Every listed skill is tagged with its root's marker, so a wrapper
    distribution shadowing a core skill (last-registered wins) is visible
    instead of silent.
    """
    print("Skill roots (last registered wins on a name collision):")  # noqa: T201  # program output
    markers: dict[Path, str] = {}
    for index, root in enumerate(roots, start=1):
        markers[root] = f"[{index}]"
        print(f"  [{index}] {root}")  # noqa: T201  # program output
    return markers


def _run_list(ns: argparse.Namespace) -> int:
    args = cast("_SkillsListArgs", ns)
    target_dir = _resolve_target(args.target)
    print(f"Bundled skills (target: {target_dir}):")  # noqa: T201  # program output
    print()  # noqa: T201  # program output
    markers = _print_root_legend(skill_roots())
    print()  # noqa: T201  # program output
    for name, root in _skill_index().items():
        status = _entry_status(target_dir, name)
        bundled_path = _bundled_skill_path(name)
        bundle_note = "" if bundled_path.exists() else " [bundle missing!]"
        marker = markers.get(root, f"[{root}]")
        # program output for piping
        print(f"  {name:<32}  {status:<14}{marker}{bundle_note}")  # noqa: T201
    return 0


def _install_one(name: str, target_dir: Path, *, force: bool) -> int:
    """Install a single bundled skill into *target_dir*. Returns 0 or 1."""
    entry = target_dir / name
    bundled = _bundled_skill_path(name)

    if not bundled.exists():
        # program output for piping
        print(f"  {name}: error — bundled skill directory not found at {bundled}")  # noqa: T201
        return 1

    if entry.is_symlink():
        if _is_our_symlink(entry, name):
            print(f"  {name}: already installed")  # noqa: T201  # program output
            return 0
        entry.unlink()
    elif entry.exists():
        if force:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
        else:
            # program output for piping
            print(f"  {name}: skipped: user-modified (use --force to overwrite)")  # noqa: T201
            return 0

    entry.symlink_to(bundled, target_is_directory=True)
    print(f"  {name}: installed -> {bundled}")  # noqa: T201  # program output
    return 0


def _run_install(ns: argparse.Namespace) -> int:
    args = cast("_SkillsInstallArgs", ns)
    target_dir = _resolve_target(args.target)
    target_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    for name in bundled_skill_names():
        if _install_one(name, target_dir, force=args.force) != 0:
            exit_code = 1
    return exit_code


def _run_uninstall(ns: argparse.Namespace) -> int:
    args = cast("_SkillsUninstallArgs", ns)
    target_dir = _resolve_target(args.target)

    if not target_dir.exists():
        print(f"Target directory does not exist: {target_dir}")  # noqa: T201  # program output
        return 0

    removed = 0
    for name in bundled_skill_names():
        entry = target_dir / name
        if _is_our_symlink(entry, name):
            entry.unlink()
            print(f"  {name}: removed")  # noqa: T201  # program output
            removed += 1
        elif entry.is_symlink() or entry.exists():
            print(f"  {name}: skipped (not our symlink)")  # noqa: T201  # program output

    if removed == 0:
        print("No bundled skills were installed; nothing removed.")  # noqa: T201  # program output
    else:
        print(f"\nRemoved {removed} skill(s) from {target_dir}")  # noqa: T201  # program output
    return 0


# ---------------------------------------------------------------------------
# argparse registration
# ---------------------------------------------------------------------------


def _add_target(p: argparse.ArgumentParser) -> None:
    _ = p.add_argument(
        "--target",
        type=Path,
        default=None,
        metavar="DIR",
        help="Target skills directory (default: ~/.claude/skills/ or $CLAUDE_HOME/skills/)",
    )


def register(
    subparsers: SubParsers,
    parents: CommonParents,  # noqa: ARG001
) -> None:
    skills = subparsers.add_parser(
        "skills",
        help="Install / list / uninstall bundled Claude Code skills",
        description="Manage the Claude Code skills bundled with mdd (spec S23).",
    )
    sub = skills.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    p_list = sub.add_parser(
        "list",
        help="List bundled skills with installed/available status",
        description="List bundled skills with installed/available status.",
    )
    _add_target(p_list)
    p_list.set_defaults(func=_run_list)

    p_install = sub.add_parser(
        "install",
        help="Symlink bundled skills into the target directory (idempotent)",
        description=(
            "Symlink each bundled skill into the target skills directory. "
            "Already-installed symlinks are no-ops. Non-symlink entries are "
            "skipped unless --force is given."
        ),
    )
    _add_target(p_install)
    _ = p_install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite non-symlink entries (user-modified directories) at the target",
    )
    p_install.set_defaults(func=_run_install)

    p_uninstall = sub.add_parser(
        "uninstall",
        help="Remove only the symlinks installed by mdd",
        description=(
            "Remove symlinks in the target directory that point at our bundle. "
            "Other entries (user-modified) are left alone."
        ),
    )
    _add_target(p_uninstall)
    p_uninstall.set_defaults(func=_run_uninstall)
