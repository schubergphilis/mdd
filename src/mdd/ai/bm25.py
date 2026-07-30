"""Thin BM25 index wrapper using rank-bm25.

Tokenises on word boundaries, lowercases, strips frontmatter and code blocks.
Index is built once and held in memory; no disk representation.

Usage::

    index = Bm25Index.build(docs)   # docs: list of (path, body_text)
    pairs = index.top_k_pairs(k=5, min_score=0.0)
    for (path_a, path_b), score in pairs:
        ...
    neighbours = index.top_k_for(path, k=5)
    newer_neighbours = index.top_k_for(path, k=5, restrict_to=newer_paths)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rank_bm25 import BM25Okapi  # pyright: ignore[reportMissingTypeStubs]

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Text pre-processing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"(?m)^(`{3,}|~{3,})[^\n]*\n.*?\n\1[ \t]*$", re.DOTALL)


def _strip_markup(text: str) -> str:
    """Remove frontmatter and fenced code blocks; return plain text."""
    text = _FRONTMATTER_RE.sub("", text)
    return _CODE_BLOCK_RE.sub("", text)


def _tokenise(text: str) -> list[str]:
    """Lowercase word-boundary tokenisation."""
    return re.findall(r"\b\w+\b", _strip_markup(text).lower())


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bm25Pair:
    """A scored pair of document paths."""

    path_a: Path
    path_b: Path
    score: float


class Bm25Index:
    """In-memory BM25 index over a collection of markdown documents.

    Built once via :meth:`build`; queried via :meth:`top_k_pairs` or
    :meth:`top_k_for`.  The *paths* list preserves document order and
    is used to translate numeric BM25 indices back to paths.
    """

    def __init__(self, paths: list[Path], bm25: BM25Okapi, corpus: list[list[str]]) -> None:
        self._paths = paths
        self._bm25 = bm25
        self._corpus = corpus  # tokenised corpus, parallel to _paths
        # Build a reverse lookup once.
        self._path_to_idx: dict[Path, int] = {p: i for i, p in enumerate(paths)}

    @classmethod
    def build(cls, docs: list[tuple[Path, str]]) -> Bm25Index:
        """Build an index from *(path, body)* pairs.

        Empty *docs* returns a valid but empty index.
        """
        if not docs:
            # rank-bm25 crashes on empty corpus; return a stub.
            return _EmptyBm25Index()  # type: ignore[return-value]

        paths = [p for p, _ in docs]
        corpus = [_tokenise(body) for _, body in docs]
        bm25 = BM25Okapi(corpus)
        return cls(paths, bm25, corpus)

    def top_k_for(
        self,
        path: Path,
        k: int,
        *,
        restrict_to: set[Path] | None = None,
    ) -> list[tuple[Path, float]]:
        """Return the top-K neighbours of *path* (excluding itself).

        Parameters
        ----------
        path:
            The query document.  Must be in the index.
        k:
            Number of neighbours to return.
        restrict_to:
            When given, only consider paths in this set.

        Returns
        -------
        list of (neighbour_path, score) sorted by score descending.
        """
        idx = self._path_to_idx.get(path)
        if idx is None:
            return []

        query_tokens = self._corpus[idx]
        scores: list[float] = list(self._bm25.get_scores(query_tokens))  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]

        candidates: list[tuple[float, Path]] = []
        for i, score in enumerate(scores):
            if i == idx:
                continue
            candidate = self._paths[i]
            if restrict_to is not None and candidate not in restrict_to:
                continue
            candidates.append((score, candidate))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [(p, s) for s, p in candidates[:k]]

    def top_k_pairs(
        self,
        k: int,
        *,
        min_score: float = 0.0,
    ) -> list[Bm25Pair]:
        """Return all high-scoring pairs across the corpus.

        For each document, finds its top-K neighbours; deduplicates symmetric
        pairs (A,B) == (B,A) and filters by *min_score*.

        Returns a list of :class:`Bm25Pair` sorted by score descending.
        """
        seen: set[tuple[int, int]] = set()
        pairs: list[Bm25Pair] = []

        for path in self._paths:
            for neighbour, score in self.top_k_for(path, k):
                if score < min_score:
                    continue
                i = self._path_to_idx[path]
                j = self._path_to_idx[neighbour]
                key = (min(i, j), max(i, j))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(Bm25Pair(path_a=path, path_b=neighbour, score=score))

        pairs.sort(key=lambda p: p.score, reverse=True)
        return pairs

    @property
    def paths(self) -> list[Path]:
        """Ordered list of all indexed paths."""
        return list(self._paths)

    def __len__(self) -> int:
        return len(self._paths)


class _EmptyBm25Index(Bm25Index):
    """Stub returned when the corpus is empty."""

    def __init__(self) -> None:
        # Don't call super().__init__ — avoid building a BM25Okapi with empty corpus.
        self._paths: list[Path] = []
        self._path_to_idx: dict[Path, int] = {}

    def top_k_for(
        self,
        path: Path,  # noqa: ARG002
        k: int,  # noqa: ARG002
        *,
        restrict_to: set[Path] | None = None,  # noqa: ARG002
    ) -> list[tuple[Path, float]]:
        return []

    def top_k_pairs(self, k: int, *, min_score: float = 0.0) -> list[Bm25Pair]:  # noqa: ARG002
        return []
