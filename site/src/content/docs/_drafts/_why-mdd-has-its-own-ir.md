# Why mdd has its own document IR

Take one page from `mdd`'s test corpus. In the Confluence editor it reads "The
current status is On track. A problematic status would be Blocked" — 80
characters of visible text, each status drawn as a small colored lozenge. In
storage format, each lozenge is a macro. This is the first one, copied from
the committed snapshot
`tests/corpus/confluence/_snapshots/164105/storage.xhtml`:

```xml
<ac:structured-macro ac:name="status" ac:schema-version="1" ac:macro-id="3fe67e21-3b3d-4d7e-a364-77d2e531f479"><ac:parameter ac:name="title">On track</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro>
```

Before `mdd` had a document IR, exporting this page produced the Markdown
below — committed in
`tests/corpus/confluence/fixtures/niche-macros/status.md`, exported on
2026-05-11 by the converter `mdd` shipped at the time:

```markdown
The current status is `<ac:structured-macro xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/repository/confluence/1.0" ac:name="status" ac:schema-version="1" ac:macro-id="3fe67e21-3b3d-4d7e-a364-77d2e531f479"><ac:parameter ac:name="title">On track</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro>`{=confluence} .
```

The 237-character macro became a 350-character inline code span of raw XML,
`xmlns` declarations included — semantically intact, but a blob no person
would want to edit. Round-tripping back to storage made it worse: the page's
80 characters of visible text came back as 750, and a sibling fixture holding
two same-space page links grew from 146 characters to 666
([R09](../research/R09-confluence-ir-spike-status-quo.md)).

Numbers like these are why `mdd` now converts between Confluence storage XHTML
and Markdown through its own intermediate representation: a tree of typed
Python `dataclass` nodes in `src/mdd/ir/`
([S28](../spec/S28-document-ir-foundation.md)). Building a document model from
scratch deserves suspicion — Pandoc alone has handled this problem space for
two decades. So the decision was made by
measurement: four candidate pipelines, scored against the same corpus of real
Confluence pages, and a winner that was not on the original shortlist.

## Sync needs untouched content to survive

The first version of Confluence sync punted on merge: when both Confluence and
the local Markdown changed between sync points, it reported a conflict and
skipped the page ([R06](../research/R06-confluence-bidirectional-sync-ir.md)).
Fixing that requires real bidirectional merge, and merge has a hard
prerequisite: every storage element the user did *not* touch must round-trip
unchanged — macro IDs intact, attribute order preserved, whitespace the way
Confluence emitted it. Otherwise every push silently rewrites half the page.

The status-macro example shows why the old code could not deliver that. The
two converters, one per direction, shared no vocabulary: every Confluence
shape was encoded twice, with raw-XML spans like the one above as the only
escape hatch, and there was nothing either converter could attach identity or
provenance *to* ([S28](../spec/S28-document-ir-foundation.md)). The natural
fix is an intermediate representation with identity per node, so that merge
becomes a tree diff and untouched nodes re-render to their original bytes.

That much was agreed early. Which IR to use was not, and the project settled
it empirically: a corpus of real Confluence pages, a harness that scores any
candidate pipeline the same way, and one spike per candidate. The design had
already corrected itself once before the spikes started.
An early draft spoke of "byte-for-byte" preservation, which the note itself
calls wrong: diff and merge belong at the level of the parsed tree, not at
byte offsets, where the first non-ASCII character breaks the arithmetic
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

## Numbers, not vibes

The harness ran every candidate against 35 snapshot pages from a live
Confluence instance, scoring each round trip on six measurements: how much
visible text survives, whether the block structure survives, whether macro IDs
survive, whether each Markdown block can be traced back to a storage element,
whitespace drift, and code size
([R08](../research/R08-confluence-ir-experiment-harness.md)). Its stated job
was to keep the comparison "grounded in numbers, not vibes". Each fixture
carried shape tags — callout, page link, status macro — so failures pointed
at specific Confluence constructs rather than disappearing into an average.

Three candidates were shortlisted. All three lost.

## The baseline: correct on prose, broken where it matters

The first spike wrapped the existing converter pair unchanged, to give the
others a baseline to beat
([R09](../research/R09-confluence-ir-spike-status-quo.md)). On plain prose it
was fine: eleven of the 35 fixtures came through perfect on both fidelity
scores. It collapsed on the Confluence-namespaced shapes, exactly as the
example above shows — the status-macro page scored 0.11 on text fidelity, an
attachment link 0.13, a same-space page link 0.22, each ballooning into raw
XML because the Markdown-to-storage direction did not recognize the spans the
other direction emitted. The comparison's verdict: correct on most shapes,
brittle on exactly the ones merge cares about, no identity, no provenance
([R12](../research/R12-confluence-ir-comparison.md)).

## Docling: good text, wrong structure

Docling was attractive on paper: Python-native, in-process, already a
transitive dependency of `mdd`, MIT-licensed, with identity and provenance
slots built into its document model
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). The research
flagged its gap before the spike ran: no equivalent of a raw block, no idiom
for "carry these bytes through verbatim, I don't know what they mean."

The measurement sharpened that gap into a rejection. Docling scored well on
text fidelity — 0.94, where the baseline scored 0.86 — but worst of any
candidate on structure, at 0.41
([R11](../research/R11-confluence-ir-spike-docling.md)). Its Markdown export
hard-wraps prose and its re-parse treats each wrapped line as a new paragraph,
so a four-paragraph fixture came back as twelve; Confluence-namespaced
elements it does not recognize are silently dropped. The comparison ruled it
out because the fixes were "upstream-shaped, not in our control"
([R12](../research/R12-confluence-ir-comparison.md)).

One Docling claim had been withdrawn even earlier: that adopting it would
unify the document model across `mdd`'s PDF, DOCX, PPTX, and Confluence paths.
The note records that as "an overreach" — no writer exists from Docling's
model back to DOCX or PPTX, and the question was only ever about storage XHTML
and Markdown ([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

## Pandoc: the recommendation that lasted a day

Pandoc was the reasonable bet. Its document model is twenty years old,
carrying unknown bytes through verbatim is a first-class concept there, and
the exact architecture — Pandoc plus a custom Lua writer emitting Confluence
storage — ships in production inside Quarto's Confluence publisher, which the
research studied line by line
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). The spike
delivered: Pandoc won every fidelity score then measurable — 0.97 on text,
0.77 on structure, 0.75 on whitespace — in about 200 lines of adaptor and Lua
([R10](../research/R10-confluence-ir-spike-pandoc-lua.md)).

On that evidence the comparison note recommended it, with two follow-ups
before production: wire identity and provenance through the writer, and close
known gaps around code blocks and merged table cells
([R12](../research/R12-confluence-ir-comparison.md)).

The recommendation lasted less than a day, and its own text records the
tension that undid it. The fidelity margin over the baseline was real but
modest, while the costs were concrete: roughly 125 times the per-page latency,
a 7 MB GPL-licensed binary, Lua as a second implementation language — and,
most telling, the identity and provenance channels that motivated the whole
exercise still not wired up, deferred to follow-up work
([R13](../research/R13-confluence-ir-spike-pure-python.md)).

## The late entrant that won

The design principle had been on paper from the start — an IR with identity on
every node, diffed as a tree — yet every shortlisted candidate delegated the
IR to a third party. A fourth spike, run after the recommendation was written,
implemented the principle directly: a pure-Python typed IR, with identity and
provenance carried on the nodes themselves rather than bolted on afterward
([R13](../research/R13-confluence-ir-spike-pure-python.md)).

It swept the board. Text fidelity 0.9988, structure 0.9838, whitespace 0.9830,
and identity preservation and provenance coverage both complete — it was the
only candidate that wired identity at all. Twenty-seven of the 35 fixtures
came through perfect on every measurement simultaneously, and the whole corpus
round-tripped in 31 ms against Pandoc's 2895 ms
([R13](../research/R13-confluence-ir-spike-pure-python.md)). The comparison
note was revised in place, keeping the Pandoc analysis under an explicit
"original recommendation" heading so the trade-off reasoning stays on the
record ([R12](../research/R12-confluence-ir-comparison.md)).

## What it cost

The one measurement the pure-Python IR lost was code size: 2249 lines, against
78 for the Docling adaptor and 202 for Pandoc
([R12](../research/R12-confluence-ir-comparison.md)). Reading that number is
the crux of the build-versus-adopt call. The 78-line Docling adaptor sits on
top of a large pre-1.0 library; the 202 Pandoc lines sit on a GPL binary plus
a Lua writer with no upstream; the 2249 lines are the only option whose entire
surface lives in this repository, with no library to track, version, or
migrate. `mdd` did not build an IR because building is fun. It bought
identity, provenance, and fidelity whose remaining gaps were a bounded list of
five fixes, about 50 lines in total, at the price of owning the code
([R13](../research/R13-confluence-ir-spike-pure-python.md)).

## What shipped, and what got reversed after

The spike was promoted into the production tree as three specs: the IR types
and identity contract ([S28](../spec/S28-document-ir-foundation.md)), the
Confluence storage converters
([S29](../spec/S29-confluence-ir-conversion.md)), and the Markdown converters
([S30](../spec/S30-markdown-ir-conversion.md)). The five fixes are recorded
there as shipped, and the old converter pair was deleted once the IR
converters took over, rather than kept indefinitely as wrappers
([S29](../spec/S29-confluence-ir-conversion.md)).

Even the winning plan lost a piece after promotion. The spike and the
comparison both sketched an on-disk sidecar — a `<page>.confluence.json` next
to each Markdown file — as the production home for cached identity
([R12](../research/R12-confluence-ir-comparison.md)). That design was retired:
page metadata lives in the Markdown file's YAML frontmatter, the cached-IR
lookup happens in-process from the remote-storage parse, and no sidecar file
is written during normal runs
([S31](../spec/S31-ir-normalization-and-whitespace.md)).

What the IR guarantees today — which shapes round-trip byte-perfect, and where
the documented trade-offs sit — is a story of its own, covered in
[what near-lossless means](near-lossless.md).

The method outlasts the outcome. Any of the four candidates could have been
argued for persuasively in prose; the corpus and harness made the argument
unnecessary. A written recommendation was overturned within a day, at the cost
of one more spike, because the harness made a late entrant directly comparable
to three incumbents ([R12](../research/R12-confluence-ir-comparison.md)). That
is the cheapest a reversal ever gets.
