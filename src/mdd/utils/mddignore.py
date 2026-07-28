"""Source-side `.mddignore` matcher (spec S39).

Loads a union of ``.mddignore`` patterns from the destination mirror root
plus zero-or-more CLI-provided ignore files, and exposes:

- ``is_ignored(rel_path, *, is_dir)`` — gitignore-style match against a
  POSIX-style relative path.
- ``prune_dir(rel_dir)`` — conservative "every descendant would be
  ignored" check that lets walkers skip whole subtrees.

Pattern syntax is gitignore wildmatch, delegated to the ``pathspec``
library. The matcher itself adds no negation/precedence layer on top.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pathspec

if TYPE_CHECKING:
    from collections.abc import Iterator

_IGNORE_FILENAME = ".mddignore"

# Probe suffixes used by ``prune_dir`` to test whether every descendant
# of a candidate directory would be ignored. Diversity matters: different
# extensions, different depths, dotfile-like names, names without an
# extension. If every probe matches the spec, we can confidently prune.
_PRUNE_PROBES: tuple[str, ...] = (
    "a",
    "a.txt",
    "a.md",
    ".hidden",
    "no-extension-file",
    "sub/a.bin",
    "sub/deep/file.dat",
    "x/y/z",
)


def _read_pattern_lines(path: Path) -> list[str]:
    """Read pattern lines from *path*. Missing files yield ``[]`` silently."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return text.splitlines()


def _collect_sources(
    dest_repo_root: Path,
    cli_ignore: Path | tuple[Path, ...] | None,
) -> tuple[Path, ...]:
    """Build the ordered tuple of ignore-file paths to load.

    The dest-root ``.mddignore`` comes first (if present on disk), followed
    by CLI-supplied paths in the order they were given. A missing dest
    file is silently skipped; CLI paths are recorded even if absent (so
    ``sources`` reflects user intent).
    """
    sources: list[Path] = []
    dest_ignore = dest_repo_root / _IGNORE_FILENAME
    if dest_ignore.is_file():
        sources.append(dest_ignore)
    if cli_ignore is None:
        return tuple(sources)
    if isinstance(cli_ignore, Path):
        sources.append(cli_ignore)
        return tuple(sources)
    sources.extend(cli_ignore)
    return tuple(sources)


def _to_posix(rel_path: Path) -> str:
    """Render *rel_path* as a POSIX-style forward-slash string.

    The matcher treats all paths as relative to the destination mirror
    root, matching gitignore's own portability rules.
    """
    return PurePosixPath(*rel_path.parts).as_posix()


def _is_root_skip(name: str) -> bool:
    """True iff *name* is the dest-root ``.mddignore`` or any dotfile at the root.

    ``.mddignore`` is the matcher's source-of-truth (deleting it would
    surprise the user). Other dotfiles at the mirror root (``.git/``,
    ``.gitlab-ci.yml``, etc.) are infrastructure that the matcher should
    never own — they are protected for the same reason ``rm -rf .`` is
    not the prune semantics we want.
    """
    return name == _IGNORE_FILENAME or name.startswith(".")


def _yield_if_prunable(
    candidate: Path,
    dest_root: Path,
    root_resolved: Path,
    matcher: MddIgnore,
) -> Iterator[Path]:
    """Yield *candidate* if it is a regular file matched by *matcher* and inside *dest_root*.

    Refuses to yield paths whose ``resolve()`` escapes *root_resolved* —
    this is the symlink-escape guard the spec requires.
    """
    if not candidate.is_file():
        return
    try:
        resolved = candidate.resolve()
    except OSError:
        return
    try:
        _ = resolved.relative_to(root_resolved)
    except ValueError:
        return  # symlink escaped dest_root
    rel = candidate.relative_to(dest_root)
    if matcher.is_ignored(rel, is_dir=False):
        yield candidate


@dataclass(frozen=True)
class MddIgnore:
    """Compiled `.mddignore` matcher (spec S39).

    Wraps a ``pathspec.GitIgnoreSpec`` so callers do not need to depend
    on pathspec directly.
    """

    spec: pathspec.GitIgnoreSpec
    sources: tuple[Path, ...]

    @classmethod
    def load(
        cls,
        dest_repo_root: Path,
        cli_ignore: Path | tuple[Path, ...] | None = None,
    ) -> MddIgnore:
        """Load the matcher from the dest root and CLI-supplied paths.

        The dest-root ``.mddignore`` (if present) and every CLI-supplied
        file are read and their pattern lines unioned together. Missing
        files are silently treated as empty.
        """
        sources = _collect_sources(dest_repo_root, cli_ignore)
        lines: list[str] = []
        for src in sources:
            lines.extend(_read_pattern_lines(src))
        spec = pathspec.GitIgnoreSpec.from_lines(lines)
        return cls(spec=spec, sources=sources)

    def is_ignored(self, rel_path: Path, *, is_dir: bool) -> bool:
        """True iff *rel_path* would be ignored by any loaded pattern.

        *rel_path* is interpreted relative to the destination mirror
        root and rendered POSIX-style internally. ``is_dir=True`` appends
        a trailing ``/`` so gitignore directory-only patterns (those
        ending in ``/``) match correctly.
        """
        posix = _to_posix(rel_path)
        if is_dir and not posix.endswith("/"):
            posix = posix + "/"
        return self.spec.match_file(posix)

    def walk_prunable(self, dest_root: Path) -> Iterator[Path]:
        """Yield every file under *dest_root* whose relative path is ignored.

        Used by ``--prune-ignored`` (spec S39 "Opt-in cleanup"). The helper
        only enumerates; deletion is the caller's responsibility.

        Safety domain (enforced here, not the caller):

        - Skips ``dest_root/.mddignore`` itself.
        - Skips dot-prefixed entries at the mirror root (``.git/``,
          ``.gitlab-ci.yml`` etc.).
        - Never escapes *dest_root*: ``os.walk`` runs with
          ``followlinks=False`` and every yielded path is verified to
          resolve under ``dest_root.resolve()``.
        - Yields nothing when the matcher carries no patterns (the common
          "no .mddignore, no --ignore" case is a cheap no-op).
        """
        if not dest_root.exists():
            return
        if not self.spec.patterns:
            return
        root_resolved = dest_root.resolve()
        for current_dir, subdirs, files in os.walk(dest_root, followlinks=False):
            current = Path(current_dir)
            if current == dest_root:
                subdirs[:] = [d for d in subdirs if not d.startswith(".")]
                files = [f for f in files if not _is_root_skip(f)]
            for name in files:
                candidate = current / name
                yield from _yield_if_prunable(candidate, dest_root, root_resolved, self)

    def prune_dir(self, rel_dir: Path) -> bool:
        """True iff every descendant of *rel_dir* is provably ignored.

        Conservative: returns False when in doubt. Used by walkers to
        skip listing a directory entirely.

        Decision rule: ``rel_dir`` is prunable when

        - it is matched as a directory itself (gitignore semantics: a
          matched directory implies all descendants are ignored), or
        - every synthetic descendant probe from :data:`_PRUNE_PROBES`
          matches the spec. Probes are deliberately diverse (different
          extensions, depths, dotfiles) so that a pattern with mixed
          coverage (e.g. ``**/*.tmp``) cannot pass.
        """
        if self.is_ignored(rel_dir, is_dir=True):
            return True
        base = _to_posix(rel_dir)
        for probe in _PRUNE_PROBES:
            probe_path = f"{base}/{probe}" if base else probe
            if not self.spec.match_file(probe_path):
                return False
        return True
