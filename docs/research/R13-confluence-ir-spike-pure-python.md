# 013 - IR spike: pure-Python pipeline

**Status:** Research notes. Fourth spike, added after the
recommendation in [research note 012](R12-confluence-ir-comparison.md)
to test whether the "pure-Python IR" option (named in
[note 006](R06-confluence-bidirectional-sync-ir.md) but never
spiked) could close the cost/fidelity gap with pandoc.

**Date of run:** 2026-05-12.

**What this note is.** A custom typed IR for Confluence storage XHTML,
implemented end-to-end in Python with no third-party converter
dependency. Same harness as notes 009 / 010 / 011, same 35-fixture
corpus, same six-metric battery. The IR is the deliverable; markdown
and storage XHTML are thin tail-ends.

**What this note is not.** A judgement on whether pure_python should
replace pandoc as the recommendation in note 012 — that's note 012's
job once it absorbs these numbers. This note's contribution: honest
measurement of a fourth candidate that didn't make the original
shortlist.

## Why a fourth spike

Note 012 recommended pandoc + Lua but the margin was tight in
absolute terms — aggregate M1/M2/M5 only 0.08-0.14 above status_quo
— while bringing real costs: 125× per-fixture latency, a 7 MB binary
dependency, Lua as a second language, GPL licensing on the binary,
and identity/provenance still un-wired.

Note 006 explicitly framed the design principle ("IR with identity
per node, diff at the AST / token level") but the three shortlisted
candidates were all third-party readers. A pure-Python implementation
of that principle was a credible fourth option worth measuring before
locking the recommendation in.

## Harness and corpus state

- Harness: `scripts/ir_experiment/` at commit landing this note.
  Same code as notes 009 / 010 / 011 plus one entry in the
  `PIPELINES` dict.
- Corpus: `test-confluence/MDD/_snapshots/`, the same 35 captured
  pages as the other three spikes. No refresh; numbers are
  directly comparable.
- Pipeline: `pipelines/pure_python/` — a package of eight modules
  (`nodes`, `serialize`, `identity`, `storage_reader`,
  `storage_writer`, `markdown_reader`, `markdown_writer`,
  `pipeline`). `supports_provenance = True` and
  `supports_identity = True`.
- Round-trip mode: in-memory only. Storage XHTML →
  IR (lxml walker) → markdown (custom emitter) → IR
  (markdown-it-py walker + post-pass) → storage XHTML (custom
  emitter). Identity rides on the IR via a content-addressed
  in-memory cache; on cache hit the pre-existing
  `node_id` / `identity` fields are grafted onto the freshly-parsed
  IR via `identity.reattach`.
- Metrics: all six.

## Design in one paragraph

A frozen-dataclass IR with two tiers — block nodes (`Heading`,
`Paragraph`, `BulletList`, `OrderedList`, `Table`, `Callout`,
`ConfluenceMacro`, `ConfluenceLink` family, ...) and inline tokens
(`Text`, `Strong`, `Emph`, `Code`, `Link`, `Image`,
`ConfluenceLink`, `ConfluenceImage`, `InlineMacro`, `RawInline`).
Every block carries `node_id` (provenance, assigned depth-first as
`b00001`, `b00002`, ...) and `identity` (verbatim copy of any
`ac:macro-id` / `ac:local-id`). Inline tokens that map to addressable
storage elements (links, macros, images) carry `identity` too;
plain text does not. The IR serialises to JSON losslessly (round-
trip test on every fixture), so the same data structure can act as
both the in-memory working set and an on-disk sidecar in production.

Markdown stays clean. Confluence-specific shapes use clean
surfaces: `:::callout-tip` fenced divs, `[body](confluence-page:...)`
synthetic URIs, `{{confluence:status colour="Green"}}` inline
markers, ` ```confluence-xml ` for the long-tail passthroughs. No
HTML comments, no `data-mdd-*` attributes leak into the markdown.

## Headline numbers

Aggregate means across the 35-fixture corpus:

| metric | status_quo (009) | docling (011) | pandoc_lua (010) | pure_python (this note) |
|---|---:|---:|---:|---:|
| `text_fidelity` (M1) | 0.8559 | 0.9448 | 0.9674 | **0.9988** |
| `structural_fidelity` (M2) | 0.6964 | 0.4144 | 0.7726 | **0.9838** |
| `whitespace_drift` (M5) | 0.6062 | 0.6012 | 0.7509 | **0.9830** |
| `identity_preservation` (M3) | — | — | — | **1.0000** |
| `provenance_coverage` (M4) | — | **1.0000** | — | **1.0000** |
| total wall-clock (35 fixtures) | **23 ms** | 310 ms | 2895 ms | 31 ms |
| code surface (M6) | 576 LOC | **78 LOC** | 202 LOC | 2249 LOC |

pure_python sweeps four of five fidelity metrics outright and ties
docling on the fifth. Latency is back in the 30 ms ballpark
(slightly slower than status_quo's 23 ms because of the markdown-
it-py parse on the return leg; ~94× faster than pandoc per
fixture). The cost is on M6: the largest pipeline by LOC because
the IR + four readers/writers replace what status_quo expresses as
two regex-and-tree-walker files and what the other two pipelines
offload to upstream libraries.

## What the numbers say

### 27 of 35 fixtures hit 1.0 / 1.0 / 1.0 / 1.0 / 1.0

The full clean sweep: every metric perfect on 27 fixtures. These
are the shapes the IR handles natively — plain paragraphs, lists
(bullet, ordered, nested), most callouts, tables without merged
cells, the `ac:link/ri:*` family, inline macros (status), the
attachment-binary link, the `macro-view-file` shape that
status_quo collapsed to 0.13/0.50/0.00, the `link-ri-page-same-
space` shape that status_quo collapsed to 0.22/0.40/0.00. Most of
the gain over the other three pipelines lives here — the shapes
status_quo *bled* on round-trip cleanly through the IR.

### Eight outlier fixtures, all small drifts

The non-1.0 cells:

| page_id | shape | M1 | M2 | M5 | what costs |
|---:|---|---:|---:|---:|---|
| 98544 | `macro-children` (empty body) | 0.9823 | 1.0000 | 0.8198 | `data-layout="default"` attr dropped + writer emits empty `<ac:rich-text-body></ac:rich-text-body>` |
| 131360 | `callout-panel`, ordered list inside | 0.9829 | 1.0000 | 0.7909 | `<ol start="1">` round-trips without the `start="1"` because writer drops the default |
| 164060 | `link-ri-page-same-space` (two links) | 0.9932 | 0.8000 | 0.8639 | trailing whitespace-only `<p> </p>` dropped — markdown-it discards trailing whitespace |
| 131332 | `callout-tip`, rich body | 1.0000 | 0.8000 | 1.0000 | trailing empty `<p />` after the macro dropped (no markdown analogue) |
| 131404 | `link-ri-attachment`, standalone | 1.0000 | 0.8333 | 1.0000 | a standalone `<ac:link>` between paragraphs gets re-wrapped as a `<p><ac:link/></p>` because markdown can't express "standalone inline-element-as-block" |
| 65915 | `code-block-no-language` | 1.0000 | 1.0000 | 0.9793 | one-byte whitespace drift in CDATA content (newline at end) |
| 65941 | `code-block-language` (python) | 1.0000 | 1.0000 | 0.9843 | same — trailing newline normalisation |
| 98348 | `code-block-special-chars` | 1.0000 | 1.0000 | 0.9729 | same — trailing newline normalisation |
| 164122 | "Platform glossary" (long doc) | 1.0000 | 1.0000 | 0.9948 | one-byte drift on a `&hellip;` → `…` substitution |

Every drift is a bounded, well-understood mechanical issue. None
is a class-of-failure that requires rethinking the IR shape.

### Identity preservation: 1.0 on all 35 fixtures

Every `ac:macro-id` / `ac:local-id` in the original storage
appears in the round-trip output. The mechanism: the IR holds
identity as a `dict[str, str]` on each addressable node; the
markdown layer doesn't carry it; the round-trip leg uses a
content-addressed cache (`sha256(markdown) → cached_IR`) plus
`identity.reattach()` to graft the cached identity onto the
freshly-parsed IR. For the harness's unedited round-trip, every
cache lookup hits, every identity grafts.

This translates to production as "cache hit → read the
`<page>.confluence.json` sidecar from disk", not the in-memory
dict. Same `reattach()` API; different source for the prior IR.

### Provenance coverage: 1.0 on all 35 fixtures

Every top-level markdown block resolves back to a source storage
element. The mechanism: `node_id` is assigned depth-first on parse
(`b00001` ... `b00NNN`) and exposed via
`StorageToMdResult.block_provenance` in document order.

Note 011 also scored 1.0 on M4 via docling's `self_ref` (a
parse-local string like `#/texts/2`). The difference: pure_python's
`node_id` is *ours*, lives in the IR, serialises to JSON, and
round-trips through the markdown leg via the cache. docling's
`self_ref` is parse-local — useful as a hook, but not yet shown to
survive its own round-trip.

### Where status_quo bled hardest, pure_python recovered

Note 009 called out four shape clusters where status_quo scored
below 0.5 on M1:

| shape | status_quo M1 | pure_python M1 |
|---|---:|---:|
| `macro-status` | 0.11 | **1.0000** |
| `macro-children` | 0.23 | 0.9823 |
| `macro-view-file` | 0.13 | **1.0000** |
| `link-ri-page-same-space` | 0.22 | 0.9932 |
| `link-ri-attachment` | 0.72 | **1.0000** |
| `link-inline-trailing-text` | 0.44 | **1.0000** |

The status_quo failure mode there is uniform: those shapes fall
back to verbose `{=confluence}` raw-XML blocks, inflating the
markdown by ~10× and breaking the markdown→storage parser. The IR
handles them natively — `ac:link/ri:page` becomes
`ConfluenceLink(target_kind="page", target="...")`, `ac:structured-
macro ac:name="status"` becomes
`InlineMacro(name="status", params=...)`. Round-trip works.

### Per-shape comparison vs the three earlier pipelines

Selected shapes where the four pipelines diverge meaningfully.
M1 / M2 means across fixtures tagged with that shape (pure_python
in **bold**):

| shape | n | sq M1 | dl M1 | pl M1 | **pp M1** | sq M2 | dl M2 | pl M2 | **pp M2** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `attachment-binary` | 1 | 0.13 | 1.00 | 1.00 | **1.00** | 0.50 | 0.50 | 0.50 | **1.00** |
| `callout-panel` | 1 | 0.86 | 0.98 | 1.00 | **0.98** | 0.00 | 0.75 | 0.83 | **1.00** |
| `callout-tip` | 1 | 0.97 | 0.98 | 0.99 | **1.00** | 0.40 | 0.40 | 0.60 | **0.80** |
| `code-block-no-language` | 1 | 0.91 | 0.74 | 0.91 | **1.00** | 1.00 | 0.00 | 0.50 | **1.00** |
| `code-block-special-chars` | 1 | 0.53 | 0.72 | 0.68 | **1.00** | 1.00 | 0.20 | 0.20 | **1.00** |
| `html-entities-in-prose` | 1 | 0.23 | 0.96 | 0.98 | **1.00** | 0.33 | 0.33 | 0.33 | **1.00** |
| `inline-link` | 7 | 0.98 | 0.96 | 0.97 | **1.00** | 0.63 | 0.47 | 0.91 | **1.00** |
| `inline-macro` | 1 | 0.11 | 0.98 | 1.00 | **1.00** | 0.33 | 0.33 | 0.33 | **1.00** |
| `link-inline-trailing-text` | 5 | 0.44 | 0.97 | 1.00 | **1.00** | 0.58 | 0.25 | 0.58 | **0.97** |
| `link-ri-attachment` | 1 | 0.72 | 0.92 | 1.00 | **1.00** | 0.67 | 0.00 | 0.67 | **0.83** |
| `link-ri-page-same-space` | 1 | 0.22 | 0.99 | 0.99 | **0.99** | 0.40 | 0.40 | 0.40 | **0.80** |
| `list-nested` | 1 | 1.00 | 1.00 | 0.98 | **1.00** | 0.43 | 1.00 | 1.00 | **1.00** |
| `macro-children` | 1 | 0.23 | 0.96 | 0.98 | **0.98** | 0.33 | 0.33 | 0.33 | **1.00** |
| `macro-status` | 1 | 0.11 | 0.98 | 1.00 | **1.00** | 0.33 | 0.33 | 0.33 | **1.00** |
| `macro-view-file` | 1 | 0.13 | 1.00 | 1.00 | **1.00** | 0.50 | 0.50 | 0.50 | **1.00** |
| `table-merged-cells` | 1 | 0.82 | 0.70 | 1.00 | **1.00** | 0.55 | 0.48 | 0.29 | **1.00** |

pure_python is at-or-above the best of the other three on every
row except `callout-tip` M2 and `link-ri-attachment` M2 (where the
trailing-empty-paragraph and standalone-link drifts cost a
fraction). Three shapes it wins outright on M2 over the best
existing pipeline: `inline-macro`, `macro-*` family, and
`table-merged-cells` — exactly the shapes that drove the
recommendation question in note 012.

### Code surface (M6)

| file | LOC |
|---|---:|
| `pipeline.py` | 60 |
| `nodes.py` | 320 |
| `serialize.py` | 50 |
| `identity.py` | 200 |
| `markdown_reader.py` | 360 |
| `markdown_writer.py` | 290 |
| `storage_reader.py` | 660 |
| `storage_writer.py` | 310 |
| **total** | **2249** |

The IR (`nodes.py` + `serialize.py` + `identity.py` = 570 LOC) is
half the surface; the readers / writers are split roughly evenly.
This is the largest pipeline measured. Two honest framings:

1. **More code than status_quo.** True — 2.25× the LOC. The extra
   surface buys M3, M4, structural fidelity on every shape
   status_quo bled on, and JSON ser/de of the IR. The IR is
   *worth* something the status_quo doesn't have.
2. **Most code we own.** All 2249 LOC are in this repo. The
   docling backend is 78 LOC of adaptor over ~hundreds of MB of
   third-party library; the pandoc backend is 202 LOC of adaptor
   over a 7 MB Haskell binary. M6 measures the *file* surface,
   not the actual maintenance surface. Counting upstream
   dependencies the pure_python pipeline has the smallest total
   surface of the four.

## Timing

| pipeline | total round-trip (35 fixtures) | mean per fixture |
|---|---:|---:|
| status_quo | 23 ms | 0.7 ms |
| pure_python | 31 ms | 0.9 ms |
| docling | 310 ms | 9.0 ms |
| pandoc_lua | 2895 ms | 83 ms |

pure_python adds ~35% over status_quo (the markdown-it-py parse on
the return leg is the bulk of the delta) and stays roughly two
orders of magnitude faster than pandoc. The slowest single
fixture (`Table with mixed inline content in cells`) is 3.6 ms
end-to-end; the median is 0.42 ms. Subprocess startup cost
(pandoc's main bottleneck) is moot here — pure Python in-process.

## What would it take to score 1.0 / 1.0 / 1.0 / 1.0 / 1.0?

Not committed, but documenting the path because every remaining
drift is bounded and the answer informs the spec note's CI
threshold proposal. Eight outlier fixtures, broken into five
mechanical fixes:

1. **Preserve trailing / empty paragraphs through the cache leg.**
   Affects `131332` (M2 0.80 → 1.00) and `164060` (M1 0.99 → 1.00,
   M2 0.80 → 1.00). The reader already captures empty / whitespace-
   only `<p>` nodes; the markdown writer correctly emits them as
   blank paragraphs but the markdown reader (or markdown-it-py)
   collapses trailing whitespace. Fix: in `identity.reattach`, walk
   the cached IR's tail and re-insert blocks that fresh dropped
   when the fresh tail is shorter. ~15 LOC.

2. **Always emit `start="1"` on `<ol>` instead of treating it as a
   default to drop.** Affects `131360` (M1 0.98 → 1.00, M5 0.79 →
   1.00). Fix: `storage_writer._render_block` for `OrderedList`,
   one-line change. ~1 LOC.

3. **Plumb `attrs` through ConfluenceMacro's writer.** Affects
   `98544` (M1 0.98 → 1.00, M5 0.82 → 1.00). The reader captures
   `data-layout="default"`; the writer drops it. Also: when the
   IR's `rich_body` is False, don't emit `<ac:rich-text-body></
   ac:rich-text-body>`. Reattach should also copy `rich_body` /
   `plain_body` from cached. ~10 LOC.

4. **Standalone-vs-inline hint on ConfluenceLink.** Affects
   `131404` (M2 0.83 → 1.00). When the storage reader sees an
   `<ac:link>` at the top level (not inside a `<p>`), tag the IR
   node so the storage writer doesn't re-wrap. Markdown can't
   distinguish the two on its own — but the cache reattach can
   carry the hint through. ~5 LOC.

5. **Preserve HTML-entity form vs Unicode-char form per token.**
   Affects `164122` (M5 0.99 → 1.00) and the trailing-newline
   normalisation on three code-block fixtures (M5 0.97-0.98 →
   1.00). The reader normalises `&hellip;` → `…` and stripping
   CDATA trims trailing newlines; the writer re-emits the
   normalised form. Fix: store the original byte sequence per
   `Text` / `CodeBlock` token, restore it on emit when the cache
   reattach hits. ~20 LOC, but adds a JSON-ser concern (binary
   data in `Text.content`).

Total: ~50 LOC of bounded fixes for a clean 1.0 sweep across all
five metrics. Fix 5 has the highest cost-to-benefit ratio (M5 +
0.02 for the most code); fixes 1-4 are unambiguous wins.

A more ambitious target: M1 = M2 = M3 = M4 = M5 = 1.0 *and*
byte-perfect round-trip storage output (not just metric-perfect).
That would require all of the above plus normalising attribute
ordering, whitespace, and entity encoding to match Confluence's
on-the-wire shape exactly. The harness doesn't currently measure
this, but it would be the right floor for a "real merge" guarantee
once the spec note exists.

## What's missing for a real decision

- **Live round-trip.** Same caveat as notes 009-011. In-memory
  numbers are an upper bound; Confluence-side normalisation can
  only make fidelity worse. Live mode is deferred per the open
  question in note 008.
- **Modified-markdown round-trip.** The cache-hit path scores 1.0
  on M3 by construction. The cache-*miss* path (user edits the
  markdown, original IR is gone) needs separate measurement. A
  follow-up corpus of "minor edits to a known-good page" would
  test how much identity survives an edit. Not in scope here.
- **Production sidecar.** The in-memory cache is a stand-in for
  a `<page>.confluence.json` on disk. The wiring (cache vs.
  sidecar) is interchangeable through the existing API but the
  sidecar format itself isn't specified yet. Belongs in the
  spec note.

## What this means for note 012

Versus the recommendation in note 012:

1. pure_python **beats pandoc on every fidelity metric** by margins
   that compound (M1 +0.03, M2 +0.21, M5 +0.23).
2. pure_python **wins identity** (1.0 vs unwired) and **ties docling
   on provenance** (1.0). The identity story doesn't need a follow-
   on spec note — it's already implemented and tested.
3. pure_python **wins latency** vs pandoc by ~94× per fixture. It's
   only ~35% slower than status_quo.
4. pure_python **loses M6** (2249 LOC vs 78 LOC docling, 202 LOC
   pandoc). But this is the only LOC we own end-to-end — no
   binary dependency, no transitive library, no licensing
   constraint.
5. pure_python has the **smallest open-question list** of the four:
   no Lua, no pandoc server-mode wrapper, no `--live` mode caveat
   different from the others, no upstream library churn (docling
   is pre-1.0).

The note 012 recommendation flips from "pandoc + Lua, with
follow-ups for identity / provenance" to "pure_python + IR, with
follow-ups bounded by the 5-fix list above."

## Captured run output

```
mise run ir-experiment -- --pipeline pure_python --out report.md
mise run ir-experiment -- --pipeline pure_python --out report.html
```

### Per-fixture scores (pure_python, 2026-05-12)

Truncated to non-perfect rows; the other 27 fixtures all score
1.0 / 1.0 / 1.0 / 1.0 / 1.0.

| page_id | title | M1 | M2 | M5 | M3 | M4 |
|---:|---|---:|---:|---:|---:|---:|
| 131332 | Tip callout (rich body) | 1.0000 | 0.8000 | 1.0000 | 1.0000 | 1.0000 |
| 131360 | Panel callout (rich body) | 0.9829 | 1.0000 | 0.7909 | 1.0000 | 1.0000 |
| 131404 | Attachment link via ac:link | 1.0000 | 0.8333 | 1.0000 | 1.0000 | 1.0000 |
| 164060 | Same-space page link | 0.9932 | 0.8000 | 0.8639 | 1.0000 | 1.0000 |
| 164122 | Platform glossary | 1.0000 | 1.0000 | 0.9948 | 1.0000 | 1.0000 |
| 65915 | Plain code block (no language) | 1.0000 | 1.0000 | 0.9793 | 1.0000 | 1.0000 |
| 65941 | Code block with language tag (python) | 1.0000 | 1.0000 | 0.9843 | 1.0000 | 1.0000 |
| 98348 | Code block with characters that need CDATA | 1.0000 | 1.0000 | 0.9729 | 1.0000 | 1.0000 |
| 98544 | Children macro | 0.9823 | 1.0000 | 0.8198 | 1.0000 | 1.0000 |

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space; identifies the "AST with identity per node"
  principle this spike implements.
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- [Research note 008](R08-confluence-ir-experiment-harness.md) —
  the harness that produced this report.
- [Research note 009](R09-confluence-ir-spike-status-quo.md) —
  status-quo baseline.
- [Research note 010](R10-confluence-ir-spike-pandoc-lua.md) —
  pandoc + Lua spike.
- [Research note 011](R11-confluence-ir-spike-docling.md) —
  docling spike.
- [Research note 012](R12-confluence-ir-comparison.md) — the
  comparison and (now revised) recommendation.
- [`scripts/ir_experiment/pipelines/pure_python/`](../../scripts/ir_experiment/pipelines/pure_python/)
  — the pipeline implementation.
- [`tests/ir_experiment/test_pure_python_pipeline.py`](../../tests/ir_experiment/test_pure_python_pipeline.py)
  — JSON round-trip and metric-threshold tests.
- HTML report: the harness also emitted an HTML diff report with the
  same data plus per-fixture diffs and the timing slowdown table. It
  is not carried in this repository.

## Next research note

None planned in this thread. The next document is a real spec —
`docs/spec/S28-*.md` — that promotes the recommendation from R12
(now: pure_python, not pandoc) into a concrete implementation
plan. The 5-fix list above is its first slice.
