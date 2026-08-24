"""Path-based file discovery for every prose subcommand.

Scoping is path-based, not mirror-based. The registered-root-source registry
``mdd search`` uses answers "where are all my mirrors" — the wrong question for
a gate, which runs inside one repository's checkout and must not silently reach
into another.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.utils.mddignore import MddIgnore

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

MARKDOWN_SUFFIXES = (".md", ".qmd")


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_SUFFIXES


def _walk_directory(root: Path, ignore: MddIgnore) -> Iterable[Path]:
    for current_dir, subdirs, files in os.walk(root, followlinks=False):
        current = Path(current_dir)
        subdirs[:] = sorted(
            name
            for name in subdirs
            if name != ".git" and not ignore.prune_dir((current / name).relative_to(root))
        )
        for name in sorted(files):
            candidate = current / name
            if not _is_markdown(candidate):
                continue
            if ignore.is_ignored(candidate.relative_to(root), is_dir=False):
                continue
            yield candidate


def discover(
    paths: Sequence[Path],
    *,
    extra_ignores: Sequence[Path] = (),
) -> list[Path]:
    """Return every Markdown file under *paths*, honouring ``.mddignore``.

    A directory is walked for ``*.md`` and ``*.qmd``; a file the user named
    explicitly is taken as given, since naming a path is the user asking for it.
    """
    targets = list(paths) or [Path()]
    out: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target.is_dir():
            ignore = MddIgnore.load(target, tuple(extra_ignores) or None)
            found = _walk_directory(target, ignore)
        elif target.is_file():
            found = [target]
        else:
            continue
        for path in found:
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def missing(paths: Sequence[Path]) -> list[Path]:
    """Return the named paths that do not exist."""
    return [path for path in paths if not path.exists()]
