"""R3 — Storage → IR → Markdown → IR → Storage (full bidirectional) round-trip tests.

Parametrised over every snapshot in the corpus via the ``corpus_snapshots``
session fixture in ``conftest.py``.  If the corpus is absent the module
skips cleanly.

The R3 pipeline:

  storage → parse_confluence_storage → IR_a
          → render_markdown → markdown
          → parse_markdown → IR_b
          → reattach(IR_b, cached=IR_a)
          → render_confluence_storage → storage'

- Preserving mode: ``storage' == storage`` byte-for-byte for unmodified content.  Gate.
- Normalising mode: SequenceMatcher ratio ≥ 0.95 (per-fixture floor).  Gate.

Per-fixture HTML diffs are written to ``build/ir-diffs/<page_id>_r3_*.html`` on failure.

The markdown writer emits a blank line before `:::` close fences
(otherwise the reader absorbs them into the preceding paragraph),
preserves trailing newlines in code blocks via an extra blank line, and
the reattach pass restores ConfluenceMacro shape (name, params,
rich_body, plain_body) lost across the markdown leg. The normalising R3
path also calls `reattach`, because identity attributes can only survive
via the cached IR_a. Remaining xfails are markdown-leg gaps that need
structural changes.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.ir import reattach
from mdd.markdown.ir import parse_markdown, render_markdown

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
        todesc="R3 round-trip storage",
        context=True,
        numlines=3,
    )
    (_BUILD_DIR / f"{name}.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{table}</body></html>",
        encoding="utf-8",
    )


def _r3_preserving(storage: str) -> str:
    """Full R3 preserving pipeline."""
    ir_a = parse_confluence_storage(storage, mode="preserving")
    md = render_markdown(ir_a, mode="normalising")
    ir_b = parse_markdown(md, mode="normalising")
    ir_b_reattached = reattach(ir_b, ir_a)
    return render_confluence_storage(ir_b_reattached, mode="preserving")


def _r3_normalising(storage: str) -> str:
    """Full R3 normalising pipeline.

    Reattach happens in both preserving and normalising modes:
    identity attributes must survive, and can only come from the
    cached IR_a.
    """
    ir_a = parse_confluence_storage(storage, mode="normalising")
    md = render_markdown(ir_a, mode="normalising")
    ir_b = parse_markdown(md, mode="normalising")
    ir_b = reattach(ir_b, ir_a)
    return render_confluence_storage(ir_b, mode="normalising")


# ---------------------------------------------------------------------------
# Gate tests — stable fixtures only
# ---------------------------------------------------------------------------


def test_r3_preserving_gate(corpus_snapshots: list[SnapshotFixture]) -> None:
    """R3 preserving mode — byte-perfect gate for fixtures with working Origin."""
    failures: list[str] = []
    for snap in corpus_snapshots:
        storage = snap.storage_xhtml
        storage2 = _r3_preserving(storage)
        if storage != storage2:
            _write_diff(f"{snap.page_id}_r3_preserving", storage, storage2)
            failures.append(snap.page_id)
    if failures:
        pytest.fail(
            f"R3 preserving byte-perfect gate failed for: {failures}. Diffs in build/ir-diffs/"
        )


def test_r3_normalising_gate(corpus_snapshots: list[SnapshotFixture]) -> None:
    """R3 normalising mode — M1 ≥ 0.95 per-fixture floor gate."""
    failures: list[tuple[str, float]] = []
    for snap in corpus_snapshots:
        storage = snap.storage_xhtml
        storage2 = _r3_normalising(storage)
        ratio = difflib.SequenceMatcher(None, storage, storage2).ratio()
        if ratio < 0.95:
            _write_diff(f"{snap.page_id}_r3_normalising", storage, storage2)
            failures.append((snap.page_id, ratio))
    if failures:
        detail = ", ".join(f"{pid}(M1={r:.4f})" for pid, r in failures)
        pytest.fail(f"R3 normalising M1 < 0.95 for: {detail}. Diffs in build/ir-diffs/")
