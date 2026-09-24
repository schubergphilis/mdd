"""Shared config-loading utilities for mdd."""

import re
from pathlib import Path
from typing import Any, cast

import yaml


class ConfigError(Exception):
    """Raised when a config file cannot be found or parsed."""


class _PlainTextLoader(yaml.SafeLoader):
    """A safe loader that reads every plain scalar as the text written.

    ``yaml.safe_load`` follows YAML 1.1 implicit typing, so an unquoted ``NO``
    becomes ``False``, ``007`` becomes ``7`` and ``2026-01-01`` becomes a date.
    This loader keeps them as the strings ``"NO"``, ``"007"`` and
    ``"2026-01-01"``. Lists and mappings still load as lists and dicts.

    Null (``~``, ``null``, an empty value) is still recognised, so a missing
    value stays distinguishable from text and a caller can reject it.
    """


_PlainTextLoader.yaml_implicit_resolvers = {}
_PlainTextLoader.add_implicit_resolver(  # pyright: ignore[reportUnknownMemberType]
    "tag:yaml.org,2002:null",
    re.compile(r"^(?:~|null|Null|NULL|)$"),
    ["~", "n", "N", ""],
)


def _load_yaml_with(path: Path, loader: type[yaml.SafeLoader]) -> dict[str, Any]:
    """Load *path* with *loader* and return the top-level mapping.

    Raises ConfigError on missing/unreadable files or parse failure.
    """
    try:
        with path.open() as fh:
            result: Any = yaml.load(fh, Loader=loader)  # noqa: S506  # SafeLoader subclass
    except OSError as exc:
        raise ConfigError(f"Failed to read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping at the top level")
    return cast("dict[str, Any]", result)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict.

    Raises ConfigError on missing/unreadable files or parse failure.
    """
    return _load_yaml_with(path, yaml.SafeLoader)


def load_yaml_plain_text(path: Path) -> dict[str, Any]:
    """Load a YAML file whose scalars must be kept exactly as written.

    Like :func:`load_yaml`, but an unquoted scalar is never turned into a
    bool, number or date: ``- NO`` loads as ``"NO"`` and ``- 0x1F`` as
    ``"0x1F"``. Null is still loaded as ``None``. Use this for files that
    list names, where a silent retype would change which name is meant.

    Raises ConfigError on missing/unreadable files or parse failure.
    """
    return _load_yaml_with(path, _PlainTextLoader)


# Leads with the fix rather than with what was expected: the reader of this
# message is usually someone who installed mdd and ran a sync, and the
# per-user path is the one that works for every install shape. The bundled
# file is listed second because a packaged install does not carry it and a
# reader cannot create it.
_NO_BLACKLIST_MESSAGE = """No data-protection blacklist found, and one is required.
  Sync and export refuse to run until a blacklist declares which Confluence
  spaces and SharePoint sites must never leave their source system.
  To proceed, create ~/.config/mdd/data-protection.yaml containing:

    confluence:
      blacklisted_spaces: []
    sharepoint:
      blacklisted_sites: []

  Both sections must be present. An empty list means "protect nothing", which
  is a deliberate choice you are making rather than a default you inherit; add
  the space keys and site names you want protected to the lists.
  Also searched, in order: configs/data-protection.yaml bundled with the mdd
  install (a source checkout has this, a packaged install does not), then
  ~/.config/mdd/data-protection.yaml, then ./configs/data-protection.yaml
  relative to the current directory."""


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
        raise ConfigError(_NO_BLACKLIST_MESSAGE)
    return found
