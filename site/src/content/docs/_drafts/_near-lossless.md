# What "near-lossless" actually means

The README promises "near-lossless roundtrips" between Markdown in git and
Confluence. Before you point `mdd` at a space you care about, you deserve a
precise reading of that phrase: which round-trip the claim is about, what
survives it and by what mechanism, what does not survive, and how CI enforces
the boundary. This article gives that reading. For the story of
why the machinery underneath exists at all, read
[why mdd has its own IR](why-mdd-has-its-own-ir.md).

## The round-trip the claim is about

`mdd` converts through a typed intermediate representation, and the test suite
gates three distinct round-trips through it
([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)): storage to IR to
storage (R1), Markdown to IR to Markdown (R2), and the full bidirectional trip
— Confluence storage to IR to Markdown to IR back to storage (R3).

R3 is the one the promise rides on, because it is what a sync run performs
when you pull a page and push it back. The gate on it is not "close": for
content you did not edit, the round-tripped storage must equal the original
[byte for byte](../spec/S33-ir-roundtrip-testing-and-benchmarks.md), and CI
fails when any corpus page stops satisfying that.

So the honest one-sentence version is: **unmodified content round-trips
without loss; edited content and a documented list of constructs do not, and the
"near" is that list.** The rest of this article walks the list.

## Why "lossless" is not on the table

Confluence stores a page as namespaced XHTML in which macros, layout cells,
and links carry identity attributes — `ac:local-id`, `ac:macro-id`,
`ac:schema-version` — that Confluence itself needs back
([S28](../spec/S28-document-ir-foundation.md)). Markdown has nowhere to put
them, and `mdd` [deliberately refuses](../spec/S30-markdown-ir-conversion.md)
to invent a place: no `data-mdd-*` attributes, no HTML comment trails, because
the Markdown file is what humans read and edit.

Any converter therefore faces a fork: pollute the Markdown with metadata, or
carry the metadata somewhere else. `mdd` carries it somewhere else, and
"near-lossless" is the measured result of that choice.

## What survives, and by what mechanism

Three mechanisms do the preserving.

**Nothing is dropped silently.** A reader that meets a shape it does not
recognize must emit a `RawBlock` or `RawInline` holding the source verbatim —
the [fallback contract](../spec/S28-document-ir-foundation.md) states this as
"MUST NOT silently drop content". On the Markdown surface an unknown macro
appears as a fenced block tagged `confluence-xml` with the storage XHTML
inside — editable only as XHTML, but present in the file and visible in every
diff. Every fallback also raises a `FallbackEmitted` event, and CI
[fails](../spec/S33-ir-roundtrip-testing-and-benchmarks.md) when one fires on
a fixture not explicitly tagged as a fallback case — falling back is allowed,
falling back unexpectedly is a build failure.

**Identity is grafted back.** Since the Markdown leg drops identity
attributes, the push path re-fetches the remote storage, parses it, and
[reattaches](../spec/S28-document-ir-foundation.md) the cached tree's
`node_id`, attributes, and reader-only fields onto the tree parsed from your
Markdown — "fresh wins, cached fills". This is production behavior, not a test
harness trick: `mdd confluence update-page` reuses the storage it already
fetched for the diff display, and an integration test asserts that pushing an
unedited export [issues no PUT at
all](../spec/S33-ir-roundtrip-testing-and-benchmarks.md). An earlier design
kept the cached IR in a `<page>.confluence.json` sidecar next to each file;
that sidecar was [retired](../spec/S31-ir-normalization-and-whitespace.md)
because page metadata already lives in the Markdown's frontmatter and the
lookup happens in-process from the fetched storage.

**Source form is recorded.** In preserving mode every node carries an
[`Origin`](../spec/S31-ir-normalization-and-whitespace.md): the exact source
bytes, leading and trailing whitespace, and the entity form of each character
— so a page that spells `…` as `&hellip;` gets its `&hellip;` back instead of
a normalized Unicode character, and a CDATA section keeps its trailing
newline.

## The numbers, and where they come from

The claim started as a measurement. Four candidate pipelines ran against the
same 35-fixture corpus in May 2026, scoring text fidelity (M1), structural
fidelity (M2), whitespace drift (M5), identity preservation (M3), and
provenance coverage (M4). The then-production converter scored an aggregate
M1 of 0.8559 with individual fixtures [as low as
0.11](../research/R12-confluence-ir-comparison.md); the comparison note first
recommended pandoc with a Lua writer, then reversed itself when a fourth,
pure-Python spike [beat pandoc on every fidelity
metric](../research/R12-confluence-ir-comparison.md) — M1 = 0.9988,
M2 = 0.9838, M5 = 0.9830, M3 and M4 both 1.0, with [27 of 35 fixtures
perfect on every metric
simultaneously](../research/R13-confluence-ir-spike-pure-python.md). The eight
imperfect fixtures reduced to a [five-fix list of about 50
lines](../research/R13-confluence-ir-spike-pure-python.md) — trailing empty
paragraphs, `start="1"` on ordered lists, macro attribute passthrough, a
standalone-link hint, and entity-form preservation — and those fixes are why
`Origin` exists.

Those percentages are historical: they date from a 35-fixture corpus and a
spike harness. What holds today is stricter and binary. The corpus has grown
to 82 captured Confluence pages plus Markdown-first fixtures for [every
CommonMark 0.31 construct, the GFM additions, and each mdd
extension](../spec/S32-ir-test-corpus-expansion.md), and the gates are: R3
byte-perfect in preserving mode, and in normalizing mode M1 ≥ 0.995 aggregate,
M2 ≥ 0.97, M3 = 1.0, M4 = 1.0, with a [per-fixture floor of
0.95](../spec/S33-ir-roundtrip-testing-and-benchmarks.md). You can run the
whole thing locally: `mise run ir-roundtrip` runs the three flavors,
`mise run ir-coverage` writes the coverage matrix to
`build/ir-coverage.json`, and both run inside `mise run ci`.

## What is known not to survive

The carve-outs are written down, and each one is a decision with a rejected
alternative behind it.

- **Backslash escapes.** The Markdown reader strips `\*` and `\_` per
  CommonMark; storage holds the literal character, and restoring the backslash
  on the way back needs a context-sensitive re-escape policy that is
  [deferred](../spec/S33-ir-roundtrip-testing-and-benchmarks.md). Fixtures
  exercising it are expected failures on the byte-perfect gate.
- **Empty paragraphs carrying an anchor id.** Confluence's editor records the
  cursor position as a trailing empty `<p>` with a `local-id`. Markdown has no
  syntax for that, and `mdd` [considered and rejected inventing
  one](../spec/S30-markdown-ir-conversion.md) — an HTML-comment marker or a
  fence with no body would either be noise in human-edited files or get
  stripped by other Markdown tooling, a silent loss anyway. Corpus pages that
  exhibited the shape were corrected at the source instead of taught to the
  converter.
- **Inline `<kbd>` and `<samp>`.** An allowlist gap in the Markdown reader's
  [raw-HTML handling](../spec/S33-ir-roundtrip-testing-and-benchmarks.md).
- **Text nodes over 256 KiB.** `Origin.raw_bytes` is
  [capped](../spec/S31-ir-normalization-and-whitespace.md); beyond the cap the
  writer falls back to its canonical render. The alternative — unbounded
  source capture — could turn a 5 MB page into a ~10 MB IR, and graceful
  degradation on that long tail won.
- **Merged-cell tables in the Markdown surface.** Pipe-table syntax cannot
  express `colspan` or `rowspan`, so the writer [falls back to a raw HTML
  `<table>`](../spec/S30-markdown-ir-conversion.md). Content survives; the
  clean Markdown surface does not.
- **Origin across structural edits.** Split a paragraph in two and the second
  half's recorded source form is meaningless; the system treats the page as
  edited and re-renders canonically rather than replaying [stale
  bytes](../spec/S31-ir-normalization-and-whitespace.md).

Separately, some page aspects are outside the model entirely rather than lossy
within it: comments, page restrictions, and page properties are not synced,
and labels are read but not pushed back — the [concepts
page](../guide/03-concepts.md) lists these, and [Safety](../guide/04-safety.md)
covers what they mean for a push.

## Losing things on purpose

One class of loss is a feature. The converter runs in [two
modes](../spec/S31-ir-normalization-and-whitespace.md): a preserving mode used
internally on the push leg so Confluence sees its own bytes back, and a
default normalizing mode for the files written to disk, which collapses soft
breaks, drops empty paragraphs, converts `&hellip;` to `…`, and trims
redundant attributes. These goals conflict — a byte-faithful export is full of
entity clutter and trailing blank paragraphs no human wants to read — and the
spec's answer is that [a single mode cannot serve
both](../spec/S31-ir-normalization-and-whitespace.md). Several normalization
passes are explicitly skipped in preserving mode precisely because the spike
found they cost round-trip bytes. When someone says the Markdown on disk is
not byte-identical to what a raw export would give: correct, and intentional.

## Attachments are a different promise

None of the above applies to attachments. On pull, `mdd` downloads the binary
and, for Office formats and PDF, writes a converted `.md`
[sibling](../spec/S16-confluence-attachment-conversion.md) next to it. The
binary is the fidelity copy; the sibling is a convenience for grep and diff in
the mirror, and page links keep pointing at the binary. The research behind
the Office story is blunt about the direction of truth: renders between
Markdown and `.docx` are one-way authoritative, and the design [never claims a
byte-stable round-trip](../research/R02-attachments.md) for them — divergence
is detected and surfaced to a human instead of merged.

## How the boundary is defended

The gates above run on every commit, and the discipline around them has two
properties worth knowing. Known failures are quarantined, not tolerated: a
page that stops round-tripping gets a reproducer snapshot in a strict
expected-failure tier (`tests/corpus/confluence/_xfail_snapshots/`), so the
moment a fix lands the test unexpectedly passes, CI fails, and the snapshot
must move into the main byte-perfect gate. That tier is empty at the time of
writing. And thresholds only ratchet one way: if a benchmark gate flakes, the
documented response is to [raise the ceiling, never to disable the
gate](../spec/S33-ir-roundtrip-testing-and-benchmarks.md). One gate was
honestly dropped rather than ratcheted — a hard limit keeping the JSON form of
the IR within 10× of the source size [could not be made
meaningful](../spec/S33-ir-roundtrip-testing-and-benchmarks.md) on small
fixtures, where structural overhead produces ~30× ratios on 200-byte pages,
so it was demoted to a design goal reviewers eyeball during corpus growth.

The IR did not become the default on green tests alone: promotion required the
gates green for two consecutive weeks, a whole-space sync round-tripping clean
against a live tenant, and a two-week A/B against the legacy converters with
[zero unexpected diffs](../spec/S33-ir-roundtrip-testing-and-benchmarks.md).
That is the standard "near-lossless" is held to, and the reason the word
"near" comes with a list instead of a shrug.
