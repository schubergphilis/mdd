"""Pin the diff-table verdict of every fixture pair in the SharePoint corpus.

The corpus under ``tests/corpus/sharepoint/`` is vendored data: office
binaries plus ``.md`` siblings carrying frozen
``office_sha256_at_sync`` / ``md_sha256_at_sync`` values. Those frozen hashes
are what make each pair land on a specific cell of the reconciliation table.

Refreshing the corpus — re-harvesting from a live site, or re-running the
maintainers' de-branding pass over it — changes the binaries and therefore
the hashes. Without a pin, a refresh silently collapses the interesting cells into
``no_op`` and the corpus keeps looking healthy while covering nothing. This
module asserts the exact expected verdict per pair, so a refresh that forgets
to re-freeze a hash fails loudly and says which one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.sharepoint.diff import (
    PairAction,
    classify_pair,
    read_sync_state,
    sha256_file,
    sha256_md_content,
)

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "corpus" / "sharepoint" / "MDD - Documents"

# (relative .md path, expected verdict). One entry per fixture pair in the
# corpus; `test_matrix_is_exhaustive` fails if the corpus grows a pair that is
# not listed here.
EXPECTED_VERDICTS: dict[str, PairAction] = {
    # Realistic site content: everything in sync.
    "Example-Word.docx.md": PairAction.NO_OP,
    "Example-PowerPoint.pptx.md": PairAction.NO_OP,
    "Example-Folder/Example-Word-Folder.docx.md": PairAction.NO_OP,
    "Markdown-First/Example-Templated-Word.docx.md": PairAction.NO_OP,
    "Markdown-First/Example-Templated-PowerPoint.pptx.md": PairAction.NO_OP,
    "Templated/Example-Templated-Word.docx.md": PairAction.NO_OP,
    "Templated/Example-Templated-PowerPoint.pptx.md": PairAction.NO_OP,
    # Purpose-built fixtures for the cells the real site does not cover.
    "diff-table/both-no-sync-block/Foo.docx.md": PairAction.FIRST_SYNC_BOTH_DOCX_WINS,
    "diff-table/docx-changed/Foo.docx.md": PairAction.DOCX_TO_MD,
    "diff-table/md-changed-update-true/Foo.docx.md": PairAction.MD_TO_DOCX,
    "diff-table/md-changed-update-false/Foo.docx.md": PairAction.SKIP_MD_UPDATE,
    "diff-table/divergence/Foo.docx.md": PairAction.DIVERGED,
    "diff-table/skip-both-changed/Foo.docx.md": PairAction.SKIP_MD_UPDATE,
}

# Fixtures that deliberately have only one side of the pair. `classify_pair`
# never sees them — the walker decides these before pairing — so they are pinned
# by on-disk shape instead: (present file, absent sibling, cell it stands for).
UNPAIRED_FIXTURES: dict[str, tuple[str, PairAction]] = {
    "diff-table/docx-only-no-md/Foo.docx": (
        "diff-table/docx-only-no-md/Foo.docx.md",
        PairAction.FIRST_SYNC_DOCX_AUTHORITATIVE,
    ),
    "diff-table/md-only-no-docx/Foo.docx.md": (
        "diff-table/md-only-no-docx/Foo.docx",
        PairAction.FIRST_SYNC_MD_AUTHORITATIVE,
    ),
}
UNPAIRED = set(UNPAIRED_FIXTURES)


def _sibling_markdown_paths() -> set[str]:
    """Return every ``*.docx.md`` / ``*.pptx.md`` in the corpus, corpus-relative."""
    return {
        str(md.relative_to(CORPUS_ROOT))
        for md in CORPUS_ROOT.rglob("*.md")
        if md.name.endswith((".docx.md", ".pptx.md"))
    }


def test_corpus_root_exists() -> None:
    assert CORPUS_ROOT.is_dir(), f"corpus missing at {CORPUS_ROOT}"


@pytest.mark.parametrize(("relpath", "expected"), sorted(EXPECTED_VERDICTS.items()))
def test_pair_verdict(relpath: str, expected: PairAction) -> None:
    """Each fixture pair still lands on the diff-table cell it was built for."""
    md_path = CORPUS_ROOT / relpath
    office_path = md_path.with_suffix("")
    assert md_path.is_file(), f"missing corpus fixture {relpath}"
    assert office_path.is_file(), f"missing office sibling for {relpath}"

    sync_state = read_sync_state(md_path)
    verdict = classify_pair(office_path, md_path, sync_state=sync_state)

    assert verdict == expected, (
        f"{relpath}: expected {expected}, got {verdict}.\n"
        f"  office_sha256_at_sync = {sync_state.office_sha256_at_sync}\n"
        f"  actual office sha256  = {sha256_file(office_path)}\n"
        f"  md_sha256_at_sync     = {sync_state.md_sha256_at_sync}\n"
        f"  actual md sha256      = {sha256_md_content(md_path)}\n"
        "If you refreshed the corpus, re-freeze the hashes that are meant to "
        "match and leave the ones that are meant to differ alone."
    )


def test_matrix_is_exhaustive() -> None:
    """Every sibling ``.md`` in the corpus is pinned (or explicitly unpaired)."""
    found = _sibling_markdown_paths()
    accounted = set(EXPECTED_VERDICTS) | {p for p in UNPAIRED if p.endswith(".md")}
    assert found - accounted == set(), (
        f"corpus grew fixture pairs with no pinned verdict: {sorted(found - accounted)}"
    )
    assert accounted - found == set(), (
        f"pinned verdicts reference fixtures that no longer exist: {sorted(accounted - found)}"
    )


_UNPAIRED_SHAPES = sorted((present, absent) for present, (absent, _) in UNPAIRED_FIXTURES.items())


@pytest.mark.parametrize(("present", "absent"), _UNPAIRED_SHAPES)
def test_unpaired_fixture_shape(present: str, absent: str) -> None:
    """The single-sided first-encounter fixtures still have exactly one side."""
    assert (CORPUS_ROOT / present).is_file(), f"missing corpus fixture {present}"
    assert not (CORPUS_ROOT / absent).exists(), (
        f"{present} is meant to be a first-encounter fixture, but {absent} now exists"
    )


def test_every_diff_table_cell_is_covered() -> None:
    """The corpus covers every ``PairAction`` a committed fixture can represent.

    ``WORD_LOCKED`` needs a transient ``~$Foo.docx`` lock file, which is never
    committed. ``MD_ONLY`` is the walker's doc-only alias for
    ``FIRST_SYNC_MD_AUTHORITATIVE`` and shares its fixture.
    """
    unreachable = {PairAction.WORD_LOCKED, PairAction.MD_ONLY}
    covered = set(EXPECTED_VERDICTS.values()) | {cell for _, cell in UNPAIRED_FIXTURES.values()}
    missing = set(PairAction) - unreachable - covered
    assert missing == set(), f"diff-table cells with no corpus fixture: {sorted(missing)}"
