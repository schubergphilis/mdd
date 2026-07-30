# Why mdd has its own document IR

`mdd` converts documents between Confluence storage XHTML and Markdown through
its own intermediate representation: a tree of typed Python `dataclass`
nodes, defined in `src/mdd/ir/`
([S28](../spec/S28-document-ir-foundation.md)). Building a document model from
scratch is the kind of decision that usually deserves suspicion — mature
converters exist, and Pandoc alone has handled this problem space for two
decades. This article explains why `mdd` built one anyway. The short version:
the decision was made by measurement, four candidate pipelines were implemented
and scored against the same corpus of real Confluence pages, and the winner was
not on the original shortlist.

## The problem: sync needs untouched content to survive

The first version of Confluence sync punted on merge: when both Confluence and
the local Markdown changed between sync points, it emitted a `CONFLICT` event
and skipped the page
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). Fixing that
requires real bidirectional merge, and merge has a hard prerequisite: every
storage element the user did *not* touch must round-trip unchanged — macro IDs
intact, attribute order preserved, whitespace the way Confluence emitted it.
Otherwise every push silently rewrites half the page
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

The converters `mdd` had at the time could not provide this. The two direction
walkers, `storage_to_md.py` and `md_to_storage.py`, shared no vocabulary:
every Confluence shape was encoded twice, once per direction, with fenced raw
blocks as the only escape hatch, and there was no representation either
converter could attach identity or provenance *to*
([S28](../spec/S28-document-ir-foundation.md)). The natural fix is an
intermediate representation with identity per node, so that merge becomes a
tree diff and untouched nodes re-render to their original bytes
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

That much was agreed early. Which IR to use was not — and the project decided
to settle it empirically rather than by argument: build a corpus of real
Confluence pages, build a harness that scores any candidate pipeline on the
same metrics, and implement each candidate as a spike
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

An early draft of the design also had to correct itself before the spikes
started: it spoke of "byte-for-byte" preservation, which the note itself calls
wrong — diff and merge belong at the AST level, not at byte offsets, because
character-offset diffing breaks on the first non-ASCII code point and encodes
no semantics ([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

## The harness: numbers, not vibes

The experiment harness
([R08](../research/R08-confluence-ir-experiment-harness.md)) ran every
candidate against 35 snapshot pages from a live Confluence instance, scoring
each round-trip (storage → Markdown → storage) on six metrics: text fidelity,
structural fidelity, identity preservation, provenance coverage, whitespace
drift, and code surface. Its stated job was to make the comparison "grounded
in numbers, not vibes"
([R08](../research/R08-confluence-ir-experiment-harness.md)). Each fixture
carried shape tags (`callout-tip`, `link-ri-page-same-space`, …) so failures
could be traced to specific Confluence constructs rather than aggregate
averages.

Three candidates were shortlisted
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). All three lost.

## Loser one: the status quo, kept as a baseline

The first spike wrapped the existing converter pair unchanged
([R09](../research/R09-confluence-ir-spike-status-quo.md)). On plain prose it
was fine: eleven fixtures scored perfect on both fidelity metrics. What killed
it was measured on the Confluence-namespaced shapes: a same-space page link
scored 0.22 on text fidelity, an attachment link 0.13, a status macro 0.11 —
because the Markdown-to-storage path did not recognize the inline shapes the
storage-to-Markdown path emitted, and fell back to verbose raw-XML blocks. A
146-character original became 666 characters; an 80-character status macro
became 750 ([R09](../research/R09-confluence-ir-spike-status-quo.md)). The
comparison note's verdict: correct on most shapes, brittle on exactly the
ones merge cares about, with no identity and no provenance
([R12](../research/R12-confluence-ir-comparison.md)).

## Loser two: Docling, good at the wrong layer

Docling was attractive on paper: Python-native, in-process, already a
transitive dependency of `mdd`, MIT-licensed, and with identity and provenance
slots (`self_ref`, `prov`) built into its document model
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). The research
notes flagged its meaningful gap before the spike ran: no `RawBlock`
equivalent, no idiom for "carry these bytes through verbatim, I don't know
what they mean" ([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

The measurement confirmed and sharpened this. Docling scored well on text
fidelity (0.94, where the status quo scored 0.86) but collapsed on structural
fidelity: 0.41, the worst of any candidate
([R11](../research/R11-confluence-ir-spike-docling.md)). Two causes: its
Markdown export hard-wraps prose, and the re-parse then treats each wrapped
line as its own paragraph — a four-paragraph fixture came back as twelve — and
Confluence-namespaced elements it does not recognize are silently dropped at
the wrapper level ([R11](../research/R11-confluence-ir-spike-docling.md)).
The comparison ruled it out because the fixes were "upstream-shaped, not in
our control" ([R12](../research/R12-confluence-ir-comparison.md)).

An earlier, grander framing of the Docling option also got walked back in
writing: the claim that adopting Docling would unify the IR across `mdd`'s
PDF, DOCX, PPTX, and Confluence paths is recorded as "an overreach" — there is
no `DoclingDocument` → DOCX/PPTX writer, and the question was only ever about
storage XHTML ↔ Markdown
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

## Loser three: Pandoc with a Lua writer — the recommendation that got reversed

Pandoc was the reasonable bet. Its IR is twenty years old and versioned,
carrying unknown bytes through verbatim is a first-class concept (`RawBlock`),
and the exact architecture — Pandoc AST plus a custom Lua writer emitting
Confluence storage format — ships in production inside Quarto's Confluence
publisher, which the research notes studied line by line
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). The spike
delivered: Pandoc won all three measurable fidelity metrics against the other
two candidates (text 0.97, structural 0.77, whitespace 0.75), in about 200
lines of adaptor and Lua
([R10](../research/R10-confluence-ir-spike-pandoc-lua.md)).

On that evidence, the comparison note recommended it. The original
recommendation in [R12](../research/R12-confluence-ir-comparison.md) reads:
adopt Pandoc + Lua, with two follow-ups before production — wire identity and
provenance through the writer, and close the code-block and merged-cell gaps.

That recommendation lasted less than a day. Its own text records the tension
that undid it: the fidelity margin over the status quo was real but modest
(0.08–0.14 aggregate), while the costs were concrete — roughly 125× the
per-fixture latency (process startup, mitigable but real), a 7 MB GPL
binary, Lua as a second implementation language, and, most tellingly, the
identity and provenance channels that motivated the whole exercise still
not wired up, deferred to follow-up work
([R13](../research/R13-confluence-ir-spike-pure-python.md)).

## The late entrant that won

[R06](../research/R06-confluence-bidirectional-sync-ir.md) had named the
design principle — an IR with identity per node, diffed at the AST level — but
every shortlisted candidate delegated the IR to a third party. A fourth spike,
run after the recommendation was already written, implemented the principle
directly: a pure-Python typed IR, with identity and provenance carried on the
nodes themselves rather than bolted on afterward
([R13](../research/R13-confluence-ir-spike-pure-python.md)).

It swept the board. Text fidelity 0.9988, structural 0.9838, whitespace
0.9830; identity preservation and provenance coverage both 1.0 — the only
candidate to wire identity at all; 27 of the 35 fixtures perfect on every
metric simultaneously; total corpus round-trip in 31 ms against Pandoc's
2895 ms ([R13](../research/R13-confluence-ir-spike-pure-python.md)). The
comparison note was revised in place, preserving the Pandoc analysis
under an explicit "original recommendation" heading so the trade-off
reasoning stays on the record
([R12](../research/R12-confluence-ir-comparison.md)).

The one metric the pure-Python IR lost was code surface: 2249 lines, against
78 for the Docling adaptor and 202 for Pandoc
([R12](../research/R12-confluence-ir-comparison.md)). The comparison's
reading of that number is the crux of the build-versus-adopt call: the 78-line
Docling adaptor sits on top of a large pre-1.0 library, the 202-line Pandoc
adaptor on a GPL binary plus a Lua writer with no upstream — while the 2249
lines are the only option whose entire surface lives in the repository, with
no library to track, version, or migrate
([R12](../research/R12-confluence-ir-comparison.md)). `mdd` did not build an
IR because building is fun; it bought identity, provenance, and fidelity
whose remaining gaps were a bounded five-fix list of about 50 lines
([R13](../research/R13-confluence-ir-spike-pure-python.md)), at the price of
owning the code.

## What the spike became — and what got reversed after

The spike was promoted into the production tree as three specs: the IR types
and identity contract ([S28](../spec/S28-document-ir-foundation.md)), the
Confluence storage converters
([S29](../spec/S29-confluence-ir-conversion.md)), and the Markdown converters
([S30](../spec/S30-markdown-ir-conversion.md)). The five fidelity fixes from
the spike are all recorded as shipped in
[S29](../spec/S29-confluence-ir-conversion.md), and the old converter pair was
deleted once the IR converters took over, rather than kept indefinitely as
wrappers ([S29](../spec/S29-confluence-ir-conversion.md)).

Even after promotion, one piece of the winning plan was reversed. The spike
and the comparison both sketched an on-disk sidecar —
`<page>.confluence.json` next to each Markdown file — as the production home
for cached identity ([R12](../research/R12-confluence-ir-comparison.md)).
That design was retired: production metadata lives in the Markdown file's
YAML frontmatter, and the cached-IR lookup happens in-process from the
remote-storage parse, so no sidecar file is written during normal runs
([S31](../spec/S31-ir-normalization-and-whitespace.md)).

What the IR guarantees today — which shapes round-trip byte-perfect, and
where the documented trade-offs sit — is a story of its own, covered in
[what near-lossless means](near-lossless.md).

The methodological point stands apart from the outcome. Any of the four
candidates could have been argued for persuasively in prose; the corpus and
harness made the argument unnecessary. A written recommendation was overturned
within a day of being made, at the cost of one more spike, because the
measurement battery made a late entrant directly comparable to three
incumbents ([R12](../research/R12-confluence-ir-comparison.md)). That is the
cheapest a reversal ever gets.
