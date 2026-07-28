"""R1 — Storage → IR → Storage round-trip tests.

Parametrised over every snapshot in the corpus via the ``corpus_snapshots``
session fixture in ``conftest.py``.  If the corpus is absent the entire
module skips cleanly via that fixture.

Spec S33 §"R1 — Storage → IR → Storage":
- Preserving mode: ``render_confluence_storage(parse_confluence_storage(x, mode="preserving"),
  mode="preserving") == x`` byte-for-byte.  Gate.
- Normalising mode: SequenceMatcher ratio ≥ 0.995 (M1 proxy).  Gate.

Per-fixture HTML diffs are written to ``build/ir-diffs/<page_id>_r1_*.html``
on failure.

Plan 106 D6 (2026-05-13) honours reader-captured whitespace and
shape metadata in either mode via the typed fields (``omit_start``,
``compact``, ``trailing_ws``, ``body_leading_ws``, ``body_trailing_ws``,
``no_wrapper``) and re-substitutes entity-form PUA markers in macro
params. No fixtures are xfailed for R1 today.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage

if TYPE_CHECKING:
    from .conftest import SnapshotFixture

_BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "ir-diffs"


def _write_diff(name: str, original: str, rendered: str) -> None:
    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    differ = difflib.HtmlDiff(wrapcolumn=120)
    table = differ.make_table(
        original.splitlines(),
        rendered.splitlines(),
        fromdesc="original storage",
        todesc="rendered storage",
        context=True,
        numlines=3,
    )
    (_BUILD_DIR / f"{name}.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{table}</body></html>",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Preserving-mode gate — runs for non-xfail fixtures only
# ---------------------------------------------------------------------------


def test_r1_preserving_gate(corpus_snapshots: list[SnapshotFixture]) -> None:
    """R1 preserving mode — byte-perfect gate for fixtures with working Origin."""
    failures: list[str] = []
    for snap in corpus_snapshots:
        storage = snap.storage_xhtml
        doc = parse_confluence_storage(storage, mode="preserving")
        rendered = render_confluence_storage(doc, mode="preserving")
        if storage != rendered:
            _write_diff(f"{snap.page_id}_r1_preserving", storage, rendered)
            failures.append(snap.page_id)
    if failures:
        pytest.fail(
            f"R1 preserving byte-perfect gate failed for: {failures}. Diffs in build/ir-diffs/"
        )


# ---------------------------------------------------------------------------
# Normalising-mode gate — runs for non-xfail fixtures only
# ---------------------------------------------------------------------------


def test_r1_normalising_gate(corpus_snapshots: list[SnapshotFixture]) -> None:
    """R1 normalising mode — M1 ≥ 0.995 gate for fixtures with working writer."""
    failures: list[tuple[str, float]] = []
    for snap in corpus_snapshots:
        storage = snap.storage_xhtml
        doc = parse_confluence_storage(storage, mode="normalising")
        rendered = render_confluence_storage(doc, mode="normalising")
        ratio = difflib.SequenceMatcher(None, storage, rendered).ratio()
        if ratio < 0.995:
            _write_diff(f"{snap.page_id}_r1_normalising", storage, rendered)
            failures.append((snap.page_id, ratio))
    if failures:
        detail = ", ".join(f"{pid}(M1={r:.4f})" for pid, r in failures)
        pytest.fail(f"R1 normalising M1 < 0.995 for: {detail}. Diffs in build/ir-diffs/")
