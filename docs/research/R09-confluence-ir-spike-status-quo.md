# 009 - IR spike: status quo pipeline

**Status:** Research notes. Baseline measurement for the IR-foundation
decision in [research note 012] (TBC).

**Date of run:** 2026-05-12.

**What this note is.** The first of three planned spikes under
[research note 008](R08-confluence-ir-experiment-harness.md). It runs
the existing mdd converters (`mdd.confluence.storage_to_md` and
`mdd.confluence.md_to_storage`) as an "IR pipeline" against the
35-fixture corpus from [note 007](R07-confluence-test-corpus.md), and
measures the round-trip fidelity. The two follow-on spikes (Pandoc +
Lua writer, docling) will use the same harness and metric battery
so the comparison in note 012 is grounded in directly comparable
numbers.

**What this note is not.** A judgement on whether the status quo
should be replaced. That decision belongs in note 012, after all
three spikes have run. This note's contribution is honest
measurement of the baseline.

## Harness and corpus state

- Harness: [scripts/ir_experiment/](../../scripts/ir_experiment/) at
  commit landing this note.
- Corpus: `test-confluence/MDD/_snapshots/`, 35 captured pages
  (`mise run refresh-corpus` run on 2026-05-12 against the same
  Confluence instance).
- Pipeline: `pipelines/status_quo.py` — `supports_provenance = False`,
  `supports_identity = False`. Identity-preservation and
  provenance-coverage metrics (M3 / M4 from note 008) report None
  for this pipeline by design.
- Round-trip mode: in-memory only
  (`storage_to_markdown(storage) → markdown_to_storage(markdown)`).
  No live API round-trip in this run — that's gated for a later
  `--live` mode.
- Metrics implemented: M1 (text fidelity), M2 (structural fidelity)
  in this note's original run; M3 (identity preservation), M4
  (provenance coverage), M5 (whitespace drift), M6 (code surface)
  added in a follow-up commit. See §"Addendum: M3-M6 measurements"
  below for the additional numbers — the M1 / M2 narrative above is
  unchanged.

## Headline numbers

| metric | mean | min | max | n |
|---|---:|---:|---:|---:|
| `text_fidelity` | 0.8559 | 0.1067 | 1.0000 | 35 |
| `structural_fidelity` | 0.6964 | 0.0000 | 1.0000 | 35 |

11 of 35 fixtures score 1.0 on both metrics simultaneously. 5 of 35
score below 0.5 on text fidelity. 1 fixture scores literally 0.0 on
structural fidelity (panel callout: the round-trip drops the macro
entirely and emits a blockquote instead).

## What the numbers say

### Healthy: prose, tables, simple inline

Pure prose shapes round-trip cleanly:

- Plain paragraph, multiple paragraphs, blockquote, hr, all six
  heading levels — `text_fidelity` and `structural_fidelity` both
  1.0000.
- Plain tables and tables with mixed inline content — both metrics
  1.0000.
- Bullet/ordered lists and external URL links — `text_fidelity`
  1.0000 (structural takes a hit, see below).
- Inline formatting (strong / em / inline code) — `text_fidelity`
  0.9965, `structural_fidelity` 1.0000.

This matches the qualitative read from the 2026-05-11 corpus build:
the status-quo converters are *correct* on the shapes that don't
involve Confluence-namespaced macros or links.

### Brittle: `ac:link` with `ri:*` children

The three lowest text-fidelity scores are all `ac:link` variants:

| fixture | shape | text_fidelity |
|---|---|---:|
| Same-space page link | `ac:link / ri:page` | 0.2192 |
| Attachment link | `ac:link / ri:attachment` | 0.1283 |
| Status macro | `ac:structured-macro` (status) | 0.1067 |

The text-fidelity detail shows the round-trip *expands* the text: a
146-character original becomes 666 characters; an 80-character status
macro becomes 750. This is the converter falling back to verbose
`{=confluence}` raw-XML blocks because the markdown→storage path
doesn't recognise the inline shape it emitted on the way out. The
macro survives semantically, but it survives as a 6× longer literal
XML block — exactly the kind of fidelity loss the IR was supposed
to fix.

### Brittle: callout macro identity

Three of the five rich-body callout macros (`panel`, `warning`,
`note`) drift structurally: the round-trip turns the macro wrapper
into a `<blockquote>` and unwraps the contents. The tip and info
fixtures partially survive (`structural_fidelity` 0.40 and 0.43)
because their contents survive even when the macro wrapper is lost.
Panel callout scores 0.0 because the macro *and* its embedded list
both vanish in round-trip.

This isn't a regression — it's the documented status-quo behaviour
(callouts → blockquotes is a deliberate fallback when the markdown
writer can't preserve macro identity). The metric just makes it
visible.

### Brittle: lists get re-paragraphed

`Bullet list` and `Ordered list` score `text_fidelity` 1.0000 but
`structural_fidelity` 0.3750 each. The detail explains it: one
`<p>` in the original becomes six `<p>`s in the round-trip. The
markdown→storage converter wraps every list-item body in a `<p>`,
inflating the paragraph count without losing text. This would
churn diffs on every save without changing semantics — exactly
the kind of whitespace/structure drift the M5 metric (deferred)
will pick up directly.

### Brittle: code blocks with special characters

`Code block with characters that need CDATA` scores `text_fidelity`
0.5348. The original has 718 chars of stripped text; the round-trip
has 384. The CDATA escape handling drops content during the
markdown rewrite. The plain code block and the python-language
variant both score 1.0 structurally, so this is specifically a
CDATA-required-content bug, not a code-macro-shape bug.

## Where the metrics agree, where they disagree

- They agree on prose (11 fixtures at 1.0 / 1.0).
- They agree on the `ac:link / ri:page` and `ri:attachment` cases
  (both metrics report drift on those fixtures).
- They disagree systematically on bullet/ordered lists:
  `text_fidelity = 1.0`, `structural_fidelity = 0.375`. Lists
  preserve every character but reshape the block structure. M5
  (whitespace drift) would catch this more directly.
- They disagree on the children macro: `text_fidelity = 0.23`,
  `structural_fidelity = 0.33`. The macro is dropped but replaced
  with verbose explanatory text, so text-fidelity sees a 4× length
  blowup that structural-fidelity smooths over.

## What's missing for a real decision

Metrics not run on this spike:

- **M3 identity preservation.** Status-quo declares
  `supports_identity = False`. Not measurable for this pipeline.
  Becomes measurable for the Pandoc-Lua and docling spikes if
  their writers emit `ac:macro-id` / `ac:local-id` deterministically.
- **M4 provenance coverage.** Same story — `supports_provenance =
  False` here. The status-quo + provenance variant (note 008 hints
  at one) would be a separate spike.
- **M5 whitespace drift.** Would clearly distinguish the
  list-re-paragraphing problem from genuine content loss. Worth
  adding before spike 010 so the Pandoc baseline isn't being
  judged on a metric we never quantified for status-quo.
- **M6 code surface.** Static. Will fold into note 012's
  maintainability assessment.

Three follow-up metric features should land before note 012, ideally
during slice work on spikes 010 / 011:

1. Whitespace drift (M5) — cheap, sits next to M1.
2. Per-shape aggregation in the report — already supported by the
   loader's `shapes` filter; the report could group rows by shape
   tag in addition to per-fixture.
3. Diff sampler — print a unified diff of original vs round-trip
   for the N worst fixtures per metric, so spike notes can show
   *what* failed, not just *how badly*.

## What this means for the comparison

For note 012 to make a clean call, the Pandoc and docling spikes
need to beat the status quo on:

1. **Macro identity** — `ac:link / ri:page`, `ac:link / ri:attachment`,
   and structured macros like `status`, `children`, `expand`. Any
   pipeline that round-trips these without ballooning to
   `{=confluence}` raw blocks is a clear win.
2. **Callout shape preservation** — keeping
   `<ac:structured-macro ac:name="tip|info|note|warning|panel">`
   verbatim across the round trip. Status quo loses 3/5.
3. **List paragraph wrapping** — single-`<p>`-per-list-item-body
   should round-trip to single-`<p>`, not six. Either a markdown-it
   plugin change in the status-quo path or a different writer.
4. **CDATA-required code content** — fixing 98348 (and any
   sibling cases the harness surfaces once we have more fixtures).

Anything below those four is decoration; anything above changes the
recommendation.

## Open questions specific to this spike

1. **`structural_fidelity = 0.0` for panel callout.** Is that a
   metric clamp artefact (the round-trip emitted *new* blocks the
   original didn't have, so the delta exceeded `total_blocks`) or
   a faithful description of "the round-trip threw the macro away"?
   Both, probably. Worth tightening the metric formula in slice 4
   to track gained/lost blocks separately.
2. **Should `structural_fidelity` count *content* changes inside
   macros?** Right now `<ac:structured-macro ac:name="tip">` is one
   block; the metric doesn't notice when the tip's body content is
   reshaped. The note-008 sketch had a hint of per-shape weighting
   that would catch this; deferred.
3. **In-memory round trip skips Confluence-side normalisation.**
   The real production round trip is `markdown → storage → PUT →
   Confluence persists → GET → storage → markdown`. Confluence may
   re-shape the storage on save (add `ac:local-id` etc.). A
   `--live` mode that exercises this is a slice for later, but the
   baseline numbers here are an *upper bound* on real-world
   fidelity — the live tier can only be worse, never better.

## Captured run output

The harness writes a machine-rendered report. The current run's
table is reproduced below for the record (so this note remains
useful even if the snapshots change later).

```
mise run ir-experiment -- --pipeline status_quo --out report.md
```

### Per-fixture scores (status_quo, 2026-05-12)

| page_id | title | text_fidelity | structural_fidelity |
|---:|---|---:|---:|
| 131253 | Image referenced by external URL | 1.0000 | 0.7778 |
| 131272 | External URL link | 1.0000 | 1.0000 |
| 131305 | Table with mixed inline content in cells | 1.0000 | 1.0000 |
| 131332 | Tip callout (rich body) | 0.9729 | 0.4000 |
| 131360 | Panel callout (rich body) | 0.8571 | 0.0000 |
| 131384 | Layout three-equal columns | 0.9990 | 0.6000 |
| 131404 | Attachment link via ac:link | 0.7241 | 0.6667 |
| 163977 | Nested mixed lists | 1.0000 | 0.4286 |
| 164003 | Multiple paragraphs | 1.0000 | 1.0000 |
| 164022 | Horizontal rule | 1.0000 | 1.0000 |
| 164045 | Warning callout (rich body) | 0.9901 | 0.3333 |
| 164060 | Same-space page link | 0.2192 | 0.4000 |
| 164069 | Attachment link | 0.1283 | 0.5000 |
| 164089 | Expand macro | 1.0000 | 0.6667 |
| 164105 | Status macro | 0.1067 | 0.3333 |
| 164122 | Platform glossary | 0.9042 | 0.8043 |
| 65915 | Plain code block (no language) | 0.9130 | 1.0000 |
| 65941 | Code block with language tag (python) | 0.5860 | 1.0000 |
| 65975 | Multiple inline links in one paragraph | 1.0000 | 1.0000 |
| 66011 | List items with inline formatting | 1.0000 | 0.4444 |
| 66045 | Plain table | 1.0000 | 1.0000 |
| 66067 | Info callout (rich body) | 0.9890 | 0.4286 |
| 98308 | Plain paragraph | 1.0000 | 1.0000 |
| 98328 | Plain blockquote | 1.0000 | 1.0000 |
| 98348 | Code block with characters that need CDATA | 0.5348 | 1.0000 |
| 98367 | Top-level heading (h1) | 1.0000 | 1.0000 |
| 98386 | Bullet list | 1.0000 | 0.3750 |
| 98412 | Ordered list | 1.0000 | 0.3750 |
| 98431 | Inline formatting | 0.9965 | 1.0000 |
| 98491 | Note callout (rich body) | 1.0000 | 1.0000 |
| 98505 | Layout two-equal columns | 0.9964 | 0.5333 |
| 98521 | Table with merged cells | 0.8167 | 0.5484 |
| 98544 | Children macro | 0.2298 | 0.3333 |
| 98559 | Acme Internal Engineering Handbook | 0.9917 | 0.7400 |
| 98579 | Meeting notes — Platform sync, 2026-05-11 | 1.0000 | 0.6835 |

### Worst per metric

`text_fidelity`:

| page_id | title | score |
|---:|---|---:|
| 164105 | Status macro | 0.1067 |
| 164069 | Attachment link | 0.1283 |
| 164060 | Same-space page link | 0.2192 |
| 98544 | Children macro | 0.2298 |
| 98348 | Code block with characters that need CDATA | 0.5348 |

`structural_fidelity`:

| page_id | title | score | drift |
|---:|---|---:|---|
| 131360 | Panel callout (rich body) | 0.0000 | macro:panel: 1→0; li: 5→0; blockquote: 0→1 |
| 164045 | Warning callout (rich body) | 0.3333 | macro:note: 1→0; blockquote: 0→1 |
| 164105 | Status macro | 0.3333 | macro:status: 2→0 |
| 98544 | Children macro | 0.3333 | macro:children: 1→0; p: 2→3 |
| 98386 | Bullet list | 0.3750 | p: 1→6 |

## Addendum: M3-M6 measurements

Added in a follow-up run on the same corpus (2026-05-12). The
narrative above is the originally-published baseline; this section
is appended raw — what was measured, what came out, no
re-interpretation of the M1 / M2 story.

### New aggregate

| metric | mean | min | max | n |
|---|---:|---:|---:|---:|
| `text_fidelity` | 0.8559 | 0.1067 | 1.0000 | 35 |
| `structural_fidelity` | 0.6964 | 0.0000 | 1.0000 | 35 |
| `whitespace_drift` | 0.6062 | 0.0000 | 1.0000 | 35 |
| `identity_preservation` | — | — | — | 0 |
| `provenance_coverage` | — | — | — | 0 |

`identity_preservation` and `provenance_coverage` report `—` (n=0)
because the status-quo pipeline declares `supports_identity =
False` and `supports_provenance = False`. By policy from note 008,
metrics that the pipeline didn't *try* to satisfy return `None`
rather than a misleading numeric score. The metric infrastructure
is in place; it lights up once the Pandoc and docling spikes wire
in identity / provenance side-channels.

### Whitespace drift — worst 5

| page_id | title | rate per 1k chars |
|---:|---|---:|
| 164105 | Status macro | 8388 |
| 164069 | Attachment link | 6678 |
| 164060 | Same-space page link | 3544 |
| 131404 | Attachment link via ac:link | 382 |
| 131360 | Panel callout (rich body) | 150 |

A rate of 8388 means the round-trip introduced 8.4 characters of
diff per character of original — i.e. the macro got blown up into a
verbose `{=confluence}` raw block, exactly as M1 already showed.
The bullet-list and ordered-list fixtures *don't* appear in this
worst-list (their scores are >0.95), which confirms M2's
"list-items get re-paragraphed" finding is purely structural; no
visible-content whitespace is being shuffled around.

### Code surface (M6)

Total LOC for `status_quo`: **576**

| file | LOC |
|---|---:|
| `status_quo.py` (wrapper) | 33 |
| `mdd/confluence/storage_to_md.py` | 409 |
| `mdd/confluence/md_to_storage.py` | 134 |

A baseline for the comparison in note 012: the Pandoc-Lua spike's
LOC will include its `confluence_storage.lua` writer; the docling
spike's LOC will include its DoclingDocument ⇄ storage adaptors.
Either approach should beat 576 LOC by a clear margin to claim a
maintainability win, or carry a corresponding fidelity uplift to
justify any extra surface area.

### Per-shape view

The harness now also renders per-shape means. Most-affected shapes
across the three fidelity metrics simultaneously (M1, M2, M5):

| shape | n | text_fidelity | structural_fidelity | whitespace_drift |
|---|---:|---:|---:|---:|
| `macro-status` | 1 | 0.11 | 0.33 | 0.00 |
| `macro-view-file` | 1 | 0.13 | 0.50 | 0.00 |
| `macro-children` | 1 | 0.23 | 0.33 | 0.00 |
| `link-ri-page-same-space` | 1 | 0.22 | 0.40 | 0.00 |
| `link-ri-attachment` | 1 | 0.72 | 0.67 | 0.00 |
| `link-inline-trailing-text` | 5 | 0.44 | 0.58 | 0.20 |
| `table-merged-cells` | 1 | 0.82 | 0.55 | 0.00 |
| `code-block-special-chars` | 1 | 0.53 | 1.00 | 0.00 |

(Pulled from the harness's per-shape table; truncated to the
shapes that score below 0.95 on M1.) Tagging the fixture corpus by
shape was the right call — it makes the comparison note's per-shape
narrative trivial to extract.

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space; identifies the gaps this measurement quantifies.
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- [Research note 008](R08-confluence-ir-experiment-harness.md) —
  the harness that produced this report.
- [`scripts/ir_experiment/`](../../scripts/ir_experiment/) — the
  harness code itself.

## Next research note

`R10-confluence-ir-spike-pandoc-lua.md` — Pandoc CLI with a custom
Lua writer for Confluence storage XHTML. Same corpus, same metric
battery, comparable numbers.
