"""Root-source registry for `mdd search`.

Mirrors :mod:`mdd.mirror.registry`: a module-level ``dict`` keyed by a
normalized source type, an explicit :func:`register_root_source` that
raises on a duplicate key, and a lookup helper.

``confluence``, ``sharepoint`` and ``docs`` are registered built-ins.
A wrapper distribution registers its own from its CLI entry point, next
to where it registers its mirror backend — that is how the SBP wrapper
adds ``lucid`` without the open-source core carrying a search filter for
an integration it does not ship.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RootSource:
    """Describes where one kind of mirror root is configured.

    Every source keeps its mirror directories in the same shape — a
    mapping of identifier to a block with an ``output_dir`` — so one
    description is enough to load any of them:

    ``config_name`` names the config file (``configs/<name>.yaml``, then
    ``~/.config/mdd/<name>.yaml``); ``section`` is its top-level key; and
    ``collection`` is the key under that holding the mapping, or ``None``
    when the section *is* the mapping (as ``docs`` in the global config).

    ``label`` is the human name used in the "root does not exist locally"
    warning.
    """

    source_type: str
    config_name: str
    section: str
    collection: str | None
    label: str


# Keyed by lowercased source type, e.g. "confluence", "sharepoint".
SOURCES: dict[str, RootSource] = {}


def _normalize(name: str) -> str:
    return name.strip().lower()


def register_root_source(source: RootSource) -> None:
    """Register *source* under its ``source_type``.

    Raises ValueError if that source type is already registered.
    """
    key = _normalize(source.source_type)
    if key in SOURCES:
        raise ValueError(
            f"Root source {key!r} is already registered "
            f"(config {SOURCES[key].config_name}.yaml); "
            f"cannot register it again from {source.config_name}.yaml"
        )
    SOURCES[key] = source


def root_source_for(name: str) -> RootSource:
    """Return the root source registered under *name*.

    Raises KeyError with the set of known types if *name* is unknown.
    """
    key = _normalize(name)
    try:
        return SOURCES[key]
    except KeyError as exc:
        raise KeyError(f"No root source registered for {name!r}. {known_types_hint()}") from exc


def registered_root_sources() -> tuple[RootSource, ...]:
    """Return every registered source, in registration order."""
    return tuple(SOURCES.values())


def known_types_hint() -> str:
    """Return a "Known source types: …" fragment for error messages."""
    known = ", ".join(SOURCES) or "(none)"
    return f"Known source types: {known}"


# The provider-neutral sources the core ships. Registered at import so
# that resolving roots never depends on which command module ran first.
CONFLUENCE = RootSource(
    source_type="confluence",
    config_name="confluence",
    section="confluence",
    collection="spaces",
    label="Confluence",
)
SHAREPOINT = RootSource(
    source_type="sharepoint",
    config_name="sharepoint",
    section="sharepoint",
    collection="sites",
    label="SharePoint",
)
DOCS = RootSource(
    source_type="docs",
    config_name="config",
    section="docs",
    collection=None,
    label="Docs",
)

for _builtin in (CONFLUENCE, SHAREPOINT, DOCS):
    register_root_source(_builtin)
