"""Corpus resolver for the IR round-trip test suite.

The corpus is vendored at ``tests/corpus/confluence/``. Spec S33 §"Test layout".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "corpus" / "confluence"


# ---------------------------------------------------------------------------
# Snapshot tuple
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotFixture:
    """One corpus snapshot, ready for round-trip tests."""

    page_id: str
    storage_xhtml: str
    snapshot_dir: Path


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def corpus_root() -> Path:
    """Return the corpus root path."""
    return CORPUS_ROOT


def _load_snapshots(snapshots_dir: Path) -> list[SnapshotFixture]:
    results: list[SnapshotFixture] = []
    if not snapshots_dir.is_dir():
        return results
    for snap_dir in sorted(snapshots_dir.iterdir()):
        if not snap_dir.is_dir():
            continue
        storage_path = snap_dir / "storage.xhtml"
        if not storage_path.is_file():
            continue
        results.append(
            SnapshotFixture(
                page_id=snap_dir.name,
                storage_xhtml=storage_path.read_text(encoding="utf-8"),
                snapshot_dir=snap_dir,
            )
        )
    return results


@pytest.fixture(scope="session")
def corpus_snapshots(corpus_root: Path) -> list[SnapshotFixture]:
    """Return every snapshot as a (page_id, storage_xhtml, snapshot_dir) tuple."""
    return _load_snapshots(corpus_root / "_snapshots")


@pytest.fixture(scope="session")
def corpus_xfail_snapshots(corpus_root: Path) -> list[SnapshotFixture]:
    """Return every known-failure snapshot under ``_xfail_snapshots/``."""
    return _load_snapshots(corpus_root / "_xfail_snapshots")
