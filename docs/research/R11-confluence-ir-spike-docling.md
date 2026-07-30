# 011 - IR spike: docling pipeline

**Status:** Research notes. Second of three planned spikes feeding the
IR-foundation recommendation in [research note 012] (TBC).

**Date of run:** 2026-05-12.

**What this note is.** The docling spike under
[research note 008](R08-confluence-ir-experiment-harness.md). It wires
`DoclingDocument` into the same harness used for
[note 009 (status quo)](R09-confluence-ir-spike-status-quo.md) and runs
the same metric battery against the same 35-fixture corpus. Docling
parses storage XHTML through its HTML reader, emits markdown via the
built-in serializer, then re-parses that markdown and re-emits HTML
for the comparison side of the round-trip.

**What this note is not.** A judgement about adopting docling — that
falls out of note 012 once the Pandoc spike (010) also runs. Docling
treats the input as generic HTML; it has no native understanding of
the Confluence storage XHTML namespace (`ac:`, `ri:`). The numbers
below therefore measure docling's *generic* fidelity, which is the
honest baseline for asking "is the structural layer alone good enough
to bolt Confluence semantics on top?"

## Harness and corpus state

- Harness: [scripts/ir_experiment/](../../scripts/ir_experiment/) at
  commit landing this note. Same as note 009 plus the
  `pipelines/docling.py` adapter and wall-clock timing instrumentation.
- Corpus: `test-confluence/MDD/_snapshots/`, the same 35 captured
  pages as note 009. No refresh; numbers are directly comparable.
- Pipeline: `pipelines/docling.py` — `supports_provenance = True` (one
  `self_ref` per top-level text item in the parsed DoclingDocument),
  `supports_identity = False` (Confluence `ac:macro-id` / `ac:local-id`
  are dropped by docling's HTML reader).
- Round-trip mode: in-memory only. Storage XHTML →
  `DoclingDocument(InputFormat.HTML)` → `export_to_markdown()` →
  `DoclingDocument(InputFormat.MD)` → `export_to_html(html_head='')`
  with the page-div wrapper stripped so comparisons line up with the
  source fragment shape.
- Metrics implemented: M1 (text fidelity), M2 (structural fidelity),
  M3 (identity preservation, gated off here), M4 (provenance
  coverage), M5 (whitespace drift), M6 (code surface). New since
  note 009: wall-clock timing per direction, surfaced in the report.

## Headline numbers

| metric | docling mean | status_quo mean (note 009) | delta |
|---|---:|---:|---:|
| `text_fidelity` | 0.9448 | 0.8559 | **+0.089** |
| `structural_fidelity` | 0.4144 | 0.6964 | **−0.282** |
| `whitespace_drift` | 0.6012 | 0.6062 | −0.005 |
| `identity_preservation` | — | — | — |
| `provenance_coverage` | 1.0000 | — | new |

The single most striking pair: docling **beats** status_quo on text
fidelity (it preserves *content* more cleanly because it normalises
through a structured intermediate that doesn't fall back to verbose
`{=confluence}` raw blocks) but **loses** on structural fidelity (it
flattens the block tree because it has no model of Confluence
macros and aggressively re-paragraphs hard-wrapped prose).

`provenance_coverage = 1.0` reflects the design choice: every
top-level text item in the parsed DoclingDocument has a stable
`self_ref` (e.g. `#/texts/2`). The pipeline exposes one per markdown
block. This is the "yes, docling has per-block identity hooks"
signal. Whether those refs survive a fresh parse — i.e. provide a
*round-trippable* identity — is M3's question and gated off here
because we don't currently round-trip them through markdown.

## What the numbers say

### Healthy: paragraphs, simple inline, nested lists

Pure prose round-trips well on M1 (≥0.99 for most paragraph and
heading fixtures). Nested lists score 1.00/1.00 on M1/M2 —
docling's list model survives the markdown intermediate cleanly.
Plain bullet list: 1.00/1.00. Where status_quo over-paragraphs
list items (`p: 1→6`, note 009), docling preserves the list shape.

`provenance_coverage = 1.00` across the whole corpus: each fixture
yields between 3 and 21 text items with stable refs in document
order. This is a real improvement over status_quo, which exposed
no provenance.

### Brittle: hard-wrapped paragraphs explode on re-parse

Top structural-fidelity offender: "Multiple paragraphs" — 4
paragraphs become 12 in the round-trip (M2 = 0.00). Why: docling's
markdown export inserts a blank line after every hard line wrap in
prose, and the markdown re-parse then treats each line as its own
paragraph. The character content is preserved (M1 = 0.99) but the
block tree inflates. The same shape sinks "External URL link"
(`p: 2→6`, M2 = 0.00), "Acme Internal Engineering Handbook"
(M2 = 0.28), and "Platform glossary" (M2 = 0.04).

This is fixable in a future variant by either (a) configuring
docling's markdown serializer to not hard-wrap, or (b)
post-processing the markdown to rejoin paragraphs before round-trip.
Neither was attempted in this spike — the point is to measure
docling out of the box.

### Brittle: code blocks lose structure

`Plain code block (no language)` — M2 = 0.00, M1 = 0.74. Docling's
HTML reader treats `<pre><code>` correctly as a code block (good),
but on the way back through markdown, the code fence parses as
expected and the surrounding prose explodes into per-line `<p>` —
plus the inline `<code>` spans in the prose round-trip as
`<span class='inline-group'><code>...</code></span>` wrappers, not
`<p>`. The harness's M2 counts those `span` wrappers as missing
`p` blocks, deepening the drift.

`Code block with characters that need CDATA` scores M1 = 0.72.
Status_quo scored 0.53 here, so docling is *better* on the
CDATA-sensitive content (no verbose escape inflation) but still
not whole — docling's markdown export reflows the code-block
content lightly, and the diff is real.

### Brittle: tables shrink

`Plain table` — M2 = 0.95 (very close), M1 = 0.95. Tables come
through with their shape mostly intact. But `Table with mixed
inline content in cells` drops to M1 = 0.73 / M2 = 0.30, and
`Table with merged cells` is the worst overall M1 at 0.70.

Docling's HTML reader collapses rich inline structure inside
`<td>` cells (likely model-specific: the docling table model is
oriented towards layout-detected tables, not authored HTML
tables). The merged-cells case loses the merge metadata entirely —
expected, since the cell-merge is encoded as `rowspan` / `colspan`
that docling normalises away.

### Brittle: Confluence-specific elements are invisible

This is the by-design limitation, not a bug. Storage XHTML elements
docling doesn't recognise (`ac:structured-macro`, `ac:link`,
`ri:page`, `ri:url`, ...) are silently dropped at the wrapper
level. Macro body content survives; the macro identity does not.
Examples from the run:

- Tip / panel / warning / note / info callouts — body text scores
  M1 ≥ 0.97 each (content survives) but the macro wrapper is lost
  entirely. Notably docling here scores *higher* on M1 than
  status_quo on most callouts (status_quo collapses to blockquote
  with content drift); the *structural* loss is the same shape
  (macro → no macro).
- `ac:link / ri:page` and `ac:link / ri:attachment` — the link
  collapses to plain text (the title or alt-text gets emitted),
  the page/attachment reference is lost. M1 stays ≥0.92 because
  the visible content is preserved; M2 hits 0.00 because the
  expected `ac:link` block is gone.
- `ac:structured-macro` `status`, `children`, `expand`,
  `view-file` — the macro is dropped; some surface text in the
  body survives. M1 ≥ 0.96 in each case (much better than
  status_quo, which expanded these to verbose XML).

### Where the metrics disagree

- M1 high, M2 low: paragraph-heavy fixtures with hard-wrapped
  source. Status_quo had this disagreement on lists; docling has
  it on prose. Same family of failure, different shape.
- M1 low, M2 reasonable: the merged-cell table case. M1 = 0.70,
  M2 = 0.48. The cell content shrinks (M1 sees the loss); the
  outer block count survives (M2 misses it).
- `provenance_coverage = 1.0` everywhere: by construction. M4 only
  measures *coverage*, not whether refs round-trip. A future M4-bis
  that compares storage→md→storage refs against the originals
  would tell us whether the self_refs are *useful* for merge
  semantics or merely present.

## Timing

New instrumentation since note 009: wall-clock per direction. Not
a benchmark — single-threaded, no warmup, cold caches — but the
ratios are informative.

| pipeline | total round-trip (35 fixtures) | mean per fixture |
|---|---:|---:|
| status_quo | 23 ms | 0.65 ms |
| docling | ~330 ms | ~9.4 ms |

Docling is ~15× slower per fixture in memory. The slowest fixture
(`Platform glossary`) takes 71 ms end-to-end vs status_quo's
2 ms on the same input. This is comfortably within "research
tool" territory — a full 35-fixture run is sub-second on either
pipeline — but worth recording in case the corpus grows by an
order of magnitude or the harness ends up in CI.

The variance (max 71 ms, min 1.7 ms) tracks document size; the
docling HTML reader has noticeable startup amortised across each
`convert()` call. A persistent converter (already what we have:
one `DocumentConverter` instance reused per pipeline) is the cheap
win and is in place.

## What's missing for a real decision

- **M3 identity preservation** — gated off here. To turn it on
  we'd need to round-trip `ac:macro-id` / `ac:local-id` through
  the markdown intermediate, which docling's HTML reader
  currently discards as unknown attributes. A variant pipeline
  could pre-extract those IDs to a sidecar map; deferred.
- **Structural fidelity discount for paragraph-explosion** — the
  hard-wrap paragraph explosion is a real structural drift but it
  inflates the M2 penalty in a way that conflates "real
  structural loss" with "cosmetic over-segmentation". Note 012
  should weigh this honestly.
- **Live round-trip** — same caveat as note 009. The numbers are
  an upper bound; Confluence-side normalisation can only make
  fidelity worse.

## What this means for the comparison

Versus the status-quo baseline (note 009), docling:

1. **Wins on content preservation** (M1 +0.09). It doesn't fall
   back to verbose raw-XML blocks for shapes the writer doesn't
   recognise — the content just comes through as prose.
2. **Wins on provenance hooks** (M4 = 1.00 vs n/a). Per-block
   `self_ref` is real, stable within a parse, and free.
3. **Loses on structural fidelity** (M2 −0.28). The block tree
   gets flattened both by paragraph re-segmentation and by
   silent dropping of unknown elements. The structural loss is
   different in shape from status_quo's (which kept the macros
   but mangled the inline shapes) but not smaller.
4. **Identical on whitespace drift** (M5 effectively tied). Both
   pipelines emit different whitespace from the original on most
   fixtures; neither is meaningfully tighter than the other.
5. **Massively wins on code surface** (M6 = 78 LOC vs 576 LOC).
   78 lines of adaptor code drive the docling backend; the
   status_quo numbers count the full custom converter
   implementation. This is real but partial: docling itself is a
   substantial dependency, just not one we maintain.

For note 012 to recommend docling over status_quo, the open
questions to answer:

- Can the hard-wrap paragraph explosion be neutralised cheaply
  (serializer flag or post-process)?
- Can macro identity be preserved via a sidecar map without
  bloating the pipeline?
- Does the `self_ref` provenance survive a round-trip well enough
  to be load-bearing for a merge engine, or is it parse-local
  only?

If yes / yes / yes, docling is plausible. If any of those is no,
the Pandoc-Lua path (note 010, pending) is the next candidate to
evaluate before deciding.

## Open questions specific to this spike

1. **Does the markdown serializer have a "no hard-wrap" flag?**
   Worth a quick look before note 012 — if it does, a re-run
   would tighten M2 significantly and could change the
   recommendation.
2. **Is the `<span class='inline-group'>` wrapper avoidable?**
   It's an artefact of docling's HTML serializer choosing
   span-over-p when a paragraph contains inline children at the
   top level. Looks fixable via the serializer config.
3. **Cost of attaching Confluence semantics on top.** Could a
   thin layer on either side of docling's parse — pre-extract
   macros to sidecar before parse, re-emit macros from sidecar
   after parse — recover the structural loss without docling
   itself needing to know about Confluence? This is the central
   question for the comparison note.

## Captured run output

```
mise run ir-experiment -- --pipeline docling --out report.md
```

### Per-fixture scores (docling, 2026-05-12)

| page_id | title | text_fidelity | structural_fidelity | whitespace_drift | provenance_coverage |
|---:|---|---:|---:|---:|---:|
| 131253 | Image referenced by external URL | 0.9445 | 0.5556 | 0.3612 | 1.0000 |
| 131272 | External URL link | 0.8889 | 0.0000 | 0.0000 | 1.0000 |
| 131305 | Table with mixed inline content in cells | 0.7302 | 0.2963 | 0.0000 | 1.0000 |
| 131332 | Tip callout (rich body) | 0.9843 | 0.4000 | 0.8406 | 1.0000 |
| 131360 | Panel callout (rich body) | 0.9762 | 0.7500 | 0.6864 | 1.0000 |
| 131384 | Layout three-equal columns | 0.9990 | 0.6000 | 0.9899 | 1.0000 |
| 131404 | Attachment link via ac:link | 0.9159 | 0.0000 | 0.1346 | 1.0000 |
| 163977 | Nested mixed lists | 1.0000 | 1.0000 | 0.9282 | 1.0000 |
| 164003 | Multiple paragraphs | 0.9917 | 0.0000 | 0.9172 | 1.0000 |
| 164022 | Horizontal rule | 0.9722 | 0.5714 | 0.6998 | 1.0000 |
| 164045 | Warning callout (rich body) | 0.9943 | 0.3333 | 0.9426 | 1.0000 |
| 164060 | Same-space page link | 0.9865 | 0.4000 | 0.7959 | 1.0000 |
| 164069 | Attachment link | 1.0000 | 0.5000 | 0.8305 | 1.0000 |
| 164089 | Expand macro | 0.9970 | 0.0000 | 0.9704 | 1.0000 |
| 164105 | Status macro | 0.9756 | 0.3333 | 0.7500 | 1.0000 |
| 164122 | Platform glossary | 0.9972 | 0.0435 | 0.9080 | 1.0000 |
| 65915 | Plain code block (no language) | 0.7391 | 0.0000 | 0.0000 | 1.0000 |
| 65941 | Code block with language tag (python) | 0.9148 | 0.5000 | 0.1536 | 1.0000 |
| 65975 | Multiple inline links in one paragraph | 0.9756 | 0.0000 | 0.6992 | 1.0000 |
| 66011 | List items with inline formatting | 0.9980 | 0.7778 | 0.8035 | 1.0000 |
| 66045 | Plain table | 0.9453 | 0.9474 | 0.0000 | 1.0000 |
| 66067 | Info callout (rich body) | 0.9960 | 0.7143 | 0.9601 | 1.0000 |
| 98308 | Plain paragraph | 0.9979 | 0.0000 | 0.9787 | 1.0000 |
| 98328 | Plain blockquote | 0.9015 | 0.0000 | 0.0000 | 1.0000 |
| 98348 | Code block with characters that need CDATA | 0.7242 | 0.2000 | 0.0000 | 1.0000 |
| 98367 | Top-level heading (h1) | 0.9734 | 0.7500 | 0.7585 | 1.0000 |
| 98386 | Bullet list | 1.0000 | 1.0000 | 0.9500 | 1.0000 |
| 98412 | Ordered list | 0.9468 | 0.6250 | 0.4150 | 1.0000 |
| 98431 | Inline formatting | 0.9579 | 0.0000 | 0.5614 | 1.0000 |
| 98491 | Note callout (rich body) | 0.9899 | 0.7273 | 0.7853 | 1.0000 |
| 98505 | Layout two-equal columns | 0.9964 | 0.5333 | 0.9522 | 1.0000 |
| 98521 | Table with merged cells | 0.7042 | 0.4839 | 0.0000 | 1.0000 |
| 98544 | Children macro | 0.9646 | 0.3333 | 0.6396 | 1.0000 |
| 98559 | Acme Internal Engineering Handbook | 0.9948 | 0.2800 | 0.8614 | 1.0000 |
| 98579 | Meeting notes — Platform sync, 2026-05-11 | 0.9927 | 0.8481 | 0.7687 | 1.0000 |

### Worst per metric

`text_fidelity`:

| page_id | title | score |
|---:|---|---:|
| 98521 | Table with merged cells | 0.7042 |
| 98348 | Code block with characters that need CDATA | 0.7242 |
| 131305 | Table with mixed inline content in cells | 0.7302 |
| 65915 | Plain code block (no language) | 0.7391 |
| 131272 | External URL link | 0.8889 |

`structural_fidelity`:

| page_id | title | score | drift |
|---:|---|---:|---|
| 131272 | External URL link | 0.0000 | ac:link: 0→1; p: 2→6 |
| 131404 | Attachment link via ac:link | 0.0000 | li: 0→1; ol: 0→1; p: 4→11 |
| 164003 | Multiple paragraphs | 0.0000 | p: 4→12 |
| 164089 | Expand macro | 0.0000 | macro:expand: 1→0; p: 2→4 |
| 65915 | Plain code block (no language) | 0.0000 | macro:code: 0→1; p: 2→6 |

### Timing aggregate

| direction | mean (ms) | median (ms) | min (ms) | max (ms) |
|---|---:|---:|---:|---:|
| `storage_to_md` | 5.03 | 3.22 | 1.27 | 19.16 |
| `md_to_storage` | 3.58 | 2.12 | 0.54 | 18.88 |
| total | 8.60 | 5.19 | 1.93 | 38.04 |

Total round-trip across 35 fixtures: ~330 ms wall clock.

### Code surface (M6)

Total LOC: **78** (`pipelines/docling.py`). Plus the docling
library as an upstream dependency — not counted under M6's
"pipeline implementation" definition, but worth flagging as the
real maintenance cost.

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space; identifies docling as one of three candidate
  foundations.
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- [Research note 008](R08-confluence-ir-experiment-harness.md) —
  the harness that produced this report.
- [Research note 009](R09-confluence-ir-spike-status-quo.md) —
  status-quo baseline, directly comparable numbers.
- [`scripts/ir_experiment/pipelines/docling.py`](../../scripts/ir_experiment/pipelines/docling.py) —
  the pipeline adaptor.
- HTML report: the harness also emitted a side-by-side HTML diff
  report with the same data plus the timing slowdown table. It is
  not carried in this repository.

## Next research note

`R10-confluence-ir-spike-pandoc-lua.md` — Pandoc CLI with a custom
Lua writer for Confluence storage XHTML. Same corpus, same metric
battery. Pandoc was deferred chronologically (010) but the
comparison is symmetric — note 012 will combine all three.
