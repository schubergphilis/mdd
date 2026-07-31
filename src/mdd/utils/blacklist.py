"""Confidentiality blacklist enforcement for mdd."""

import re
import subprocess
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import yaml

from mdd.utils.config import ConfigError, find_blacklist_files, load_yaml

if TYPE_CHECKING:
    from pathlib import Path

_SSH_RE = re.compile(r"^[^@]+@[^:]+:(.+)$")


class BlacklistError(Exception):
    """Raised when a space or site matches a blacklist entry."""


class BlacklistConfigError(Exception):
    """Raised when the blacklist file is missing or malformed."""


class SourceSystem(StrEnum):
    CONFLUENCE = "confluence"
    SHAREPOINT = "sharepoint"
    OTHER = "other"
    NONE = "none"  # explicit opt-out via mdd-source: none frontmatter


def _matches(name: str, patterns: list[str]) -> str | None:
    """Return the first matching pattern, or None.

    Matching rules (case-insensitive):
    - Pattern ends with ``*``: prefix match using the part before ``*``.
      Only a *trailing* ``*`` has wildcard semantics; leading or internal
      ``*`` characters are treated as literal characters.
    - Otherwise: exact match.
    """
    name_lower = name.lower()
    for pattern in patterns:
        if pattern.endswith("*") and not pattern.startswith("*") and "*" not in pattern[:-1]:
            prefix = pattern[:-1].lower()
            if name_lower.startswith(prefix):
                return pattern
        else:
            if name_lower == pattern.lower():
                return pattern
    return None


def _section_list(data: dict[str, Any], section: str, key: str) -> list[str] | None:
    """Return ``data[section][key]`` as a list of strings, or None if absent.

    Raises BlacklistConfigError if the keys are present but malformed.
    """
    if section not in data:
        return None
    section_val: Any = data[section]  # pyright: ignore[reportAny]
    if not isinstance(section_val, dict):
        raise BlacklistConfigError(f"blacklist section '{section}' must be a mapping")
    section_dict: dict[str, Any] = cast("dict[str, Any]", section_val)
    if key not in section_dict:
        return None
    raw: Any = section_dict[key]  # pyright: ignore[reportAny]
    if not isinstance(raw, list):
        raise BlacklistConfigError(f"blacklist key '{section}.{key}' must be a list")
    return [str(p) for p in cast("list[Any]", raw)]


def _extend_unique(dest: list[str], values: list[str]) -> None:
    """Append each ``values`` entry to ``dest`` if not already present."""
    for v in values:
        if v not in dest:
            dest.append(v)


def _merge_section(
    out: dict[str, list[str]], data: dict[str, Any], section: str, key: str, out_key: str
) -> None:
    """Merge ``data[section][key]`` into ``out[out_key]`` if present."""
    values = _section_list(data, section, key)
    if values is None:
        return
    _extend_unique(out.setdefault(out_key, []), values)


def _load_blacklist(blacklist_file: Path | None) -> dict[str, list[str]]:
    """Load and merge entries from every applicable blacklist file.

    Returns a dict with keys ``confluence_spaces`` and ``sharepoint_sites``,
    each a deduplicated list (case-preserving; later files extend earlier
    ones). Missing keys mean "no file declared this section" — callers gate
    accordingly.
    """
    try:
        paths = find_blacklist_files(blacklist_file)
    except ConfigError as exc:
        raise BlacklistConfigError(str(exc)) from exc

    out: dict[str, list[str]] = {}
    for path in paths:
        try:
            data = load_yaml(path)
        except ConfigError as exc:
            raise BlacklistConfigError(str(exc)) from exc
        _merge_section(out, data, "confluence", "blacklisted_spaces", "confluence_spaces")
        _merge_section(out, data, "sharepoint", "blacklisted_sites", "sharepoint_sites")
    return out


_UNKNOWN_SOURCE = "the data-protection config"


def _pattern_source(section: str, key: str, pattern: str, blacklist_file: Path | None) -> str:
    """Return the path of the first loaded file that declares *pattern*.

    The blacklist is additive across several files, so a refusal has to say
    which one to edit. This only runs on the refusal path, so re-reading the
    files is cheap; a best-effort answer is enough and any load failure falls
    back to a generic phrase.
    """
    try:
        paths = find_blacklist_files(blacklist_file)
    except ConfigError:
        return _UNKNOWN_SOURCE
    for path in paths:
        try:
            values = _section_list(load_yaml(path), section, key)
        except ConfigError, BlacklistConfigError:
            continue
        if values is not None and pattern in values:
            return str(path)
    return _UNKNOWN_SOURCE


def check_confluence(space_key: str, *, blacklist_file: Path | None = None) -> None:
    """Raise BlacklistError if *space_key* is on the Confluence blacklist.

    An empty *space_key* means the caller could not identify the space the
    content came from. That is refused whenever any space is blacklisted at
    all — an unidentifiable space could be a protected one, and the gate must
    not be the thing that lets it through. With an empty blacklist there is
    nothing to protect, so it is allowed.

    Raises BlacklistConfigError if no loaded file declares a
    ``confluence.blacklisted_spaces`` section.
    """
    merged = _load_blacklist(blacklist_file)
    if "confluence_spaces" not in merged:
        raise BlacklistConfigError(
            "no loaded blacklist file declares confluence.blacklisted_spaces"
        )
    patterns = merged["confluence_spaces"]
    if not space_key:
        if not patterns:
            return
        raise BlacklistError(
            "Could not determine which Confluence space this content belongs to, "
            f"and {len(patterns)} space pattern(s) are blacklisted. Refused, because "
            "a space that cannot be identified cannot be checked against the "
            "blacklist. Re-run against a page whose response carries a space key."
        )
    matched = _matches(space_key, patterns)
    if matched is not None:
        raise BlacklistError(
            f"Confluence space '{space_key}' matches blacklist pattern '{matched}'. "
            "Refused by the data-protection blacklist declared in "
            f"{_pattern_source('confluence', 'blacklisted_spaces', matched, blacklist_file)}. "
            "Nothing was written or pushed. To publish this space, remove the "
            "pattern from that file."
        )


def check_sharepoint(folder_name: str, *, blacklist_file: Path | None = None) -> None:
    """Raise BlacklistError if *folder_name* is on the SharePoint blacklist.

    Raises BlacklistConfigError if no loaded file declares a
    ``sharepoint.blacklisted_sites`` section.
    """
    merged = _load_blacklist(blacklist_file)
    if "sharepoint_sites" not in merged:
        raise BlacklistConfigError("no loaded blacklist file declares sharepoint.blacklisted_sites")
    matched = _matches(folder_name, merged["sharepoint_sites"])
    if matched is not None:
        raise BlacklistError(
            f"SharePoint site '{folder_name}' matches blacklist pattern '{matched}'. "
            "Refused by the data-protection blacklist declared in "
            f"{_pattern_source('sharepoint', 'blacklisted_sites', matched, blacklist_file)}. "
            "Nothing was written or pushed. To publish this site, remove the "
            "pattern from that file."
        )


def _origin_url(path: Path) -> str | None:
    """Return the ``origin`` remote URL for *path*, or None if not set.

    Raises BlacklistConfigError if git is missing or times out.
    """
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise BlacklistConfigError(
            "git is not on PATH; cannot determine source system for blacklist gate. "
            "Install git and retry."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BlacklistConfigError(
            f"git remote get-url timed out for '{path}'; "
            "cannot determine source system for blacklist gate. "
            "Check git configuration and network access."
        ) from exc
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().removesuffix(".git")


def _url_path_segments(url: str) -> list[str]:
    """Split *url* into path segments, handling SSH (``user@host:path``) and HTTPS forms."""
    ssh_m = _SSH_RE.match(url)
    if ssh_m:
        path_part = ssh_m.group(1)
    elif "://" in url:
        path_part = urlsplit(url).path.strip("/")
    else:
        path_part = url
    return path_part.replace("\\", "/").split("/")


def _detect_from_segments(segments: list[str]) -> tuple[SourceSystem, str | None] | None:
    """Match the ``mdd/<system>/<id>`` mirror-path pattern.

    A bare ``/confluence/<x>`` in an unrelated namespace must not be
    treated as an mdd mirror — the ``mdd`` prefix is required.
    """
    for i, seg in enumerate(segments):
        if seg != "mdd" or i + 2 >= len(segments):
            continue
        next_seg = segments[i + 1]
        if next_seg == "confluence":
            return (SourceSystem.CONFLUENCE, segments[i + 2])
        if next_seg == "sharepoint":
            return (SourceSystem.SHAREPOINT, segments[i + 2])
    return None


def _read_frontmatter(md_file: Path) -> dict[str, Any] | None:
    """Parse the YAML frontmatter block at the head of *md_file*, or None.

    Returns None when the file has no ``---`` block, is unreadable, or the
    YAML doesn't parse to a mapping.
    """
    try:
        text = md_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        parsed: Any = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _detect_from_frontmatter_dict(fm: dict[str, Any]) -> tuple[SourceSystem, str | None] | None:
    """Inspect top-level frontmatter keys for an mdd-source declaration."""
    mdd_source: Any = fm.get("mdd-source")  # pyright: ignore[reportAny]
    if isinstance(mdd_source, str) and mdd_source.strip() == "none":
        return (SourceSystem.NONE, None)
    if "confluence" in fm:
        return (SourceSystem.CONFLUENCE, None)
    if "sharepoint" in fm:
        return (SourceSystem.SHAREPOINT, None)
    return None


def _resolve_via_git_remote(path: Path) -> tuple[SourceSystem, str | None] | None:
    """Detect via ``git remote get-url origin`` matching ``mdd/<system>/<id>``.

    Returns ``(CONFLUENCE, space)``, ``(SHAREPOINT, name)``, or None when no
    origin is set or the URL doesn't carry the mdd-mirror path layout.
    """
    url = _origin_url(path)
    if url is None:
        return None
    return _detect_from_segments(_url_path_segments(url))


def _resolve_via_md_frontmatter(path: Path) -> tuple[SourceSystem, str | None] | None:
    """Detect via YAML frontmatter on up to 20 top-level ``*.md`` files.

    Returns ``(NONE, None)`` for an explicit ``mdd-source: none`` opt-out,
    ``(CONFLUENCE, None)`` or ``(SHAREPOINT, None)`` for top-level
    ``confluence:``/``sharepoint:`` keys, or None when no file declares either.
    """
    for md_file in list(path.glob("*.md"))[:20]:
        fm = _read_frontmatter(md_file)
        if fm is None:
            continue
        hit = _detect_from_frontmatter_dict(fm)
        if hit is not None:
            return hit
    return None


# First-match-wins resolver chain. Resolvers are tried in order and
# may raise ``BlacklistConfigError`` for infrastructure failures (missing git,
# timeouts); a return of None means "this strategy didn't apply, try the next."
# To add a strategy: write a ``Resolver`` and append it here.
type Resolver = Callable[[Path], tuple[SourceSystem, str | None] | None]
_RESOLVERS: tuple[Resolver, ...] = (
    _resolve_via_git_remote,
    _resolve_via_md_frontmatter,
)


def detect_source_system(path: Path) -> tuple[SourceSystem, str | None]:
    """Detect whether *path* is a Confluence or SharePoint mirror repo.

    Walks ``_RESOLVERS`` in order; the first non-None result wins. Falls back
    to ``(OTHER, None)`` when no resolver matches. Per-resolver docstrings
    describe each strategy and what it returns.

    Raises ``BlacklistConfigError`` for resolver-level infrastructure
    failures (e.g. ``git`` missing or timing out) — these are operational
    failures that must not be silently swallowed.
    """
    for resolver in _RESOLVERS:
        hit = resolver(path)
        if hit is not None:
            return hit
    return (SourceSystem.OTHER, None)


def gate_push(path: Path, *, blacklist_file: Path | None = None) -> None:
    """Check whether a push from *path* is allowed.

    Detects the source system and delegates to check_confluence or
    check_sharepoint. Raises BlacklistError or BlacklistConfigError on
    violation.

    This exists for a deployment's mirror backend, which sees a work-tree and
    a remote rather than a space key, and gates at push time. It has no caller
    among the sync and export commands here: those know their own source
    system and call check_confluence / check_sharepoint directly at their
    entry points, before any content is fetched or written. Both are real
    enforcement points, so do not remove this one for looking unused from
    inside this package.

    Fail-closed behaviour:
    - If the source system cannot be identified (OTHER), raises BlacklistConfigError.
      To opt out, add ``mdd-source: none`` to the YAML frontmatter of any top-level
      ``.md`` file in the repo (e.g. README.md).
    - If the system is Confluence or SharePoint but the identifier (space/site) could
      not be extracted from the remote URL, raises BlacklistConfigError rather than
      silently allowing the push.
    - If ``git`` is not on PATH or the subprocess times out, raises BlacklistConfigError
      (propagated from detect_source_system).
    """
    system, identifier = detect_source_system(path)

    if system == SourceSystem.NONE:
        # Explicit opt-out — non-mirror repo declared via mdd-source: none frontmatter.
        return

    if system == SourceSystem.OTHER:
        raise BlacklistConfigError(
            f"Could not identify the source system for '{path}'. "
            "Push refused to avoid leaking unclassified content. "
            "If this repo is not a Confluence or SharePoint mirror, add "
            "'mdd-source: none' to the YAML frontmatter of any top-level .md file "
            "(e.g. README.md)."
        )

    if system == SourceSystem.CONFLUENCE:
        if identifier is None:
            raise BlacklistConfigError(
                f"Detected Confluence mirror at '{path}' but could not extract the "
                "space key from the remote URL. "
                "Push refused until the space key can be verified against the blacklist. "
                "Check that the remote URL follows the pattern mdd/confluence/<SPACE_KEY>."
            )
        check_confluence(identifier, blacklist_file=blacklist_file)
        return

    if system == SourceSystem.SHAREPOINT:
        if identifier is None:
            raise BlacklistConfigError(
                f"Detected SharePoint mirror at '{path}' but could not extract the "
                "site name from the remote URL. "
                "Push refused until the site name can be verified against the blacklist. "
                "Check that the remote URL follows the pattern mdd/sharepoint/<SITE_NAME>."
            )
        check_sharepoint(identifier, blacklist_file=blacklist_file)
