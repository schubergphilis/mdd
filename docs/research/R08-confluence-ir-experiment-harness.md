# 008 - Experiment harness for Confluence IR comparison

**Status:** Research notes. Not an implementation spec. **Fully
implemented** — harness skeleton, full metric battery (M1–M6),
per-shape aggregation, side-by-side HTML diff sampler, wall-clock
timing per direction, all three spikes (note 009 status_quo,
note 010 pandoc+Lua, note 011 docling), and the comparison
recommendation (note 012) landed across five sessions on
2026-05-12. The next step is a real spec promoting the
recommendation; see [note 012](R12-confluence-ir-comparison.md).

**Problem brief.** [Research note 006](R06-confluence-bidirectional-sync-ir.md)
defines three candidate IR foundations (status quo + provenance, Pandoc
via Lua writer, docling) and proposes deciding between them
empirically. [Research note 007](R07-confluence-test-corpus.md)
specifies the test corpus (now built at
`mdd/test-confluence/MDD` — 26 live pages on
`markdown.atlassian.net/MDD`, 23 focused fixtures + 3 synthetic
long-form pages). This note specifies the **experiment harness** that
consumes the corpus and produces comparison reports for the three
candidate pipelines.

The harness is a small Python tool, intentionally outside the
production mdd codebase (lives under `scripts/ir_experiment/` — the
underscored name keeps it importable as a Python module). Its
output is a set of numbered research notes (009 = status quo spike,
010 = Pandoc spike, 011 = docling spike, 012 = comparison) with
measurements, sample diffs, and an honest assessment of fit per
candidate. Note 012 distils findings into the recommendation that
becomes a real spec.

## What the 2026-05-11 run already proved

Before writing automated metric code, it's worth naming what the
manual round-trip work on the corpus has *already* told us:

- The current pipeline (storage_to_md / md_to_storage with no IR)
  **works end-to-end on a real Confluence Cloud instance** for the
  shapes in our corpus, after fixes #70 / #71 / #72 / #73 / #74.
- It has identifiable fidelity gaps in known places: lossy
  merged-cell tables, no provenance, no element identity tracking,
  inline-vs-block decisions for `ac:link` and `ac:structured-macro`
  hard-coded per element type rather than derived from a model.
- The corpus itself surfaced five distinct bugs in two days. That's
  evidence the corpus is well-shaped; the harness's job is to make
  this kind of surfacing repeatable, scaleable, and automatic
  rather than dependent on a human eyeballing exports.

So note 008's contribution isn't "find out if the status quo
pipeline works" — it does, more or less. It's "measure how *well*
each candidate pipeline does, on a common battery, so the
comparison in note 012 is grounded in numbers, not vibes."

## Goals

1. **Reproducible.** Running `mise run ir-experiment` against the
   committed corpus produces deterministic output. Any deviation
   between runs traces to a real change in pipeline behaviour or
   in the snapshots (and the snapshot path is gated by an explicit
   refresh command, per note 007).
2. **Pluggable.** All three candidate pipelines implement the same
   small interface; the harness doesn't know which is which. New
   pipelines can be added later without touching the harness core.
3. **Measurable.** Each metric produces a number per fixture and an
   aggregate across the corpus. Side-by-side comparison reports
   are the natural output.
4. **Bounded scope.** This is research tooling, not production
   code. Pyright-strict, ruff-clean, and ≥70% tests are not the
   bar; "useful enough to ground the decision" is.

## Non-goals

- A general-purpose corpus runner. The harness is specific to the
  Confluence storage XHTML ↔ markdown question.
- Performance benchmarking. We measure pipeline correctness, not
  speed. Note 006's perf caveat (pandoc subprocess startup ~50ms)
  is real but not blocking until the corpus is much bigger.
  *Update 2026-05-12*: wall-clock timing per direction is now
  recorded and surfaced in the report — not as a benchmark
  (single-threaded, no warmup, cold caches) but to flag
  order-of-magnitude differences between candidates. The
  full-corpus round trip stays sub-second on every pipeline tried
  so far.
- Bidirectional sync semantics. The harness measures conversion
  fidelity per direction; merge / 3-way / conflict handling is a
  separate (later) concern.

## Architecture

```
+-------------------+    +-------------------+    +----------------------+
| Corpus snapshots  |    |  Pipeline impl    |    |  Metric calculators  |
| (storage.xhtml,   |--->|  storage_to_md()  |--->|  text fidelity       |
|  export_view.html,|    |  md_to_storage()  |    |  structural fidelity |
|  metadata.json)   |    |                   |    |  identity preservation|
+-------------------+    +-------------------+    |  provenance feas.    |
                                                  |  whitespace drift    |
                                                  +----------------------+
                                                              |
                                                              v
                                                  +----------------------+
                                                  |  Comparison report   |
                                                  |  (markdown tables    |
                                                  |   per fixture +      |
                                                  |   aggregate)         |
                                                  +----------------------+
```

The harness has four parts:

1. **Corpus loader** (`harness/corpus.py`).  Walks
   `mdd/test-confluence/MDD/_snapshots/<page_id>/` and, alongside,
   reads the fixture markdown files for the `test_corpus.shapes`
   tags. Produces `Fixture` records: `(page_id, title, shapes,
   storage_xhtml, export_view_html, expected_markdown,
   metadata)`. Optionally re-fetches from live for
   integration-tier runs.

2. **Pipeline protocol** (`harness/pipeline.py`).  A small Python
   protocol that each spike implements:

   ```python
   class Pipeline(Protocol):
       name: str

       def storage_to_markdown(
           self, storage_xhtml: str, *, page_title: str | None = None
       ) -> StorageToMdResult: ...

       def markdown_to_storage(
           self, markdown_body: str
       ) -> MdToStorageResult: ...

       @property
       def supports_provenance(self) -> bool: ...
       @property
       def supports_identity(self) -> bool: ...
   ```

   `StorageToMdResult` carries the markdown body plus optional
   provenance/identity side-channels.  `MdToStorageResult` carries
   the storage XHTML plus optional identity emissions.  The
   protocol is deliberately narrow so the three spikes are
   independent.

3. **Metric calculators** (`harness/metrics/`).  Pure functions
   that take a `Fixture` and a pipeline's results and return a
   `MetricResult`. Each metric is its own module so spikes can
   skip metrics that don't apply (e.g. a pipeline with no
   provenance support reports `None` for the provenance metric,
   not a failure).

4. **Comparison reporter** (`harness/report.py`).  Aggregates
   `MetricResult` rows into a markdown report. One report per
   spike (research notes 009-011), one cross-pipeline comparison
   (note 012).

The CLI entry point (`harness/__main__.py` invoked via
`mise run ir-experiment`) takes flags like `--pipeline pandoc`,
`--shapes link-ri-page`, `--live` (use live fetch instead of
snapshots), `--out docs/research/R09-confluence-ir-spike-status-quo.md`.

## Metric definitions (initial sketch)

Each metric returns a numeric score in `[0, 1]` plus a structured
"detail" record so the report can show *what* differed, not just
the score.

### M1 - Text fidelity

Strip all markup from both sides; compare normalised text streams.

```
text_fidelity(fixture, result) =
    1 - levenshtein(
        normalise(strip_markup(fixture.storage_xhtml)),
        normalise(strip_markup(result.round_trip_storage))
    ) / max(len(...), 1)
```

Where `normalise` collapses whitespace runs and Unicode-normalises
to NFC. The Levenshtein distance approximates "how many character
edits would it take to recover the original."

Score interpretation: 1.0 = identical text; >0.99 = minor
whitespace drift; >0.95 = acceptable for most uses; <0.95 = real
loss.

**Already-known gotcha**: bug #73 (HTML entities dropped) would
score this near 1.0 on most fixtures but fail catastrophically on
prose with apostrophes — a curly `’` becomes nothing, which is
one character difference per occurrence. Aggregate fidelity stays
high; the corpus needs a fixture (we have it:
`niche-macros/children.md`) that the score *will* flag.

### M2 - Structural fidelity

Count occurrences of each block type in storage XHTML and in the
markdown output. Compare counts.

```
structural_fidelity(fixture, result) =
    1 - sum(|count_storage[T] - count_md[T]|) / total_blocks
```

Where T ranges over {heading-1..6, paragraph, list-bullet,
list-ordered, list-item, table, table-row, code-block, blockquote,
horizontal-rule, ac-structured-macro-by-name, ac-link, ac-image,
ac-layout-section}.

The exact mapping markdown → storage isn't 1:1 for every type;
e.g. markdown `> ` becomes `<blockquote>` *or* a callout macro
depending on context. The metric tolerates this via per-fixture
"expected mappings" pulled from the fixture's
`test_corpus.shapes` tags.

### M3 - Identity preservation

Extract `ac:macro-id` and `ac:local-id` from `fixture.storage_xhtml`,
extract the same from `result.round_trip_storage`, compute set
intersection over union.

```
identity_preservation(fixture, result) =
    |orig_ids ∩ round_trip_ids| / |orig_ids ∪ round_trip_ids|
```

Score 1.0 means every macro / local id round-tripped. Score <1.0
means some macros got renumbered or dropped — which would break
merge semantics in production.

**Only meaningful when the pipeline declares
`supports_identity = True`.** Status-quo pipeline returns None
here (no identity tracking); Pandoc pipeline scores it if the
Lua writer carries IDs through; docling pipeline scores it via
`self_ref`.

### M4 - Provenance feasibility

For each top-level block in `result.round_trip_markdown`, does the
pipeline emit a mapping back to a specific storage element?

```
provenance_coverage(fixture, result) =
    |md_blocks_with_provenance| / |md_blocks_total|
```

Score 1.0 means every markdown block can be traced back to its
storage origin. Lower scores indicate gaps that would force the
merge engine to fall back to heuristics for those blocks.

**Only meaningful when the pipeline declares
`supports_provenance = True`.**

### M5 - Whitespace drift

Same as text fidelity but without normalising whitespace. Picks
up gratuitous reformatting that doesn't change semantics but does
churn diffs in the local mirror.

```
whitespace_drift(fixture, result) =
    levenshtein(
        strip_markup(fixture.storage_xhtml),
        strip_markup(result.round_trip_storage)
    ) / 1000   # report as drift-per-1000-chars
```

Reported as a rate, not a score. Lower is better. Useful for
spotting "the pipeline works but spits out wildly different
whitespace each time."

### M6 - Code surface

Static, not per-fixture.  Lines of code in the pipeline
implementation (excluding test files, excluding upstream library
code).  Reported per spike as a single number so the comparison
note can weigh maintainability honestly.

## Snapshot strategy (concretised from note 007)

Note 007 deferred the "how do tests find snapshots" question to
note 008. Proposal:

### Snapshot directory layout

```
mdd/test-confluence/MDD/_snapshots/
├── <page_id>/
│   ├── storage.xhtml          # body-format=storage, verbatim
│   ├── export_view.html       # body-format=export_view, verbatim
│   └── metadata.json          # title, version, parent_id, space_id,
│                              # timestamps, attachments manifest
└── ...
```

One subdirectory per fixture page. The page ID is the stable
handle (matches `confluence.page_id` in the fixture frontmatter).

### Refresh task

```bash
mise run refresh-corpus
```

The task (definition in `mise.toml`):

1. Walks `mdd/test-confluence/MDD/fixtures/**/*.md` and
   `corpus/**/*.md`. For each, reads
   `frontmatter.confluence.page_id`.
2. Fetches `body-format=storage`, `body-format=export_view`, and
   the page metadata for each ID.
3. Writes the three files into
   `_snapshots/<page_id>/`.
4. Reports a `git diff --stat` summary so the user can see what
   changed.

Refresh is **manual, not automatic**. CI never refreshes.  When
the integration tier (below) detects drift, the failure is loud
and the human decides whether to refresh or whether the drift is
a real Confluence-side change worth investigating.

### Snapshot tier (default unit tests)

The harness loads from `_snapshots/<page_id>/` by default. No
network. Deterministic. Used by `tests/confluence/test_corpus_*.py`
(to be written) which run as part of `mise run test`.

### Live tier (integration)

When run with `--live` or under `mise run test-integration`, the
harness re-fetches each page from `markdown.atlassian.net` and
diffs against the snapshot. Drift triggers a clear failure with
both versions printed; the operator decides whether to `mise run
refresh-corpus` (legitimate Confluence-side change) or investigate
(API regression or mdd-side bug).

The integration tier requires `op` access to the test-tenant
token; CI for this tier is **not** set up yet (note 006 open
question).

## How the three spikes plug in

Each spike (notes 009, 010, 011) implements `Pipeline` and lives
under `scripts/ir_experiment/pipelines/`:

- `pipelines/status_quo.py` — wraps the existing
  `mdd.confluence.storage_to_md` and `mdd.confluence.md_to_storage`
  modules.  `supports_provenance = False`,
  `supports_identity = False`.  Establishes the baseline; note 009
  is its report.
- `pipelines/pandoc_lua.py` — invokes Pandoc CLI with the
  custom Lua writer (`pipelines/confluence_storage.lua`).
  Provenance via element IDs emitted as `data-mdd-id` attributes
  (open question: see #73's prep work on entity handling —
  similar pre-processing may be needed for the pandoc input
  side).  Identity via the same channel.  Note 010 is its report.
- `pipelines/docling.py` — uses `DoclingDocument` directly,
  in-process.  Provenance via `self_ref`.  Identity via `prov`
  fields (open question: do they actually round-trip when used
  for logical rather than layout-derived provenance?).  Note 011
  is its report.

Each spike runs the same metric battery against the same corpus.
Comparison note 012 aggregates the three reports into a table per
metric and per fixture-category, then proposes a recommendation.

## File layout

Actual layout as of 2026-05-12 (✅ = exists; • = future spike):

```
scripts/ir_experiment/                 # one-off, not part of mdd's package tree
├── __init__.py                        ✅
├── __main__.py                        ✅ CLI entry: python -m ir_experiment
├── harness/
│   ├── corpus.py                      ✅ Fixture loader
│   ├── pipeline.py                    ✅ Pipeline protocol + result types
│   ├── metrics/
│   │   ├── text_fidelity.py           ✅ M1
│   │   ├── structural_fidelity.py     ✅ M2
│   │   ├── identity_preservation.py   ✅ M3
│   │   ├── provenance.py              ✅ M4
│   │   ├── whitespace_drift.py        ✅ M5
│   │   └── code_surface.py            ✅ M6
│   ├── report.py                      ✅ markdown report writer
│   └── html_report.py                 ✅ HTML report with side-by-side diffs
├── pipelines/
│   ├── status_quo.py                  ✅
│   ├── pandoc_lua.py                  ✅ spike 010
│   ├── confluence_storage.lua         ✅ spike 010 (the Lua writer)
│   └── docling.py                     ✅ spike 011
└── README.md                          (deferred; mise help is sufficient)

mise.toml entries:
  ir-experiment   = "uv run python -m ir_experiment ..."   (PYTHONPATH=scripts)
  refresh-corpus  = "uv run python scripts/refresh-corpus.py ..."
```

`refresh-corpus` is a separate small script (not part of the
harness itself) that lives in the corpus repo
(`mdd/test-confluence/MDD/scripts/refresh-corpus.py`) and uses
the same `mdd` client as `push-fixtures.py`.

## Using `test_corpus.shapes` tags

Each fixture's frontmatter carries a `test_corpus.shapes` list:

```yaml
test_corpus:
  authoring: confluence-first
  shapes:
    - callout-tip
    - inline-strong
    - inline-em
    - inline-code
```

The harness uses these tags two ways:

1. **Filter:** `--shapes link-ri-page` runs only fixtures whose
   shape list includes `link-ri-page` — useful for focused
   debugging.
2. **Aggregate:** the comparison report breaks scores down by
   shape ("how well does Pandoc handle `ac:link/ri:page`
   specifically vs callouts"). This is where the per-shape
   fidelity story lives.

## What's deliberately *not* in this note

- Concrete Lua-writer code. That lands in spike 010.
- The provenance-map data structure (sidecar JSON vs HTML
  comments vs `data-mdd-id` attributes) — decided per pipeline
  in its respective spike.
- Conflict UX or merge algorithm — that's after the comparison.
- Performance instrumentation. Skip until the corpus is bigger
  or the spikes show suspicious latency.
- CI integration. The harness runs locally for now. CI
  integration is downstream of the recommendation.

## Open questions

1. **Levenshtein at scale.** O(n²) on full storage XHTML strings
   gets slow on the long-form pages (~5kB). Probably switch to a
   line-level diff with character-level inside changed lines.
   Decide when the harness is being written.
   *Resolved (provisionally) 2026-05-12*: classic O(n*m) Levenshtein
   was fine for the current 35-fixture corpus (longest fixture
   ~5kB; full run completes in <1 s). Revisit if the corpus grows
   10×.
2. **What does "structural fidelity" count for nested macros?**
   A `tip` macro containing a list containing inline code — is
   that 1 macro, or 1 macro + 1 list + 1 inline span? Per-shape
   tagging in the fixture may need to grow.
   *Resolved (provisionally) 2026-05-12*: the current M2
   implementation counts every block independently (`<ul>` and the
   `<li>` children inside a `<tip>` macro each contribute), and
   keys `ac:structured-macro` by its `ac:name` so swapping a tip
   for a note registers as drift. Per-shape weighting still
   deferred; per-shape *aggregation* (averaging M2 across fixtures
   carrying the same shape tag) is in.
3. **Should the harness round-trip via the live API or just
   in-memory?** In-memory (just running the converters back-to-
   back) is faster but doesn't exercise the actual create / update
   PUT shape that Confluence might re-normalise. Live round-trip
   catches "Confluence rewrote our storage XHTML on save" but
   adds API quota and flakiness. Probably both, gated by `--live`.
   *Decided 2026-05-12*: in-memory only for now. `--live` mode is
   deferred until spikes 010 / 011 surface a case that needs it.
   The baseline numbers in note 009 are explicitly an *upper bound*
   on real-world fidelity — the live tier can only be worse.
4. **Where does the provenance map live in markdown for the
   status-quo + provenance spike?** Sidecar JSON is one option;
   HTML comments inline are another; frontmatter is a third. Pick
   in spike 009.
   *Still open.* Spike 009 ended up being status-quo *without*
   provenance, since the existing converters don't emit any. The
   "status-quo + provenance" variant is now its own future spike;
   the picker question moves with it.
5. **Pandoc binary as a hard dependency for the experiment** —
   document the install path (`brew install pandoc` or platform
   equivalent), or vendor it in a docker layer. Decide in spike
   010. *Still open — pick when spike 010 starts.*

## Sequence of work (if we proceed)

1. **Bootstrap the harness skeleton.** ✅ Done 2026-05-12.
   `scripts/ir_experiment/harness/corpus.py`,
   `harness/pipeline.py`, `pipelines/status_quo.py` (wraps existing
   converters), `tests/ir_experiment/` smoke tests. Loader resolves
   the corpus via `MDD_CORPUS_PATH` or `test-confluence/MDD`
   relative to the mdd repo.
2. **Implement the snapshot refresh script.** ✅ Done 2026-05-12
   (one session earlier). `scripts/refresh-corpus.py` wraps a
   corpus-side `mdd/test-confluence/MDD/scripts/refresh-corpus.py`;
   `mise run refresh-corpus`. Initial `_snapshots/` tree (35 pages)
   captured and committed.
3. **Write metric calculators.** ✅ Done 2026-05-12.
   M1 text_fidelity, M2 structural_fidelity, M3 identity_preservation,
   M4 provenance_coverage, M5 whitespace_drift, M6 code_surface all
   live under `harness/metrics/`. Per-shape aggregation + worst-5
   sampler + HTML side-by-side diff report layered on top. M3
   returns `None` when `pipeline.supports_identity = False`; M4
   returns `None` when `pipeline.supports_provenance = False` —
   status_quo declares both False (the note's policy: don't
   conflate "didn't try" with "tried and failed").
4. **Run spike 009** (status quo, no provenance). ✅ Done
   2026-05-12. [`R09-confluence-ir-spike-status-quo.md`](R09-confluence-ir-spike-status-quo.md).
   Baseline: mean text_fidelity 0.86, structural 0.70,
   whitespace_drift 0.61; 576 LOC code surface. Known brittle on
   `ac:link/ri:*`, callout macros, list paragraph wrapping,
   CDATA-required code content.
5. **Run spike 010** (Pandoc + Lua writer). ✅ Done 2026-05-12.
   [`R10-confluence-ir-spike-pandoc-lua.md`](R10-confluence-ir-spike-pandoc-lua.md).
   Wins all three measurable fidelity metrics: mean text 0.97,
   structural 0.77, whitespace 0.75. No identity/provenance
   wired up (deferred to a follow-up if note 012 picks pandoc).
   ~125× slower per fixture than status_quo in memory, dominated
   by subprocess startup (mitigable via pandoc's `--server`
   mode). 202 LOC (77 Python + 125 Lua), no upstream-maintained
   writer half.
6. **Run spike 011** (docling). ✅ Done 2026-05-12.
   [`R11-confluence-ir-spike-docling.md`](R11-confluence-ir-spike-docling.md).
   Wins on text fidelity (mean 0.94 vs status_quo's 0.86) and on
   per-block provenance hooks (`self_ref`, coverage 1.00); loses
   on structural fidelity (0.41 vs 0.70) because of hard-wrap
   paragraph re-segmentation and silent dropping of Confluence
   namespaced elements. ~15× slower than status_quo per fixture
   in memory — still sub-second for the full 35-fixture run. 78
   LOC adaptor on top of the docling library.
7. **Write comparison note 012.** ✅ Done 2026-05-12.
   [`R12-confluence-ir-comparison.md`](R12-confluence-ir-comparison.md).
   Recommends **pandoc + Lua** as the IR foundation, with two
   bounded follow-ups (identity / provenance plumbing; code-block
   and merged-cell writer growth). Pandoc wins all three
   measurable fidelity metrics by clear margins; docling holds
   the provenance-affordance card; status_quo holds latency.
   Sequencing in §"Sequencing" of note 012.
8. **Promote the recommendation into a real spec**
   (`028-confluence-bidirectional-sync.md` or similar) covering
   the merge algorithm, conflict UX, cache layout, and migration
   path from the current sync model. Pending.

Research thread closed. Remaining work is step 8 (spec
promotion) — owned downstream of this note. Estimate per note
012: **~2-3 weeks of focused work** from spec to default flip,
plus the merge / 3-way story.

## Where we left off (2026-05-12)

Five sessions on 2026-05-12 closed the IR research thread:
harness + all three spikes + the comparison recommendation.
Commits on `main`:

- `8ae6cb1` — scripts adapted to detected git remotes (pre-008 cleanup)
- (slice 1, in 008-prep) — skeleton + corpus loader
- (slice 2) — pipeline protocol + status_quo + M1
- (slice 3) — M2 + report + note 009
- `a3d3e12` — HTML reporter with side-by-side diff outliers
- `bf8d082` — `--no-header` on `mdd confluence export`; harness
  strips export header from compared markdown
- `70144ae` — M3 / M4 / M5 / M6 + per-shape aggregation
- `bb9d2b2` — note 009 addendum with M3–M6 numbers
- `884c1da` — outlier blocks collapsible; only-outlier rows linked
- (session 3) — wall-clock timing per direction + spike 011
  (docling): adapter, registration, note 011 with comparison
  against the status-quo baseline
- (session 4) — spike 010 (pandoc + Lua): subprocess adapter,
  classic-style Lua writer covering paragraph / heading / list /
  table / code-macro / inline shapes, note 010 with comparison
  against both prior baselines.
- (session 5) — comparison note 012: per-shape comparison table
  across the three pipelines + maintainability / latency / code
  surface assessment. Recommends pandoc + Lua with two bounded
  follow-ups (identity / provenance plumbing; code-block +
  merged-cell writer growth).

What the downstream spec session should pick up:

1. **Draft `docs/spec/<NN>-confluence-bidirectional-sync.md`**
   per note 012's "Sequencing" section. First slice:
   `data-mdd-id` / `data-mdd-confluence-id` channel, macro-shape
   pre/post-processors, merged-cell tables, pandoc `--server`
   mode wrapper, harness as a CI gate.
2. **Move the spike code into the production tree** under a
   feature flag — `pipelines/pandoc_lua.py` and
   `confluence_storage.lua` migrate into `src/mdd/confluence/`.
3. **Flip the default** once per-shape thresholds hold for a few
   real pages over a few weeks of A/B usage.

The three-pipeline numbers (for the spec session's record):

- Pandoc wins all measurable fidelity metrics (M1 0.97, M2 0.77,
  M5 0.75); ~125× slower than status_quo in memory but the cost
  is subprocess startup (fixable via `--server`).
- Docling wins on provenance hooks (M4 = 1.00 via `self_ref`)
  but loses badly on structural fidelity (0.41) because of
  hard-wrap re-paragraphing.
- Status_quo holds the middle on structural (0.70) but is
  brittle on macro-shape preservation (M1 = 0.86, with several
  fixtures below 0.25 from `{=confluence}` raw-XML bloat).

## Decisions deferred from prior notes

Resolving these belongs in note 008 territory:

- **From note 007 §"Open questions before bootstrapping" #1**
  (submodule vs vendored vs path config): the harness uses a
  configurable path (`MDD_CORPUS_PATH` env var, defaulting to
  `../test-confluence/MDD` relative to the mdd repo). Sibling
  checkout in the same parent directory is the assumed layout.
  Not a submodule (cross-org git pain) and not vendored
  (duplication).
- **From note 007 §"Open questions" #2** (snapshot diff
  tolerance): hard-fail in the integration tier when any tracked
  metric crosses the threshold (default text-fidelity ≥ 0.99,
  identity-preservation ≥ 0.95, structural-fidelity ≥ 0.95).
  Operator can run `mise run refresh-corpus` if the drift is
  legitimate; CI never auto-refreshes.

## Cross-references

- [Research note 006](R06-confluence-bidirectional-sync-ir.md) —
  IR design space.
- [Research note 007](R07-confluence-test-corpus.md) — corpus
  specification.
- Manual test plan run on 2026-05-11 — the round-trip work that
  motivated this note (the plan itself has since been retired).
- `mdd/test-confluence/MDD` — the corpus repo, 26 live pages.
- Fixed bugs that the harness should pin down with regression
  tests: issues #70-#74 in the tracker that predates this
  repository (entity dropping, `ac:link` handling, callout macros,
  list paragraph wrapping, CDATA-required code content).

## Next research note

All three spikes plus the comparison recommendation landed
2026-05-12:
[009 status_quo](R09-confluence-ir-spike-status-quo.md),
[010 pandoc + Lua](R10-confluence-ir-spike-pandoc-lua.md),
[011 docling](R11-confluence-ir-spike-docling.md),
[012 comparison + recommendation](R12-confluence-ir-comparison.md).
The research thread is closed. The next document is a real spec
under `docs/spec/`, not another research note.
