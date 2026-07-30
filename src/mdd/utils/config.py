"""Shared config-loading utilities for mdd."""

from pathlib import Path
from typing import Any, cast

import yaml


class ConfigError(Exception):
    """Raised when a config file cannot be found or parsed."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict.

    Raises ConfigError on missing/unreadable files or parse failure.
    """
    try:
        with path.open() as fh:
            result: Any = yaml.safe_load(fh)
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping at the top level")
    return cast("dict[str, Any]", result)


def _repo_blacklist_path() -> Path | None:
    """Return the path to the repo-bundled blacklist, or None if absent.

    Resolves ``<repo>/configs/data-protection.yaml`` from this module's location
    so it is found regardless of the caller's current working directory. When
    ``mdd`` is installed as an editable tool (the default install path), the
    file lives in the checked-out source tree; a non-editable install won't
    have it and this returns None.
    """
    # src/mdd/utils/config.py → src/mdd/utils → src/mdd → src → repo
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = repo_root / "configs" / "data-protection.yaml"
    return candidate if candidate.exists() else None


def find_blacklist_files(explicit: Path | None) -> list[Path]:
    """Return every data-protection blacklist file that should apply.

    The blacklist is additive: entries are unioned across all files that exist.
    Sources, in load order:
      1. The repo-bundled ``configs/data-protection.yaml`` (resolved via the
         package install location — independent of the caller's cwd).
      2. ``~/.config/mdd/data-protection.yaml`` (per-user additions).
      3. ``./configs/data-protection.yaml`` (cwd-relative; skipped if it
         resolves to the same file as the repo-bundled one).
      4. *explicit*, when given.

    Raises ConfigError if *explicit* is provided but does not exist, or if no
    blacklist file is found anywhere.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        found.append(path)

    repo = _repo_blacklist_path()
    if repo is not None:
        _add(repo)

    user = Path.home() / ".config" / "mdd" / "data-protection.yaml"
    if user.exists():
        _add(user)

    local = Path("configs") / "data-protection.yaml"
    if local.exists():
        _add(local)

    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"Blacklist file not found: {explicit}")
        _add(explicit)

    if not found:
        raise ConfigError(
            "No data-protection blacklist found. "
            "Expected a bundled configs/data-protection.yaml in the mdd install, "
            "~/.config/mdd/data-protection.yaml, or a --blacklist override. "
            "The file must declare confluence.blacklisted_spaces and "
            "sharepoint.blacklisted_sites; either may be an empty list."
        )
    return found
