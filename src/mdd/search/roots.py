"""Resolve mirror roots from mdd config files.

Loads the config file of every registered root source (see
:mod:`mdd.search.sources`) and extracts the ``output_dir`` value for each
configured space / site / repo. Missing directories are reported via
warnings; they are not errors — the user may not have cloned every mirror
locally.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from mdd.search.sources import RootSource, registered_root_sources

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class MirrorRoot:
    """A single configured mirror directory with its provenance."""

    path: Path
    mirror_name: str  # e.g. "confluence/ENGINEERING"
    source_type: str  # a registered source type, or "extra" for --include
    identifier: str  # space_key / site_name / folder_name / repo_name


def _load_yaml_safe(path: Path) -> dict[str, Any] | None:
    """Load a YAML file; return None on any error (file missing, parse error)."""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            result: Any = yaml.safe_load(fh)
        if isinstance(result, dict):
            return result  # pyright: ignore[reportReturnType, reportUnknownVariableType]
    except OSError, yaml.YAMLError:
        pass
    return None


def _find_config(name: str) -> Path | None:
    """Return the first candidate config path that exists, or None."""
    candidates = [
        Path("configs") / f"{name}.yaml",
        Path.home() / ".config" / "mdd" / f"{name}.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _get_mapping(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Return ``data[key]`` when it is a mapping, else None."""
    raw: Any = data.get(key)
    if not isinstance(raw, dict):
        return None
    return raw  # pyright: ignore[reportUnknownVariableType]


def _entries_for(source: RootSource, data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the identifier → block mapping *source* keeps its roots in."""
    section = _get_mapping(data, source.section)
    if section is None:
        return None
    if source.collection is None:
        return section
    return _get_mapping(section, source.collection)


def roots_for_source(source: RootSource, config_path: Path | None = None) -> list[MirrorRoot]:
    """Extract the mirror roots *source* declares in its config file.

    *config_path* overrides the auto-discovered location. Entries with no
    usable ``output_dir``, and directories that do not exist locally, are
    skipped — the latter with a warning.
    """
    path = config_path or _find_config(source.config_name)
    if path is None:
        return []
    data = _load_yaml_safe(path)
    if data is None:
        return []
    entries = _entries_for(source, data)
    if entries is None:
        return []

    roots: list[MirrorRoot] = []
    for key, val in entries.items():
        if not isinstance(val, dict):
            continue
        entry: dict[str, Any] = val  # pyright: ignore[reportUnknownVariableType]
        output_dir_raw: Any = entry.get("output_dir")
        if not isinstance(output_dir_raw, str) or not output_dir_raw:
            continue
        p = Path(output_dir_raw).expanduser()
        if not p.exists():
            warnings.warn(
                f"{source.label} mirror root does not exist locally, skipping: {p}",
                stacklevel=2,
            )
            continue
        roots.append(
            MirrorRoot(
                path=p,
                mirror_name=f"{source.source_type}/{key}",
                source_type=source.source_type,
                identifier=str(key),
            )
        )
    return roots


def _apply_source_filters(
    roots: list[MirrorRoot],
    source_filters: Mapping[str, list[str]],
) -> list[MirrorRoot]:
    """Restrict roots to source types whose filter is active.

    Identifier matching is case-insensitive. A filter on one source type
    drops every root of the others: ``--site AI`` keeps only sharepoint
    sites matching `AI`, and ``--space Labs`` against a config with no
    `Labs` space returns nothing, even if a sharepoint site named `Labs`
    exists.
    """
    wanted: dict[str, set[str]] = {
        source_type: {i.casefold() for i in identifiers}
        for source_type, identifiers in source_filters.items()
        if identifiers
    }
    empty: set[str] = set()
    return [r for r in roots if r.identifier.casefold() in wanted.get(r.source_type, empty)]


def resolve_roots(
    *,
    config_paths: Mapping[str, Path] | None = None,
    extra_paths: list[Path] | None = None,
    exclude_paths: list[Path] | None = None,
    source_filters: Mapping[str, list[str]] | None = None,
) -> list[MirrorRoot]:
    """Return all configured mirror roots that exist locally.

    Parameters
    ----------
    config_paths:
        Explicit config file per source type (e.g.
        ``{"confluence": Path("confluence.yaml")}``); source types absent
        from the mapping are auto-discovered.
    extra_paths:
        Additional directories to include (--include flag).
    exclude_paths:
        Directories to remove from the results (--exclude flag).
    source_filters:
        Identifiers to keep per source type (e.g.
        ``{"confluence": ["ENG"]}``, from --space / --site / --source).
        Source types with no entry here are dropped entirely as soon as
        *any* filter is active.
    """
    overrides = config_paths or {}
    roots: list[MirrorRoot] = []
    for source in registered_root_sources():
        roots.extend(roots_for_source(source, overrides.get(source.source_type)))

    if source_filters and any(source_filters.values()):
        roots = _apply_source_filters(roots, source_filters)

    # Add extra paths (raw directories without mirror metadata)
    if extra_paths:
        for ep in extra_paths:
            if ep.exists():
                roots.append(
                    MirrorRoot(
                        path=ep,
                        mirror_name=str(ep),
                        source_type="extra",
                        identifier=str(ep),
                    )
                )
            else:
                warnings.warn(f"Extra search path does not exist, skipping: {ep}", stacklevel=2)

    # Remove excluded paths
    if exclude_paths:
        exclude_resolved = {p.resolve() for p in exclude_paths}
        roots = [r for r in roots if r.path.resolve() not in exclude_resolved]

    return roots
