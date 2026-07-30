# 006 - Intermediate representation for bi-directional Confluence sync

**Status:** Research notes. Not an implementation spec.

**Problem brief.** [Spec 014](../spec/S14-confluence-sync.md) defines a
sync loop with a deliberate punt: when both Confluence and the local
markdown mirror change between sync points, the sync emits a `CONFLICT`
event and skips the page. This is fine for an MVP, useless as a
working model — any non-trivial use of `mdd` against a Confluence space
that humans also edit will start producing conflicts faster than the
user can resolve them, and the resolution UX today is "go fix it
manually." We need real bidirectional merge.

Round-tripping a real, macro-heavy Confluence page through
[`storage_to_md.py`](../../src/mdd/confluence/storage_to_md.py) and
[`md_to_storage.py`](../../src/mdd/confluence/md_to_storage.py) made
the deeper problem visible: those two converters share no
intermediate representation. They each independently encode/decode
between Confluence storage XHTML and markdown, with `{=confluence}`
fenced raw blocks as the only escape hatch for content neither
converter knows how to represent. There is no provenance, no element
identity, no place to anchor "this paragraph in the markdown came
from that element in storage." Without that, merge is guesswork.

This note frames the design question, identifies the candidate
approaches, and proposes a sequence of experiments to decide between
them empirically rather than by argument. It deliberately stops short
of choosing a winner or writing a spec — both depend on what we
learn from the spikes.

## Why this is worth thinking about carefully

The naive approach — "diff markdown, project to storage, upload" — is
unsolvable in general because markdown is lossy relative to storage.
Every storage element the user did *not* touch must round-trip
**unchanged**: macro `ac:macro-id` attributes intact, parameter
ordering preserved, unknown attributes carried through, whitespace
the way Confluence emitted it. Otherwise every push silently rewrites
half the page.

The natural architecture for "preserve untouched parts" is **an
intermediate representation with identity per node**. The local
markdown edit becomes a delta over the IR; the IR's untouched nodes
re-render to their original storage representation. This is the same
shape as a tree-diff git merge: changed subtrees get rewritten,
everything else passes through.

But every IR choice has consequences for fidelity, performance,
toolchain, and long-term maintenance. The decision is not a
weekend's worth of code.

## A correction on layering

An early draft of this design talked about "byte-for-byte"
preservation of storage XHTML. That's wrong. All formats involved
(storage XHTML, markdown, JSON IRs) are character data, UTF-8 in
practice. The right layering is:

```
bytes  →  decode (UTF-8)  →  Unicode codepoints  →  tokenize  →  parse  →  AST
```

Diff and merge belong **at the AST / token level**, not at character
or byte offsets. Character-offset diffing breaks the moment a
non-ASCII codepoint appears (emoji in a heading, accent in an author
name) and encodes no semantics: a heading marker `# ` looks identical
to a literal `# ` in prose. Tree diff over a typed IR is the right
shape; codepoint diff is at most a tie-breaker inside a single
text-bearing leaf node.

## Candidate approaches

We have three plausible foundations. Each comes with its own
tradeoffs across fidelity, perf, toolchain, and ecosystem.

### A. Status quo + provenance map

Keep `storage_to_md.py` and `md_to_storage.py` as-is. Augment with a
provenance map produced at export time: for every markdown block,
record which storage element it came from. Persist as sidecar JSON
or as hidden HTML comments in the markdown. Merge becomes a walk
over both trees side-by-side using the map as the anchor.

- **Pro:** smallest delta from current code. No new dep, no new
  language.
- **Con:** no shared vocabulary between the converters — they're
  still two independent walkers. Macros remain opaque. No path to
  rendering anywhere except markdown and storage.
- **Con:** the provenance-map design is fragile under structural
  edits (block split, list-item promotion). Re-anchoring strategies
  need empirical validation.

### B. Pandoc-style IR via pandoc CLI

Build on Pandoc, which has a mature, well-documented intermediate
representation expressed as Haskell algebraic data types and
serialised stably as JSON
(see [pandoc-types](https://hackage.haskell.org/package/pandoc-types)
or `pandoc --print-default-data-file <format>` for shape).

Architecture:

```
storage XHTML  ─[ Python: lxml walk → pandoc JSON ]─→ pandoc JSON
                                                       │
                                              [ pandoc -f json -t markdown ]
                                                       ↓
                                                    markdown

markdown  ─[ pandoc -f markdown -t writer.lua ]─→ storage XHTML
```

The "writer.lua" half is a [custom Lua
writer](https://pandoc.org/lua-filters.html) — pandoc IR comes in as
Lua tables, the Lua code emits storage XHTML. This replaces the
placeholder-sentinel dance currently in `md_to_storage.py` with
something like 200 lines of declarative Lua. The Python half on the
input side keeps lxml for storage XHTML parsing (which is gnarly:
namespaces, CDATA, malformed-XHTML recovery) but emits pandoc JSON
dicts instead of markdown strings.

- **Pro:** pandoc IR is industrial-strength, 15+ years old, JSON
  schema versioned via `pandoc-api-version`.
- **Pro:** `RawBlock format text` and `RawInline format text` are
  first-class — exactly the passthrough mechanism we need for opaque
  Confluence macros.
- **Pro:** wide ecosystem signal — Quarto is built on Pandoc, so
  betting on Pandoc is also betting on a stack with a healthy
  parallel investment.
- **Pro:** GPLv2 is a non-issue if we shell out to the binary rather
  than link Haskell into mdd. The Lua writer + JSON pipeline are
  data-only interfaces — they don't infect mdd's own permissive
  licensing.
- **Pro:** the macro-modelling pattern is established (`Div` / `Span`
  with classes for structural macros, `RawBlock` / `RawInline` for
  opaque).
- **Con:** Lua is yet another language in the codebase (currently
  Python only).
- **Con:** subprocess startup cost (~50–100ms per invocation; not
  fatal but real). `pandoc server` mode mitigates but we don't need
  to worry about this yet.
- **Con:** ties us to Pandoc's IR vocabulary. If the schema bumps
  major version, we'd adapt. JSON is easy to adapt.

### C. Docling-based IR via in-process Python

Build on [docling](https://docling-project.github.io/docling/) and
its `DoclingDocument` IR. Docling is already a transitive dependency
of `mdd` (via `converters/docx.py`, `converters/pdf.py`,
`convert/pdf.py`).

Architecture:

```
storage XHTML  ─[ Python: lxml walk → DoclingDocument ]─→ DoclingDocument
                                                              │
                                                  [ docling.export_to_markdown() ]
                                                              ↓
                                                          markdown

markdown  ─[ DoclingDocument.from_markdown() ]─→ DoclingDocument ─[ Python: walk → storage XHTML ]─→ storage XHTML
```

- **Pro:** Python-native, in-process. No subprocess, no Lua, no
  JSON-over-pipe.
- **Pro:** already a dependency.
- **Pro:** every `*Item` has a `self_ref` and a `prov` field —
  identity and provenance are built in, not bolted on. That's
  exactly the slot the merge layer needs.
- **Pro:** MIT licensed.
- **Con:** **no `RawBlock` equivalent.** This is the meaningful gap.
  Docling's IR was designed for ingestion of well-structured
  documents into RAG pipelines; it has no idiom for "carry these
  bytes through verbatim, I don't know what they mean." We'd have
  to encode opaque Confluence XML as `CodeItem` with a custom
  language tag, or as `GroupItem` with a marker, or by extending
  the data model. None of these are as clean as Pandoc's
  `RawBlock`.
- **Con:** much less mature than Pandoc (~1 year vs ~20). IR may
  evolve. We can pin and adapt.
- **Con:** docling was not designed for edit-and-push-back; its
  reference flow is one-way (source → DoclingDocument → markdown
  for RAG). Using it as the foundation for bidirectional sync is
  using it past its design intent.
- **Con:** narrower ecosystem signal. Pandoc has Quarto, panflute,
  Lua filter libraries, and 40+ format adapters. Docling has its
  own ML pipelines and one document model.

### Why not "docling unifies the whole mdd document model"

An earlier framing of option C claimed adopting docling more deeply
would unify the IR across mdd's PDF / DOCX / PPTX / Confluence
legs. This was an overreach. There is no `DoclingDocument` →
DOCX / PPTX writer, and writing one is fiendishly hard:

- DOCX is a ZIP of >10 interrelated XML parts (document, styles,
  numbering, settings, relationships, theme, headers/footers as
  separate parts) with style inheritance and complex list-numbering
  definitions.
- PPTX adds slide masters, layouts, theme inheritance, shape
  geometry/transforms, animation timelines.
- `DoclingDocument` deliberately discards most of that — it captures
  semantic structure, not the styling that constitutes the document's
  identity in Office formats.
- Tools that *do* write DOCX (python-docx, LibreOffice headless,
  Pandoc's docx writer) all have well-known round-trip pain.

Practically, mdd's PDF / DOCX / PPTX flows are one-way (file →
markdown) and likely to stay that way. The docling-vs-pandoc
question is narrowly about **storage XHTML ↔ markdown**, not about
a grand unified theory of document conversion.

## Beyond technical fit

Pandoc and docling differ in non-technical ways that matter for a
multi-year investment:

| Axis | Pandoc | Docling |
|---|---|---|
| Age | ~20 years | ~1 year |
| Ecosystem | Wide — Quarto, panflute, Lua filters, 40+ formats | Narrow — single project, document understanding focus |
| Backing | John MacFarlane + community | IBM Research |
| API stability | `pandoc-api-version` versioned, decades of practice | Pre-1.0 churn likely |
| License | GPLv2 (binary; CLI use is clean) | MIT |
| Adjacent usage in our toolchain | Quarto (which `mdd new` already scaffolds) | None known |

The Quarto datum is a real signal: if Quarto is part of the wider
document toolchain around mdd (and it is — see `mdd new` and
the [templates directory](../../src/mdd/templates/)), then Pandoc is
already a load-bearing tool in the broader stack, not just an
imported library for this one feature.

This doesn't decide the question by itself — docling's "already in
mdd's transitive deps" is also real — but it weights the calculus
toward Pandoc on stability grounds.

## Prior art: how Quarto publishes to Confluence

[Quarto's Confluence publisher](https://quarto.org/docs/publishing/confluence.html)
is the closest existing system to what we'd build under option B. Its
architecture is worth studying for two reasons: it validates the
Pandoc + custom-Lua-writer shape in production, and it tells us
which prior decisions we *can't* borrow because the use cases
diverge.

### Architecture, in one paragraph

Quarto registers a Pandoc custom format
([`_extension.yml`](https://github.com/quarto-dev/quarto-cli/blob/main/src/resources/extensions/quarto/confluence/_extension.yml))
that points at a Lua writer
([`publish.lua`](https://github.com/quarto-dev/quarto-cli/blob/main/src/resources/extensions/quarto/confluence/publish.lua)).
The writer walks the Pandoc AST and emits Confluence Storage Format
XHTML directly. Macro templates (callouts, code blocks with CDATA,
images with `<ri:attachment>`, anchor macros) live in
[`overrides.lua`](https://github.com/quarto-dev/quarto-cli/blob/main/src/resources/extensions/quarto/confluence/overrides.lua).
TypeScript orchestrates the REST publishing — `confluence.ts`,
`confluence-helper.ts`, `api/`. Pandoc is invoked once per document
to drive the Lua writer; cross-document link resolution happens in
a second pass after page IDs are known.

This is **literally the architecture we sketched for option B**. The
Lua writer is ~200 lines of declarative CSF templates. It is not
hypothetical or experimental — it is production code shipping in
Quarto.

### What we can crib directly

- **CSF macro templates from `overrides.lua`.** Callouts (with the
  correct `ac:structured-macro` shape), code blocks with
  `<![CDATA[…]]>`, image macros with `ri:attachment` and sizing
  attributes, anchor macros for identifiers. These are the exact
  emitters our markdown→storage writer needs. Quarto solved them;
  we just have to read the file.
- **The Pandoc-custom-format pattern.** `output-ext: xml`, `writer:
  publish.lua`, `quarto-custom-format: confluence` in
  `_extension.yml` is a clean way to register a format with Pandoc
  without forking. We can do the same.
- **Two-pass publish for cross-doc links.** Pass 1 creates/updates
  pages and learns their server-assigned IDs; pass 2 rewrites
  source-format links to those URLs. Relevant when mdd does a
  whole-space sync where one new page links to another new page.
- **Filename ↔ page binding via a Confluence content property**
  (`ContentPropertyKey.fileName` in
  [`confluence-helper.ts`](https://github.com/quarto-dev/quarto-cli/blob/main/src/publish/confluence/confluence-helper.ts)).
  Quarto stores the source filename as a content property on the
  Confluence page itself, so identity tracking lives server-side
  rather than in local state. mdd uses frontmatter `page_id`
  today; the content-property approach is robust to local-state
  drift and worth comparing.

### Where Quarto offers no prior art

Quarto is **explicitly publish-only with last-writer-wins**. From
`confluence.ts:385` (`updateContent`):

```ts
const previousPage = await client.getContent(id);
…
const toUpdate: ContentUpdate = {
  id,
  version: getNextVersion(previousPage),   // monotonic ++
  title: uniqueTitle,
  body: updatedBody,                        // wholesale replacement
};
```

No diff, no etag check, no merge, no conflict UI. The Quarto docs
state plainly: *"edits to pages made in Confluence are overwritten
when content is published from Quarto."* On publish, Quarto sets
view-only restrictions to actively discourage UI edits.

This is the opposite stance from what we want. mdd's bidirectional
sync — the actual hard part — has no precedent in Quarto. The
`sync_diff.py` / `apply.py` / merge-engine design has to come from
elsewhere (or be invented). Specifically:

- No element-level identity tracking. Page version numbers only.
- No provenance map between markdown sources and storage elements.
- No round-trip via `body-format=export_view` or any other
  rendered-HTML pathway.
- No conflict resolution UX.

So the Quarto borrow is bounded: **the markdown→storage writer is
a copy-with-attribution exercise; the storage→markdown reader and
the merge engine are entirely ours.**

### Pitfalls Quarto's source flags for us

- **Hardcoded macro GUIDs** for callouts (`97c39328-9651-4c56-…`
  for tip, etc.). Fragile if Confluence ever validates them or if
  duplicates cause problems. We should generate fresh GUIDs per
  emission, or omit and let Confluence assign.
- **Callout name swap.** Quarto's `warning` macros emit Confluence's
  `note`; Quarto's `important` macros emit Confluence's `warning`.
  Visually surprising; if we map markdown callouts to Confluence
  macros, we should match Confluence's vocabulary, not Quarto's.
- **Raw HTML is silently dropped** (`publish.lua:104`,
  `return ""`). We should pass through `RawBlock format="confluence"`
  verbatim and warn (not drop) on `RawBlock format="html"` if it
  contains anything Confluence won't accept.
- **Math is unsupported.** If the content being published uses math,
  this is a gap to call out.
- **Delete and attachment-upload paths use `sleep()` for rate
  limiting.** Confluence has documented rate limits; respect them
  via retry/backoff (our existing `client.py` already does this).

### Net effect on option B

Option B's risk profile drops materially. We're not pioneering;
we're replicating a working pattern with a different update model.
Lua-writer expressiveness is no longer an open question — Quarto
proves it scales to the macro surface area we care about.

The merge engine remains the genuinely novel piece. That's where
the spike effort should concentrate.

## What we don't yet know

The cost of each option depends on several things we have not
measured:

1. **Fidelity.** How well does each approach round-trip the actual
   shapes of content that appear in real Confluence pages? Tables
   with merged cells? Nested lists with mixed item types? Code
   blocks with `ac:plain-text-body`? `{=confluence}` raw blocks the
   user has authored by hand?
2. **Provenance reliability.** Does `ac:local-id` / `ac:macro-id`
   actually survive a Confluence v2 PUT followed by re-fetch? Or
   does Confluence rewrite them? Without this, the identity story
   needs a different anchor.
3. **Macro coverage.** What macros actually appear in real
   Confluence content? Inventorying the top N by frequency tells us
   how many need first-class IR treatment vs. falling back to raw
   passthrough.
4. **Docling's actual writer quality.** Does
   `docling.export_to_markdown()` produce output we'd want to ship?
   Compare against the current `storage_to_md.py` output and
   Pandoc's `-t markdown` output.
5. **Lua-writer expressiveness.** Can a Lua writer for
   `confluence-storage` realistically handle the macro surface area,
   or does the Lua approach hit a wall on complex macros?

These are answerable empirically with small spikes.

## Proposed plan

Three discrete pieces of work, in order.

### Step 1 — Build a test corpus (this note's first sub-task)

We need representative Confluence content we can use as ground
truth — and that we can publish, share with maintainers of any
upstream tools, embed in unit tests, and discuss in open-source
context. Confidential content is not usable here.

Sub-tasks (separate research note will detail this):

- Identify content shapes that must be covered: nested lists,
  tables (simple + merged cells), code blocks (storage and
  fenced), callout macros (tip/info/note/warning/panel),
  `ac:link` to `ri:page` / `ri:url`, layout-section / layout-cell,
  unknown macros, attachments, math, emoticons, placeholders.
- Decide where the corpus lives: GitLab project repo
  (`mdd/test-corpus`?), separate GitHub repo, or in-tree under
  `tests/confluence/fixtures/`.
- Set up a Confluence Cloud free-tier instance for the project
  to host the corpus as live pages, so the corpus can be re-fetched
  and the round-trip tested against a real API. The free tier
  allows 10 users and unlimited pages — sufficient.
- Seed the instance with content shaped to exercise each item
  on the list. Where possible, copy public-domain or
  Creative-Commons-licensed source material (Wikipedia
  introduction sections render well as Confluence pages).
- Capture the storage XHTML, the export_view HTML, and the
  rendered HTML for each page as fixture data alongside the
  corpus definition.

Output: a research note `R07-confluence-test-corpus.md` that
specifies what's in it, where it lives, and how to regenerate it.

### Step 2 — Build an experiment harness

A small standalone tool that, given a Confluence page and a
candidate IR pipeline, measures:

- **Round-trip fidelity.** Convert storage XHTML → markdown →
  storage XHTML. Diff against the original. Score loss by category
  (text content, structure, attributes, whitespace).
- **Identity preservation.** Do macro IDs survive? Do paragraph
  positions remain matchable?
- **Provenance feasibility.** Can we produce a stable mapping
  from markdown blocks to storage elements? Does it survive
  user-style edits (insert paragraph, modify list, rename
  heading)?
- **Code surface.** Lines of code per pipeline. Number of
  edge-case branches.

Output: a small Python package, probably
`scripts/ir-experiment/` (one-off, not part of the production
tree). Doesn't need to be production-quality.

### Step 3 — Run three spikes

Each spike implements one of the three approaches against the
experiment harness and the test corpus:

1. **Spike A — status quo + provenance map.** Extend the current
   converters with a provenance-emitter and re-anchoring logic.
2. **Spike B — Pandoc pipeline.** Implement the Lua writer and
   Python-emits-pandoc-JSON reader. Use `pandoc` for the rest.
3. **Spike C — Docling pipeline.** Implement the
   `DoclingDocument` reader and writer. Pick an encoding for
   opaque-passthrough and document its limits.

Each spike outputs a numbered research note with measurements,
sample diffs, and an honest assessment of fit. The comparison
then writes itself.

Output: research notes `008` through `010`, plus a comparison
note `011` that distills findings into a recommendation.

### Step 4 — Decide and spec

Only after step 3. The decision goes into an implementation spec
(probably `028-confluence-bidirectional-sync.md`) that picks one
foundation and details the merge algorithm, conflict UX, cache
layout, and migration path.

## Files this work intersects with

Reading list when the spikes start, in rough order of importance:

- [`src/mdd/confluence/storage_to_md.py`](../../src/mdd/confluence/storage_to_md.py)
  — current XHTML → markdown converter; the Python parser logic
  is reusable in spikes B and C.
- [`src/mdd/confluence/md_to_storage.py`](../../src/mdd/confluence/md_to_storage.py)
  — current markdown → XHTML converter; gets replaced wholesale in
  spikes B and C.
- [`src/mdd/confluence/sync.py`](../../src/mdd/confluence/sync.py)
  — the orchestrator with the existing `LOCAL_PUSH` event class
  that any merge engine will plug into.
- [`src/mdd/confluence/state.py`](../../src/mdd/confluence/state.py)
  — `LocalPage` model; will need fields for cache pointers
  (storage hash, export_view hash, provenance path) when we
  ship.
- [`src/mdd/confluence/client.py`](../../src/mdd/confluence/client.py)
  — currently fetches `body-format=storage` only. Will need a
  method for `body-format=export_view` when we want rendered HTML
  for conflict UX.
- [`docs/spec/S14-confluence-sync.md`](../spec/S14-confluence-sync.md)
  — current sync semantics; "local + remote = skip" decision gets
  replaced by the merge engine.
- [`docs/spec/S26-managed-elsewhere.md`](../spec/S26-managed-elsewhere.md)
  — load-bearing on the push side; merge engine must respect it.
- [`docs/research/R01-confluence-renames.md`](R01-confluence-renames.md)
  through [`R05-managed-elsewhere.md`](R05-managed-elsewhere.md)
  — prior research, especially for context on what's already
  decided.

## Open questions before step 1 starts

1. ~~**Where does the Confluence Cloud test instance live?**~~
   **Resolved.** Free-tier instance at
   <https://markdown.atlassian.net/> with one space `MDD` at
   <https://markdown.atlassian.net/wiki/spaces/MDD/overview>,
   single user. The corpus mirror lives in a companion
   `mdd/test-confluence` git repository.
2. **Test corpus license.** Are we comfortable picking
   Creative-Commons-licensed source material and seeding it
   ourselves, or do we hand-author every fixture page? Implication
   for what goes in `mdd/test-confluence` — if upstream sources are
   CC-licensed, attribution + LICENSE files are mandatory; if
   hand-authored, we own the rights and can dual-license.
3. **What counts as "good enough fidelity"?** Pixel-perfect
   round-trip is unrealistic. Define the threshold before measuring
   so we don't shift goalposts. Candidate: zero text-content drift,
   zero macro-identity drift, ≤5% whitespace drift, no attribute
   loss on macros — to be refined in note 008 (experiment harness).
4. ~~**Lua maturity in the team.**~~ Partially answered: Quarto
   has been running a Pandoc Lua writer for Confluence in
   production for years, and the surface area is small (~200
   lines). Lua is a known commodity, not exotic. Still a fair
   question whether more than one person will touch it.
5. **Docling release cadence.** What's their stability story?
   When does the IR settle? Pin and adapt is the working
   assumption, but worth a look before betting on spike C's
   results.
