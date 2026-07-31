"""mapping.py — site-name to repo-name mapping for SharePoint mirrors."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass
class MappingEntry:
    """An explicit site-name → repo-name mapping entry."""

    site_name: str
    repo_name: str


_SPECIAL_CHARS_RE = re.compile(r'[\s/\\:*?"<>|]+')


def normalize(name: str) -> str:
    """Derive a GitLab-safe repo name from a SharePoint site name.

    Rules:
      1. Trim leading/trailing whitespace.
      2. Replace each run of whitespace or ``/\\:*?"<>|`` with a single ``-``.
      3. Strip leading/trailing ``-``.
      4. Preserve case.
    """
    name = name.strip()
    name = _SPECIAL_CHARS_RE.sub("-", name)
    return name.strip("-")


def _find_mapping_file(path: Path | None) -> Path | None:
    """Return the first existing mapping file, or None."""
    if path is not None:
        return path if path.exists() else None

    local = Path("configs") / "sharepoint-mapping.yaml"
    if local.exists():
        return local

    user = Path.home() / ".config" / "mdd" / "sharepoint-mapping.yaml"
    if user.exists():
        return user

    return None


def _load_yaml_doc(mapping_path: Path) -> dict[str, Any]:
    """Read *mapping_path* and return its top-level dict, or ``{}`` on any error.

    A non-dict top level (list, scalar, null) is silently coerced to ``{}`` —
    callers treat "no mapping" identically to "malformed mapping" by design.
    """
    try:
        with mapping_path.open(encoding="utf-8") as fh:
            data: Any = yaml.safe_load(fh)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return cast("dict[str, Any]", data)


def _parse_dict_entry(site_name: str, entry_raw: Any) -> MappingEntry | None:
    """Validate one entry of the dict-keyed format.

    Returns ``None`` when the entry is malformed (not a dict, missing ``repo``,
    or ``repo`` is not a string) so the caller can skip it.
    """
    if not isinstance(entry_raw, dict):
        return None
    entry_dict: dict[str, Any] = cast("dict[str, Any]", entry_raw)
    repo_raw: Any = entry_dict.get("repo")
    if not isinstance(repo_raw, str):
        return None
    return MappingEntry(site_name=site_name, repo_name=repo_raw)


def _parse_dict_sites(sites: dict[str, Any]) -> dict[str, MappingEntry]:
    """Parse the dict-keyed ``sites:`` block; skip malformed entries."""
    result: dict[str, MappingEntry] = {}
    for site_name, entry_raw in sites.items():
        entry = _parse_dict_entry(site_name, entry_raw)
        if entry is not None:
            result[site_name] = entry
    return result


def _parse_list_entry(item: Any) -> MappingEntry | None:
    """Validate one entry of the legacy list format.

    Returns ``None`` when ``site_name`` / ``repo_name`` are missing or not strings.
    """
    if not isinstance(item, dict):
        return None
    item_dict: dict[str, Any] = cast("dict[str, Any]", item)
    site_raw: Any = item_dict.get("site_name")
    repo_name_raw: Any = item_dict.get("repo_name")
    if not isinstance(site_raw, str) or not isinstance(repo_name_raw, str):
        return None
    return MappingEntry(site_name=site_raw, repo_name=repo_name_raw)


def _parse_list_sites(sites: list[Any]) -> dict[str, MappingEntry]:
    """Parse the legacy list ``sites:`` block; skip malformed entries."""
    result: dict[str, MappingEntry] = {}
    for item in sites:
        entry = _parse_list_entry(item)
        if entry is not None:
            result[entry.site_name] = entry
    return result


def load_mapping(path: Path | None = None) -> dict[str, MappingEntry]:
    """Load the site→repo mapping from a YAML file.

    Search order:
      1. *path* argument (if provided).
      2. ``./configs/sharepoint-mapping.yaml``.
      3. ``~/.config/mdd/sharepoint-mapping.yaml``.
      4. Return empty dict if none found.

    Supported YAML structures:

    **Spec-010 dict-keyed format (preferred)**::

        sites:
          "HR Documentation":
            repo: HR-Documentation
          "AI":
            repo: AI

    **Legacy list format (still accepted)**::

        sites:
          - site_name: "AI / ML Team"
            repo_name: "AI-ML-Team"

    Returns:
        Dict keyed by ``site_name``.
    """
    mapping_path = _find_mapping_file(path)
    if mapping_path is None:
        return {}

    sites_raw: Any = _load_yaml_doc(mapping_path).get("sites")
    if isinstance(sites_raw, dict):
        return _parse_dict_sites(cast("dict[str, Any]", sites_raw))
    if isinstance(sites_raw, list):
        return _parse_list_sites(cast("list[Any]", sites_raw))
    return {}


def repo_name(site_name: str, mapping: dict[str, MappingEntry]) -> str:
    """Return the GitLab repo name for *site_name*.

    An explicit mapping entry wins; otherwise ``normalize(site_name)`` is used.
    """
    entry = mapping.get(site_name)
    if entry is not None:
        return entry.repo_name
    return normalize(site_name)
