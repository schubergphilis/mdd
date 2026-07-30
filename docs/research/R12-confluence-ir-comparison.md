# 012 - IR foundation comparison and recommendation

**Status:** Research notes. **Recommendation note (revised
2026-05-12 — see "Revision" below).** Closes the spike thread opened
in [research note 006](R06-confluence-bidirectional-sync-ir.md) and
runs through
[007 corpus](R07-confluence-test-corpus.md),
[008 harness](R08-confluence-ir-experiment-harness.md),
[009 status quo](R09-confluence-ir-spike-status-quo.md),
[010 pandoc + Lua](R10-confluence-ir-spike-pandoc-lua.md),
[011 docling](R11-confluence-ir-spike-docling.md),
[013 pure-Python IR](R13-confluence-ir-spike-pure-python.md).

**Date of write-up:** 2026-05-12. All numbers below come from the
harness runs captured in notes 009 / 010 / 011 / 013 on the same
35-fixture corpus from
`test-confluence/MDD/_snapshots/`.

## Revision — 2026-05-12

The original recommendation (preserved below as "Original
recommendation") was pandoc + Lua. **A fourth spike (note 013)
shipped after that recommendation: a pure-Python typed IR end-to-
end, no third-party converter, identity and provenance wired
natively.** It beats pandoc on every fidelity metric by clear
margins, costs ~94× less wall-clock per fixture, and brings the
identity / provenance follow-ups the pandoc recommendation depended
on into the spike itself rather than deferring them to a spec.

**Revised recommendation: pure-Python IR (note 013).** Promote
`scripts/ir_experiment/pipelines/pure_python/` to
`src/mdd/confluence/ir/` behind a feature flag in `mdd confluence
export`. The remaining gap to byte-perfect round-trip is a five-fix
list (~50 LOC) called out at the end of note 013.

The rest of this note keeps the original analysis intact so the
trade-off rationale is auditable, with the fourth column folded in.

## TL;DR

**Recommend pure-Python typed IR** (note 013) as the IR foundation.
It beats every other candidate on every measurable fidelity metric:
M1 = 0.9988, M2 = 0.9838, M5 = 0.9830, M3 = 1.00 (only candidate
that wires it), M4 = 1.00 (ties docling). Latency stays in the
status_quo ballpark (~31 ms vs 23 ms total for the corpus) with no
external dependency — no pandoc binary, no docling library, no Lua,
no GPL constraint. M6 (code surface) is the only metric where it
loses, at 2249 LOC vs status_quo's 576: the cost of owning a typed
IR. The trade is heavily favourable.

The original pandoc + Lua recommendation is preserved below; both
analyses are useful context for the spec note.

### Original recommendation (preserved)

Recommend pandoc + custom Lua writer as the IR foundation, with
two follow-ups before it can replace the production status-quo
pipeline: (1) wire identity / provenance through the Lua writer
(M3 / M4 hooks), and (2) close the remaining writer gaps for code
blocks and merged-cell tables. Both are bounded, well-scoped tasks
visible directly in the metric tables.

Note 013 supersedes this recommendation by implementing those
follow-ups directly inside a new pipeline that also outperforms
pandoc on every measured fidelity metric. Below numbers and
analysis preserved for comparability.

Why not status_quo: it's *correct* on most shapes but brittle on
the namespaced ones (`ac:link/ri:*`, `ac:structured-macro` —
status, children) where it falls back to verbose
`{=confluence}` raw-XML blocks. Aggregate text-fidelity is 0.86;
individual fixtures drop to 0.11.

Why not docling: highest provenance affordances of the three but
loses badly on structural fidelity (0.41) because of hard-wrap
paragraph re-segmentation and silent dropping of Confluence
namespaced elements. Recovering both costs more code than the
pandoc path costs.

## Headline numbers

Aggregate means across the 35-fixture corpus:

| metric | status_quo (009) | docling (011) | pandoc_lua (010) | pure_python (013) | best |
|---|---:|---:|---:|---:|---|
| `text_fidelity` (M1) | 0.8559 | 0.9448 | 0.9674 | **0.9988** | pure_python |
| `structural_fidelity` (M2) | 0.6964 | 0.4144 | 0.7726 | **0.9838** | pure_python |
| `whitespace_drift` (M5) | 0.6062 | 0.6012 | 0.7509 | **0.9830** | pure_python |
| `identity_preservation` (M3) | — | — | — | **1.0000** | pure_python |
| `provenance_coverage` (M4) | — | **1.0000** | — | **1.0000** | tie |
| total wall-clock (35 fixtures) | **23 ms** | 310 ms | 2895 ms | 31 ms | status_quo |
| code surface (M6) | 576 LOC | **78 LOC** | 202 LOC | 2249 LOC | docling |

**pure_python (note 013) wins four of five fidelity metrics
outright and ties the fifth.** Pandoc holds none. Docling holds
none. Status_quo holds latency (the closest competitor on that
axis is pure_python at ~35% slower). The code-surface column has
to be read alongside the upstream dependency cost — docling is
small to integrate but pulls in a substantial library; pandoc is
medium to integrate over a 7 MB binary; status_quo is in-house
code; pure_python is in-house with *zero* external dependency and
~3.9× more LOC than status_quo — the cost of owning a typed IR
with JSON serialisation, identity tracking, and provenance hooks.

## What each spike taught us

### Status quo (note 009)

- Correct on plain prose, headings, tables, simple lists.
- Brittle on `ac:link/ri:*` and inline macros: the
  markdown→storage path doesn't recognise the inline shapes the
  storage→markdown path emits, so the round-trip falls back to
  literal `{=confluence}` raw-XML blocks. Five fixtures score
  below 0.5 on M1, three of them below 0.25.
- No identity, no provenance.

### Docling (note 011)

- Generic-HTML model: `ac:*` and `ri:*` elements are unknown,
  silently dropped at wrapper level, body content survives.
- Text fidelity surprisingly strong (0.94) because content
  doesn't balloon into raw XML; it just becomes plain text.
- Structural fidelity weak (0.41) for two reasons: (1) hard-wrap
  paragraph re-segmentation (markdown re-parse sees each
  hard-wrapped source line as a separate paragraph), and
  (2) macros / `ac:link` wrappers are gone in round-trip.
- `self_ref` provides real per-block provenance hooks (M4 = 1.00).
  Stable within a parse; whether they round-trip is an open
  question docling itself doesn't address.

### Pandoc + Lua (note 010)

- 12 fixtures score 1.0 on text fidelity; another 15 score ≥0.99.
- Wins structural fidelity by a clear margin: lists, paragraphs,
  headings, and most callout bodies round-trip without
  re-segmentation. `--wrap=preserve` is the key flag.
- Callouts and inline macros: pandoc drops the wrapper (same as
  docling) but inner content survives more cleanly (~10
  fixtures' worth of M2 improvement over docling).
- Two clear weaknesses: code-block fixtures (writer needs an
  HTML-side pre-processor for the existing `<ac:structured-macro
  ac:name="code">` shape) and merged-cell tables (writer
  doesn't emit `rowspan` / `colspan`). Both have visible,
  bounded fixes.

### Pure-Python IR (note 013)

- 27 of 35 fixtures score 1.0 on every metric simultaneously.
- Wins every measurable fidelity metric: M1 = 0.9988, M2 = 0.9838,
  M5 = 0.9830, M3 = 1.0 (only candidate wired), M4 = 1.0 (ties
  docling).
- All eight non-perfect fixtures are sub-percent drifts traceable
  to bounded mechanical issues (trailing whitespace-only paragraphs,
  default `start="1"` on `<ol>`, etc. — full list in note 013).
- Identity and provenance both wired natively. The IR holds them
  on the typed nodes; the in-memory cache + `identity.reattach`
  grafts them through the markdown leg. Production translation is
  "swap the cache for an on-disk JSON sidecar."
- Zero external dependencies. ~94× faster per fixture than pandoc.
- Largest pipeline by LOC (2249) — the cost of owning a typed AST,
  JSON ser/de, four direction-specific readers/writers, and the
  reattach pass.

## Per-shape comparison

Selected shapes where the three pipelines diverge meaningfully.
M1 / M2 mean across fixtures tagged with that shape:

| shape | n | sq M1 | pl M1 | dl M1 | sq M2 | pl M2 | dl M2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `attachment-binary` | 1 | 0.13 | **1.00** | **1.00** | 0.50 | 0.50 | 0.50 |
| `callout-panel` | 1 | 0.86 | **1.00** | 0.98 | 0.00 | **0.83** | 0.75 |
| `callout-tip` | 1 | 0.97 | **0.99** | 0.98 | 0.40 | **0.60** | 0.40 |
| `callout-warning` | 1 | 0.99 | **1.00** | 0.99 | 0.33 | **0.67** | 0.33 |
| `code-block-no-language` | 1 | 0.91 | 0.91 | 0.74 | **1.00** | 0.50 | 0.00 |
| `code-block-special-chars` | 1 | 0.53 | 0.68 | **0.72** | **1.00** | 0.20 | 0.20 |
| `html-entities-in-prose` | 1 | 0.23 | **0.98** | 0.96 | 0.33 | 0.33 | 0.33 |
| `inline-link` | 7 | 0.98 | 0.97 | 0.96 | 0.63 | **0.91** | 0.47 |
| `inline-macro` | 1 | 0.11 | **1.00** | 0.98 | 0.33 | 0.33 | 0.33 |
| `link-external` | 2 | **1.00** | **1.00** | 0.93 | **1.00** | **1.00** | 0.00 |
| `link-inline-trailing-text` | 5 | 0.44 | **1.00** | 0.97 | 0.58 | 0.58 | 0.25 |
| `link-ri-attachment` | 1 | 0.72 | **1.00** | 0.92 | **0.67** | **0.67** | 0.00 |
| `link-ri-page-same-space` | 1 | 0.22 | **0.99** | 0.99 | 0.40 | 0.40 | 0.40 |
| `list-bullet` | 8 | 0.99 | 0.98 | **1.00** | 0.63 | **0.96** | 0.65 |
| `list-nested` | 1 | **1.00** | 0.98 | **1.00** | 0.43 | **1.00** | **1.00** |
| `list-ordered` | 5 | 0.97 | **0.99** | 0.98 | 0.45 | **0.96** | 0.70 |
| `macro-children` | 1 | 0.23 | **0.98** | 0.96 | 0.33 | 0.33 | 0.33 |
| `macro-status` | 1 | 0.11 | **1.00** | 0.98 | 0.33 | 0.33 | 0.33 |
| `macro-view-file` | 1 | 0.13 | **1.00** | **1.00** | 0.50 | 0.50 | 0.50 |
| `paragraph` | 6 | **0.98** | **0.98** | **0.99** | 0.87 | **0.97** | 0.20 |
| `table-merged-cells` | 1 | 0.82 | **1.00** | 0.70 | **0.55** | 0.29 | 0.48 |

Observations:

- **`ac:link/ri:*` family** (`link-ri-page-same-space`,
  `link-ri-attachment*`, `attachment-binary`,
  `link-inline-trailing-text`): pandoc cleans up status_quo's
  worst M1 fixtures dramatically (0.22 → 0.99, 0.44 → 1.00).
  None of the three pipelines fully preserves the macro identity
  in M2, so the link shape collapses to plain HTML — but the
  *content* is preserved. Both pandoc and docling reach the same
  M2 plateau here (0.40-0.67) because the missing block is
  symmetric across both pipelines.
- **Inline macros** (`macro-status`, `macro-children`,
  `inline-macro`): same story — pandoc fixes status_quo's
  worst M1 cases (0.11 → 1.00).
- **`html-entities-in-prose`**: pandoc 0.98 vs status_quo 0.23.
  Status_quo's HTML-entity handling drops content; pandoc
  handles it cleanly.
- **Lists**: pandoc dominates on M2 (lists are the *thing* it
  preserves best). Docling ties on `list-nested` because
  docling's list model is also strong.
- **Code blocks**: status_quo holds M2 for these (it knows the
  `ac:structured-macro ac:name="code"` shape exactly); pandoc
  needs an HTML-side pre-processor; docling collapses both
  structure and content.
- **Merged tables**: status_quo's M2 = 0.55 is best because it
  knows about merged cells. Pandoc M1 = 1.00 (content) but M2 =
  0.29 (writer doesn't yet emit `rowspan` / `colspan`).
- **Paragraphs / blockquote**: pandoc and status_quo tie on M1;
  docling's hard-wrap explosion crashes its M2 to ~0.20.

## Trade-offs

### Fidelity

Pandoc wins all three measurable metrics. The gap over status_quo
(M1 +0.11, M2 +0.08, M5 +0.14) compounds across the corpus: it
fixes the worst fixtures (those scoring below 0.5 in status_quo)
to near-perfect. The gap over docling on M2 (+0.36) is the
largest single delta in the comparison.

### Identity / provenance

Currently:

- status_quo: neither.
- docling: M4 = 1.00 via `self_ref`. No M3 (no Confluence-side
  identity preserved through docling's HTML reader).
- pandoc_lua: neither wired up yet.

If pandoc is the foundation, the question is *how cheap* it is to
add provenance / identity. Likely answer: cheap. The Lua writer
already has access to attributes on each AST node (`attr.id`,
`attr.class`, custom `data-*`). The HTML reader preserves
`data-*` attributes by default. A two-line writer change and a
two-line pre-processor on the input side would round-trip
`data-mdd-id` end-to-end. Identity (Confluence's `ac:macro-id`
and `ac:local-id`) plugs in the same way — emit them as
`data-mdd-confluence-id` on the way in, copy them through.

Sidecar JSON is the other option for cases where the inline
channel is awkward (e.g., for elements that pandoc drops
entirely). Either works.

### Latency

| pipeline | per-fixture | full corpus |
|---|---:|---:|
| status_quo | 0.7 ms | 23 ms |
| docling | 9 ms | 310 ms |
| pandoc_lua | 83 ms | 2895 ms |

The pandoc cost is dominated by subprocess startup. Mitigation:

- Pandoc 3 `--server` mode keeps a process resident, accepts
  requests over stdin/stdout. Implementable as a context manager
  in `pandoc_lua.py`. Expected drop: 83 ms → ~10 ms per fixture.
- For one-off operations (e.g., a single page export), the cost
  is already invisible — 100 ms is below user-perceptible
  latency.

For production, the server-mode wrapper is the right shape. The
spike's subprocess-per-call is acceptable for measurement and for
batched offline jobs.

### Code surface

| pipeline | LOC | character |
|---|---:|---|
| status_quo | 576 | all in-house |
| docling | 78 | adaptor only; library upstream |
| pandoc_lua | 202 | adaptor + writer; pandoc upstream |
| pure_python | 2249 | all in-house; zero upstream |

Docling has the smallest LOC but the biggest upstream surface
(docling library itself is hundreds of MB of model wiring even
when only the HTML/MD codepath is used). Pandoc sits between: a
single 7-MB binary that's stable, well-documented, and a known
quantity in our own toolchain already (Quarto uses it).
pure_python is the largest measured but the only one whose entire
surface is in this repo — no binary, no library, no licensing
constraint.

The 125 lines of Lua are the only part we *fully own* on the
pandoc side. They'd grow modestly to cover the open gaps (code-
macro pre-process: 5 lines of Python; merged-cell tables: ~30
lines of Lua; provenance: ~10 lines combined). After those,
total pandoc surface is ~250 LOC — but pure_python already covers
those gaps natively at the cost of carrying the full IR.

When LOC are read alongside the upstream dependency cost,
pure_python's 2249 lines are arguably *cheaper* than docling's
78 — there's no library to track, version, or migrate, and the
implementation per shape lives next to the corpus shape tag that
exercises it. Same shape-by-shape extensibility argument as Lua.

### Maintainability

- status_quo: well-trodden, but every new Confluence shape
  requires touching both `storage_to_md.py` and `md_to_storage.py`
  in lockstep. Inline-vs-block decisions are hard-coded.
- docling: minimal adaptor, but extending coverage means either
  reaching upstream or maintaining a fork. Adding Confluence
  semantics on top would require parsing twice (pandoc-style
  pre/post-process around docling's parse).
- pandoc_lua: each new Confluence shape costs one Lua function
  (writer side) and one regex pre-processor (reader side if
  pandoc doesn't recognise the input shape). Per-shape costs are
  bounded and visible.

The writer code is also the closest fit to how the test corpus is
*organised* — each `test_corpus.shapes` tag corresponds to a Lua
function. Extending coverage is "look at the failing shape, add
its function." This shape-by-shape extensibility is what makes
the harness's per-shape aggregation directly actionable.

## Recommendation (revised)

**Promote pure-Python IR (note 013) to a real spec** as the IR
foundation for the bidirectional Confluence sync redesign. Sketch
of the spec's first slice:

1. **Move the package into `src/`.** Relocate
   `scripts/ir_experiment/pipelines/pure_python/` to
   `src/mdd/confluence/ir/` and expose its public API (`parse`,
   `render`, `Document`, `to_json` / `from_json`, `reattach`).
2. **Wire behind a feature flag** in `mdd confluence export`:
   `--ir pure-python` next to the existing status_quo default.
3. **Implement the five-fix list** from note 013 (trailing empty
   paragraphs, default `start="1"` preservation, ConfluenceMacro
   attrs passthrough, ConfluenceLink standalone hint, HTML-entity
   form preservation). ~50 LOC for a clean 1.0 sweep.
4. **Sidecar wiring.** Swap the in-memory IR cache for an on-disk
   `<page>.confluence.json` next to the markdown file. Same
   `identity.reattach` API; different source for the cached IR.
5. **Run the harness in CI** on the corpus as a regression gate.
   Threshold proposal (tighter than the original): M1 ≥ 0.995
   aggregate, M2 ≥ 0.97 aggregate, M3 = 1.0, M4 = 1.0, no
   fixture scores below 0.95 on any metric.

### Sketch from the superseded pandoc + Lua recommendation

Preserved here because the per-shape pre/post-processor pattern
remains relevant: even with pure_python carrying the IR, the
mapping between Confluence storage shapes and clean markdown
surfaces (e.g. `<ac:link><ri:page>` ↔ `[body](confluence-page:...)`)
is the same problem the pandoc plan called out, just expressed in
Python rather than Lua. Worth re-reading the pandoc plan's per-
shape list as a checklist for pure_python's writer coverage.

What docling brings that pandoc doesn't: a per-block `self_ref`
that's already there for free, no writer code needed. If the
pandoc identity story turns out to be awkward in practice, the
fallback is "use docling's `self_ref` as a provenance side-channel,
attach pandoc's output to it via document-position pairing." Not
recommended as the primary plan but worth keeping in mind.

What status_quo brings that the other two don't: a known
production-grade understanding of merged-cell tables and
code-block macros. Worth porting those specific behaviours into
the new Lua writer rather than rebuilding them from scratch.

## What we won't do

- Wait for "more data". The 35-fixture corpus already
  distinguishes the three pipelines clearly; bigger corpus only
  helps once the recommendation is chosen and we want to harden
  it.
- Adopt docling as the IR foundation. The structural-fidelity gap
  (0.41 vs pandoc's 0.77) is too large for a foundation and the
  fixes are upstream-shaped, not in our control.
- Adopt status_quo + provenance as a separate spike. The fidelity
  gap to pandoc on the worst shapes (M1 0.11 → 1.00, M2 0.40 →
  0.96 on lists) makes "keep status_quo, add provenance" a worse
  starting point than "switch to pandoc, add provenance."
- Replace pandoc all-at-once. The migration shape is most likely:
  introduce pandoc behind a feature flag for new pages, A/B
  against status_quo on existing ones, swap the default after
  the per-shape thresholds hold for a week of real usage.

## Open questions deferred to the spec

1. ~~**Pandoc vendoring vs PATH**~~ — moot under the revised
   recommendation. No pandoc binary in production.
2. **Sidecar provenance vs inline attributes.** Resolved by note
   013: the IR carries provenance internally, the on-disk sidecar
   format is JSON (the IR's own serialisation). Spec note should
   pick the file naming convention (`<page>.confluence.json` next
   to the markdown file vs a dedicated state dir).
3. **CI threshold values.** Revised upward given pure_python's
   headline numbers: M1 ≥ 0.995 aggregate, M2 ≥ 0.97 aggregate,
   M3 = 1.0, M4 = 1.0, no fixture below 0.95 on any metric.
   Tighten after corpus growth.
4. **Merge / 3-way / conflict handling.** Out of scope for the
   IR foundation; covered in a downstream spec once the IR
   reliably preserves provenance. The IR's JSON form makes
   tree-diff-and-merge tractable.
5. **`--live` mode.** Currently deferred. Spec should plan it as
   a quarterly integration test, not per-PR.

## Sequencing (revised)

Suggested order of work:

1. **Spec note** (`028-confluence-bidirectional-sync.md` or
   similar) drafted from the revised recommendation. Owner picks;
   spec has the same scope as this comparison plus the merge
   story.
2. **Move `pipelines/pure_python/` into `src/mdd/confluence/ir/`**
   as the new production converter, under a feature flag in
   `mdd confluence export` (`--ir pure-python`). Status_quo
   stays the default during A/B.
3. **Implement the 5-fix list** from note 013 for the clean 1.0
   sweep. ~50 LOC.
4. **Sidecar wiring.** Swap the in-memory cache for an on-disk
   `<page>.confluence.json`.
5. **Harness in CI.** `mise run ir-experiment --pipeline
   pure_python --threshold 0.995,0.97,1.0,1.0,0.95` becomes a
   gate.
6. **Flip the default** once thresholds hold for a few real
   pages over a few weeks.

Estimate: 1-2 weeks of focused work from spec to default flip,
not counting the merge / 3-way work that follows. The estimate
is lower than the pandoc plan's 2-3 weeks because the identity /
provenance follow-ups are already done.

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space (the three candidates this note compares).
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- [Research note 008](R08-confluence-ir-experiment-harness.md) —
  experiment harness.
- [Research note 009](R09-confluence-ir-spike-status-quo.md) —
  status-quo baseline.
- [Research note 010](R10-confluence-ir-spike-pandoc-lua.md) —
  pandoc + Lua spike.
- [Research note 011](R11-confluence-ir-spike-docling.md) —
  docling spike.
- [Research note 013](R13-confluence-ir-spike-pure-python.md) —
  pure-Python IR spike (the revised recommendation).
- `scripts/ir_experiment/` — the
  harness and pipelines used in this comparison.
- HTML reports: the harness also emitted side-by-side HTML diff
  reports per spike. They are not carried in this repository — the
  numbers reproduced in these notes are the durable record.

## Next research note

None planned in this thread. The next document is a real spec —
`docs/spec/S28-*.md` — that promotes the recommendation here into
a concrete implementation plan.
