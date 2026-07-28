"""Corpus coverage matrix gate.

Per spec S32 §"Coverage matrix": every IR node class must have ≥ 1
occurrence somewhere in the corpus. Two classes are intentionally
left in ``_KNOWN_GAPS`` because they can never be observed through
``parse_confluence_storage`` (the only direction this gate measures):

- ``SoftBreak`` is a markdown-reader concept; Confluence storage
  flattens internal whitespace and never emits a SoftBreak-shaped
  element.
- ``Origin`` is only populated in preserving mode; normalising parses
  (what this gate runs) intentionally drop it.

The remaining six classes that were missing in the initial 35-fixture
corpus (Emoticon, Image, LineBreak, Placeholder, RawInline,
Strikethrough) were closed in Phase 5 (2026-05-13) — they now have
focused fixtures and are hard-failed on regression.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, cast

from mdd.confluence.ir import parse_confluence_storage
from mdd.ir import ALL_CLASSES

# ---------------------------------------------------------------------------
# Classes the storage-side coverage gate cannot ever observe — see the
# module docstring for the reasoning. Anything else missing should land
# a fixture rather than join this set.
# ---------------------------------------------------------------------------

_KNOWN_GAPS: frozenset[str] = frozenset(
    {
        "Origin",  # only populated in preserving mode; not emitted in normalising parse
        "SoftBreak",  # markdown-only concept; storage flattens internal whitespace
    }
)

_BUILD_DIR = Path(__file__).resolve().parents[2] / "build"


def _count_nodes(obj: Any, counter: Counter[str]) -> None:
    """Recursively count occurrences of every IR node class in *obj*."""
    class_name = type(obj).__name__
    if class_name in ALL_CLASSES:
        counter[class_name] += 1
    # Recurse through dataclass fields.
    try:
        for f in dataclass_fields(obj):  # pyright: ignore[reportArgumentType]
            val = getattr(obj, f.name)
            if isinstance(val, list):
                for item in cast("list[object]", val):
                    if hasattr(item, "__dataclass_fields__"):
                        _count_nodes(item, counter)
            elif hasattr(val, "__dataclass_fields__"):
                _count_nodes(val, counter)
    except TypeError:
        pass


def _load_snapshots(
    snapshots_dir: Path,
) -> list[tuple[str, str]]:
    """Return (page_id, storage_xhtml) for every snapshot."""
    result: list[tuple[str, str]] = []
    for snap_dir in sorted(snapshots_dir.iterdir()):
        if not snap_dir.is_dir():
            continue
        storage_path = snap_dir / "storage.xhtml"
        if not storage_path.is_file():
            continue
        result.append((snap_dir.name, storage_path.read_text(encoding="utf-8")))
    return result


def test_corpus_coverage(corpus_root: Path) -> None:
    """Every IR node class used in production must appear at least once in the corpus.

    Classes in ``_KNOWN_GAPS`` are tolerated (storage-unobservable —
    see the module docstring). Unexpected missing classes are hard
    failures.
    """
    snapshots_dir = corpus_root / "_snapshots"
    counter: Counter[str] = Counter()
    parse_failures: list[str] = []

    for page_id, storage in _load_snapshots(snapshots_dir):
        try:
            doc = parse_confluence_storage(storage, mode="normalising")
            _count_nodes(doc, counter)
        except Exception as e:
            parse_failures.append(f"{page_id}: {e!r}")

    assert not parse_failures, (
        f"parse_confluence_storage failed on {len(parse_failures)} snapshot(s): "
        f"{parse_failures}. The corpus is supposed to parse cleanly."
    )

    coverage: dict[str, int] = {name: counter.get(name, 0) for name in sorted(ALL_CLASSES)}

    # Write JSON report
    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (_BUILD_DIR / "ir-coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
    )

    # Gaps in _KNOWN_GAPS are storage-unobservable by construction; the rest are regressions.
    regressions = [
        class_name
        for class_name, count in coverage.items()
        if count == 0 and class_name not in _KNOWN_GAPS
    ]

    assert not regressions, (
        f"IR coverage regression — these classes had fixtures before but now have zero: "
        f"{regressions}. Check build/ir-coverage.json."
    )
