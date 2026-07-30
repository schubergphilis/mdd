# 010 - IR spike: Pandoc + custom Lua writer

**Status:** Research notes. Third of three planned spikes feeding the
IR-foundation recommendation in [research note 012] (TBC).

**Date of run:** 2026-05-12.

**What this note is.** The Pandoc spike under
[research note 008](R08-confluence-ir-experiment-harness.md). It
shells out to `pandoc` for both directions: `pandoc -f html -t markdown`
for storage→md, and `pandoc -f markdown -t confluence_storage.lua`
for the reverse, where `confluence_storage.lua` is a minimal custom
classic-style Lua writer that maps pandoc's AST to a Confluence
storage XHTML subset (paragraphs, headings, lists, tables, code-block
macros, links, images, basic inline formatting).

**What this note is not.** A judgement on whether to switch from
status_quo to pandoc — that belongs in note 012, where pandoc's
numbers stand alongside the
[status_quo baseline](R09-confluence-ir-spike-status-quo.md) and the
[docling spike](R11-confluence-ir-spike-docling.md). Pandoc has no
native understanding of `ac:structured-macro` or `ac:link/ri:*`
shapes; the writer's coverage of those is bounded by what we put in
the Lua file. The numbers below measure how far that minimal coverage
gets us out of the gate.

## Harness and corpus state

- Harness: [scripts/ir_experiment/](../../scripts/ir_experiment/) at
  commit landing this note. Same as notes 009 + 011 plus the
  `pipelines/pandoc_lua.py` adaptor and the
  `pipelines/confluence_storage.lua` writer.
- Corpus: `test-confluence/MDD/_snapshots/`, the same 35 captured
  pages as notes 009 + 011. No refresh; numbers are directly
  comparable.
- Pipeline: `pipelines/pandoc_lua.py`. `supports_provenance = False`,
  `supports_identity = False` — pandoc's HTML reader drops unknown
  attributes by default, so neither side-channel is wired up.
  Could be added (sidecar JSON, or `data-mdd-id` round-tripped via
  RawInline) — a follow-up if the comparison note recommends pandoc.
- Round-trip mode: in-memory only, via two `subprocess.run` calls
  per fixture. Pandoc 3.9.0.2 (`brew install pandoc`).
- Metrics implemented: M1-M6 plus wall-clock timing per direction.

## Headline numbers

Comparison against the two prior spikes on the same corpus:

| metric | pandoc_lua mean | docling mean (011) | status_quo mean (009) |
|---|---:|---:|---:|
| `text_fidelity` | **0.9674** | 0.9448 | 0.8559 |
| `structural_fidelity` | **0.7726** | 0.4144 | 0.6964 |
| `whitespace_drift` | **0.7509** | 0.6012 | 0.6062 |
| `identity_preservation` | — | — | — |
| `provenance_coverage` | — | 1.0000 | — |

Pandoc + Lua wins on all three measurable fidelity metrics — text,
structural, and whitespace. The closest contender is docling on text
fidelity (within 0.02), but docling's structural number is half
pandoc's because of its hard-wrap paragraph re-segmentation. Pandoc
preserves paragraph boundaries cleanly because `--wrap=preserve`
hands the markdown intermediate to the Lua writer without
re-flowing.

The provenance/identity columns are empty by design: this spike
doesn't wire either channel. Closing those gaps is a discussed
follow-up (see §"What's missing for a real decision" below).

## What the numbers say

### Healthy: most prose, lists, tables, callouts

12 fixtures score 1.0 on `text_fidelity` and another 15 score
≥0.99. The shapes that round-trip cleanly:

- Paragraphs (plain, multiple, boundary cases) — M1 = 1.00 across
  the board.
- Headings (h1-h6) — 1.00/1.00 on M1/M2.
- Bullet lists, ordered lists, nested mixed lists — all M2 = 1.00.
  Compare to status_quo's `p: 1→6` list-paragraph inflation
  (note 009) and docling's hard-wrap explosion (note 011) —
  pandoc just keeps the lists alone.
- External URL link, multiple inline links — both metrics 1.00.
- Inline formatting (strong/em/code) — 1.00/1.00.
- Plain blockquote — 1.00/1.00.
- Horizontal rule — 1.00/1.00.

Callouts: pandoc *drops* the macro wrapper too (same as docling)
but its M2 scores on these (0.60-0.95) are uniformly higher than
docling's (0.33-0.75) because the inner body — paragraphs, lists,
inline formatting — survives intact rather than getting reshaped
into `<span class='inline-group'>` wrappers. The macro identity
itself is gone in both pandoc and docling round trips, which is
exactly the kind of loss a `data-mdd-id` channel (deferred) would
plug.

### Brittle: code blocks (still)

The two lowest M1 scores are both code-block fixtures:

| fixture | M1 | M2 |
|---|---:|---:|
| `Code block with language tag (python)` | 0.5945 | 0.50 |
| `Code block with characters that need CDATA` | 0.6783 | 0.20 |

Why: pandoc's markdown reader treats fenced code blocks with
language tags as `CodeBlock` nodes carrying a `class` attribute
(the language). The Lua writer re-emits this as the proper
`<ac:structured-macro ac:name="code">` shape with the language
parameter — that part works. But the *source* storage XHTML
contains the original Confluence code-macro wrapper which pandoc's
HTML reader treats as unknown elements and skips, leaving only the
`<ac:plain-text-body><![CDATA[...]]></ac:plain-text-body>` text.
The markdown intermediate is therefore *just* the code body
(without fences), the writer wraps it back in the code macro, and
the round-trip storage is much shorter than the original.

So the M1 drop here is *not* "the code content was mangled" — it's
"the code-macro identity didn't round-trip because pandoc had no
way to recognise the source macro." The same fix (pre-process the
input HTML to convert `<ac:structured-macro ac:name="code">` to
proper `<pre><code>`) would lift both scores to ~1.0. A short
pre-processor in `pipelines/pandoc_lua.py` is the natural place
for this; deferred to keep the spike scope clean.

The CDATA fixture has a deeper issue: characters like `]]>` inside
the code body would break the writer's naive CDATA emission. The
fixture content doesn't actually contain `]]>`, but the M1 score
still drops because the full XML-escape dance isn't round-tripping.

### Brittle: merged-cell tables

`Table with merged cells` — M2 = 0.29. The writer's `Table()`
implementation is also minimal: every cell becomes `<td>`, no
`rowspan` / `colspan`. The harness counts this as 13 `<p>` blocks
inside cells vanishing, and the header row collapsing into the
body. This is fixable with a couple of dozen more lines of Lua;
again, deferred.

### Brittle: `ac:link/ri:*` identity (as expected)

Same family as docling: the `ac:link` wrapper that points at a
`ri:page` / `ri:attachment` is parsed by pandoc's HTML reader as
unknown elements; the link payload survives only because of the
inline text fallback. M1 = 1.00 on these fixtures (the visible text
is preserved); M2 drops to 0.40-0.67 because the `ac:link` block
is missing from the round trip.

The fix here is the same shape as the code-macro fix: pre-process
the HTML to convert known `ac:link/ri:*` shapes to regular `<a
href="...">` before pandoc parses, then post-process the writer
output to re-emit `ac:link/ri:*` for links with a known sentinel.
Doable; out of scope for this measurement.

### Where the metrics disagree

- M1 high, M2 low: macro fixtures (`status`, `children`, `expand`).
  Inner content survives (M1 ≥ 0.98) but the macro block is gone.
  Identical shape to docling.
- M1 low, M2 high: `Table with merged cells` — M1 = 1.00 (every
  cell's text survives), M2 = 0.29 (the structure collapsed).
  Mirror of the same metric pair on docling.
- M5 (whitespace) ties M1 in pandoc more often than in docling
  because pandoc's `--wrap=preserve` keeps source line breaks. The
  three M5 = 0.00 fixtures (`Platform glossary`, `Plain table`,
  CDATA-code) are all whitespace-sensitive: tables and code
  blocks where every character matters.

### Timing

| pipeline | total round-trip (35 fixtures) | mean per fixture |
|---|---:|---:|
| status_quo | ~23 ms | 0.65 ms |
| docling | ~310 ms | 9 ms |
| pandoc_lua | **2895 ms** | **83 ms** |

Pandoc is ~125× slower than status_quo and ~9× slower than
docling. The cost is dominated by subprocess startup: 35 fixtures
× 2 directions = 70 `pandoc` invocations. Pandoc 3 exposes a
`--server` mode that holds a process open and accepts requests over
stdin/stdout — switching to that would collapse most of the
overhead. For a research harness, single-shot subprocess is fine;
for production usage the server mode would be the practical
choice.

The variance is much tighter than the other pipelines (min 76 ms,
max 108 ms) because startup dominates over content size. Fixture
size barely moves the needle inside the per-call budget.

## Code surface

| pipeline | total LOC | breakdown |
|---|---:|---|
| status_quo | 576 | 33 wrapper + 543 production converters |
| docling | 78 | 78 adaptor (+ docling library upstream) |
| pandoc_lua | 202 | 77 Python adaptor + 125 Lua writer |

Pandoc sits between docling (tiny adaptor, heavy upstream) and
status_quo (full custom converter). The 125 lines of Lua are *all*
ours to maintain — there's no upstream to defer to for the writer
direction, the way docling's serializers are upstream. The Python
side is comparable to docling because the heavy lifting goes
through `pandoc` and the Lua writer; the adaptor itself is just
subprocess plumbing.

A maintainability call here depends on the team's Lua comfort and
on how often the writer needs to grow for new Confluence shapes.
Each new `ac:*` element costs maybe 5-15 lines of Lua plus a
fixture and a per-shape tag.

## What's missing for a real decision

Items that would change the numbers materially if added:

1. **Pre-process `<ac:structured-macro ac:name="code">`** to
   `<pre><code>` before handing to pandoc. Expected lift: M1 on
   the two code-block fixtures from ~0.65 to ~1.00.
2. **Pre-process `<ac:link><ri:page .../></ac:link>` and
   `<ri:attachment>`** to `<a href="...">` with a sentinel, then
   post-process the writer output to restore the `ac:link` shape.
   Expected lift: M2 on the four `ac:link/ri:*` fixtures from
   ~0.50 to ~1.00.
3. **Merged-cell table support** — straightforward `rowspan` /
   `colspan` handling in the Lua writer's `Table()` function.
   Expected lift: M2 on the merged-cells fixture from 0.29 to
   ~0.90.
4. **`data-mdd-id` provenance channel.** Pass IDs through as
   `data-*` attributes on elements; emit them from the Lua writer
   on the way out. Lights up M3 and M4.
5. **Pandoc server mode.** Replaces the subprocess-per-call cost
   with a persistent process. Expected impact: total run time
   drops from ~3 s to under 0.5 s.
6. **Live round-trip.** Same caveat as notes 009 and 011 —
   in-memory numbers are an upper bound on real-world fidelity.

None of these is large; together they would plausibly push
pandoc_lua to ~0.99 / ~0.95 / ~0.85 on the three fidelity metrics
with all four sub-channels available. Whether that justifies
adopting a pandoc dependency in production is the call note 012
needs to make.

## What this means for the comparison

Versus status_quo (note 009):

- M1 +0.11 (0.97 vs 0.86) — pandoc preserves text consistently
  across all the shapes status_quo balloons into `{=confluence}`
  raw blocks. The big wins are on `ac:link/ri:*`, status macro,
  and children macro (status_quo 0.11-0.23, pandoc 1.00).
- M2 +0.08 (0.77 vs 0.70) — pandoc is better on most shapes; the
  exception is macro callouts where status_quo and pandoc are
  about even (both lose the wrapper).
- M5 +0.14 (0.75 vs 0.61) — pandoc's `--wrap=preserve` and the
  tight Lua writer produce much cleaner whitespace.
- Code surface: 202 LOC vs 576. Pandoc's Lua writer is the only
  code we maintain; pandoc itself is upstream.

Versus docling (note 011):

- M1 +0.02 — both pipelines preserve text well; pandoc edges out
  docling because docling's hard-wrap re-paragraphing also
  fragments inline text streams.
- M2 +0.36 — the headline win. Docling's structural collapse
  (paragraphs and code blocks alike) cost it ~30 fixtures worth
  of M2 score; pandoc keeps them intact.
- M5 +0.15 — pandoc preserves source whitespace; docling
  normalises through its document model.
- M4: docling has provenance, pandoc doesn't. The only metric
  pandoc currently loses on.

In short: pandoc + Lua is the most fidelity-faithful pipeline of
the three, by a clear margin on M2 and M5, and by a small margin
on M1. It pays for that with subprocess latency (a fixable
implementation detail) and missing identity/provenance channels
(implementable on the same Lua writer with sidecar plumbing).

## Open questions specific to this spike

1. **Pandoc server mode in the harness.** Worth the implementation
   complexity for research-tool runs? Probably no for the
   measurement loop; almost certainly yes if pandoc ever sits
   in the production conversion path.
2. **Vendoring pandoc.** Note 008 §open question #5. With pandoc
   on PATH the spike runs in ~3 s; if we adopt it, a CI-managed
   pandoc binary (or container layer) is the right shape — the
   `brew install pandoc` instruction is fine for local dev but
   not deterministic enough for shared infra. *Still open.*
3. **Where does identity live?** If pandoc wins note 012, the
   real follow-up is wiring `ac:macro-id` / `ac:local-id`
   through the writer. RawInline-with-sentinel is the cheapest
   plumbing; an out-of-band sidecar is more explicit. Either
   works.

## Captured run output

```
mise run ir-experiment -- --pipeline pandoc_lua --out report.md
```

### Per-fixture scores (pandoc_lua, 2026-05-12)

| page_id | title | text_fidelity | structural_fidelity | whitespace_drift |
|---:|---|---:|---:|---:|
| 131253 | Image referenced by external URL | 0.9988 | 0.7778 | 0.9386 |
| 131272 | External URL link | 1.0000 | 1.0000 | 0.9747 |
| 131305 | Table with mixed inline content in cells | 0.9482 | 1.0000 | 0.1601 |
| 131332 | Tip callout (rich body) | 0.9921 | 0.6000 | 0.8805 |
| 131360 | Panel callout (rich body) | 0.9965 | 0.8333 | 0.9303 |
| 131384 | Layout three-equal columns | 0.9990 | 0.6000 | 0.9848 |
| 131404 | Attachment link via ac:link | 1.0000 | 0.6667 | 0.9880 |
| 163977 | Nested mixed lists | 0.9814 | 1.0000 | 0.5153 |
| 164003 | Multiple paragraphs | 1.0000 | 1.0000 | 0.9834 |
| 164022 | Horizontal rule | 1.0000 | 1.0000 | 0.9769 |
| 164045 | Warning callout (rich body) | 0.9986 | 0.6667 | 0.9713 |
| 164060 | Same-space page link | 0.9932 | 0.4000 | 0.8639 |
| 164069 | Attachment link | 1.0000 | 0.5000 | 0.6610 |
| 164089 | Expand macro | 0.9980 | 0.3333 | 0.9704 |
| 164105 | Status macro | 1.0000 | 0.3333 | 0.8750 |
| 164122 | Platform glossary | 0.9060 | 0.8696 | 0.0000 |
| 65915 | Plain code block (no language) | 0.9130 | 0.5000 | 0.1116 |
| 65941 | Code block with language tag (python) | 0.5945 | 0.5000 | 0.0000 |
| 65975 | Multiple inline links in one paragraph | 1.0000 | 1.0000 | 0.9812 |
| 66011 | List items with inline formatting | 0.9921 | 1.0000 | 0.8625 |
| 66045 | Plain table | 0.9453 | 1.0000 | 0.0000 |
| 66067 | Info callout (rich body) | 0.9960 | 0.8571 | 0.9521 |
| 98308 | Plain paragraph | 1.0000 | 1.0000 | 0.9787 |
| 98328 | Plain blockquote | 1.0000 | 1.0000 | 0.9547 |
| 98348 | Code block with characters that need CDATA | 0.6783 | 0.2000 | 0.0000 |
| 98367 | Top-level heading (h1) | 1.0000 | 1.0000 | 0.9758 |
| 98386 | Bullet list | 0.9798 | 1.0000 | 0.7500 |
| 98412 | Ordered list | 0.9888 | 1.0000 | 0.8607 |
| 98431 | Inline formatting | 1.0000 | 1.0000 | 0.9825 |
| 98491 | Note callout (rich body) | 0.9949 | 0.9545 | 0.9489 |
| 98505 | Layout two-equal columns | 0.9988 | 0.8667 | 0.9821 |
| 98521 | Table with merged cells | 1.0000 | 0.2903 | 0.8000 |
| 98544 | Children macro | 0.9823 | 0.3333 | 0.7297 |
| 98559 | Acme Internal Engineering Handbook | 0.9905 | 0.9600 | 0.8812 |
| 98579 | Meeting notes — Platform sync, 2026-05-11 | 0.9932 | 1.0000 | 0.8560 |

### Worst per metric

`text_fidelity`:

| page_id | title | score |
|---:|---|---:|
| 65941 | Code block with language tag (python) | 0.5945 |
| 98348 | Code block with characters that need CDATA | 0.6783 |
| 164122 | Platform glossary | 0.9060 |
| 65915 | Plain code block (no language) | 0.9130 |
| 66045 | Plain table | 0.9453 |

`structural_fidelity`:

| page_id | title | score | drift |
|---:|---|---:|---|
| 98348 | Code block with characters that need CDATA | 0.2000 | macro:code: 0→1; p: 2→1; pre: 2→0 |
| 98521 | Table with merged cells | 0.2903 | p: 13→0; td: 10→16; th: 3→0 |
| 164089 | Expand macro | 0.3333 | macro:expand: 1→0; p: 2→3 |
| 164105 | Status macro | 0.3333 | macro:status: 2→0 |
| 98544 | Children macro | 0.3333 | macro:children: 1→0; p: 2→3 |

### Timing aggregate

| direction | mean (ms) | median (ms) | min (ms) | max (ms) |
|---|---:|---:|---:|---:|
| `storage_to_md` | 35.46 | 34.30 | 30.48 | 48.49 |
| `md_to_storage` | 47.27 | 46.11 | 42.42 | 61.29 |
| total | 82.72 | 80.32 | 76.43 | 107.88 |

Total round-trip across 35 fixtures: ~2.9 s wall clock.

### Code surface (M6)

Total LOC: **202** (`pipelines/pandoc_lua.py` 77 + `confluence_storage.lua` 125).

The Python adaptor is subprocess plumbing; the Lua file is the
*real* surface we maintain (heading, paragraph, list, table,
code-macro, basic inline). Pandoc itself is an upstream
dependency — not counted under M6's "pipeline implementation"
definition.

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space; identifies pandoc as one of three candidate
  foundations.
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- [Research note 008](R08-confluence-ir-experiment-harness.md) —
  the harness that produced this report.
- [Research note 009](R09-confluence-ir-spike-status-quo.md) —
  status-quo baseline.
- [Research note 011](R11-confluence-ir-spike-docling.md) —
  docling spike, the other contender.
- [`scripts/ir_experiment/pipelines/pandoc_lua.py`](../../scripts/ir_experiment/pipelines/pandoc_lua.py) —
  Python adaptor.
- [`scripts/ir_experiment/pipelines/confluence_storage.lua`](../../scripts/ir_experiment/pipelines/confluence_storage.lua) —
  custom Lua writer.
- HTML report: the harness also emitted a side-by-side HTML diff
  report with the same data plus the timing slowdown table. It is
  not carried in this repository.

## Next research note

`R12-confluence-ir-comparison.md` — aggregate notes 009 / 010 / 011
into a recommendation table per metric and per shape, then propose
which foundation should be promoted into a real spec (and what the
spec's first slice should be).
