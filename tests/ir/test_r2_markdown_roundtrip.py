"""R2 — Markdown → IR → Markdown round-trip tests.

Parametrised over every ``.md`` file in the corpus (fixtures/ and corpus/
subdirectories).  Markdown-only — no Confluence XHTML involved.

The R2 contract:
  Gate (normalising mode): ``parse_markdown(render_markdown(parse_markdown(md)))
  == parse_markdown(render_markdown(parse_markdown(render_markdown(parse_markdown(md)))))``
  — i.e. the canonical IR form is stable after one parse/render cycle.

Preserving-mode R2 is skipped in this session: no fixture has
``test_corpus.preserving = true`` frontmatter yet.

Per-fixture HTML diffs are written to ``build/ir-diffs/<slug>_r2.html`` on failure.

Every R2 fixture in the corpus is stable.
The blank-line-before-`:::` close fence and the trailing-blank-line
inside a code block with a `\n` terminator are now emitted by the
markdown writer, so the parse/render cycle is fixed-point on cycle 1.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import pytest

from mdd.markdown.ir import parse_markdown, render_markdown

_BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "ir-diffs"

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    m = _FRONTMATTER_RE.match(text)
    return text[m.end() :].lstrip("\n") if m else text


def _write_diff(name: str, md1: str, md2: str) -> None:
    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    differ = difflib.HtmlDiff(wrapcolumn=120)
    table = differ.make_table(
        md1.splitlines(),
        md2.splitlines(),
        fromdesc="parse→render→md (cycle 1)",
        todesc="parse→render→parse→render→md (cycle 2)",
        context=True,
        numlines=3,
    )
    (_BUILD_DIR / f"{name}.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>{table}</body></html>",
        encoding="utf-8",
    )


def _collect_md_files(corpus_root: Path) -> list[tuple[str, Path]]:
    """Return (relative_path, absolute_path) for every .md file in the corpus."""
    results: list[tuple[str, Path]] = []
    for md_path in sorted(corpus_root.rglob("*.md")):
        rel = md_path.relative_to(corpus_root)
        results.append((str(rel), md_path))
    return results


# ---------------------------------------------------------------------------
# Gate test — stable fixtures only
# ---------------------------------------------------------------------------


def test_r2_normalising_gate(corpus_root: Path) -> None:
    """R2 normalising mode — canonical IR form must be stable after one cycle."""
    md_files = _collect_md_files(corpus_root)
    failures: list[tuple[str, str]] = []
    for rel_path, md_path in md_files:
        text = _strip_frontmatter(md_path.read_text(encoding="utf-8"))
        try:
            doc1 = parse_markdown(text, mode="normalising")
            md1 = render_markdown(doc1, mode="normalising")
            doc2 = parse_markdown(md1, mode="normalising")
            md2 = render_markdown(doc2, mode="normalising")
            doc3 = parse_markdown(md2, mode="normalising")
            if doc2 != doc3:
                slug = rel_path.replace("/", "_").replace(".", "_")
                _write_diff(f"{slug}_r2", md1, md2)
                failures.append((rel_path, "doc2 != doc3 (IR not stable after 2 cycles)"))
        except Exception as e:
            failures.append((rel_path, f"ERROR: {e}"))
    if failures:
        detail = "; ".join(f"{p}: {r}" for p, r in failures)
        pytest.fail(f"R2 normalising canonical form unstable: {detail}")
