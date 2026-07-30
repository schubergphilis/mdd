# What "near-lossless" actually means

The README promises "near-lossless roundtrips" between Markdown in git and
Confluence. Here is what that looks like on a real page. The fragment below is
Confluence's storage XHTML for a macro that `mdd` does not recognize, taken
from a captured test page committed at
`tests/corpus/confluence/_snapshots/1147246/storage.xhtml`:

```xml
<ac:structured-macro ac:name="bogus-macro" ac:schema-version="1" ac:macro-id="4aee64f4-1892-4aa9-addd-7bb4fa941c7f"><ac:parameter ac:name="alpha">one</ac:parameter><ac:parameter ac:name="beta">two</ac:parameter><ac:rich-text-body>
    <p>The body is rich text inside an unrecognised macro. The
    reader does not introspect the children; the writer
    re-emits them byte-for-byte from the captured Origin.</p>
  </ac:rich-text-body></ac:structured-macro>
```

When `mdd` pulls that page, this is the Markdown it writes:

```markdown
:::confluence-macro {alpha="one" beta="two" name="bogus-macro"}
The body is rich text inside an unrecognised macro. The
    reader does not introspect the children; the writer
    re-emits them byte-for-byte from the captured Origin.

:::
```

(The page text describes itself; it is a test fixture.) Notice what
the Markdown does not contain: the `ac:macro-id` GUID and
`ac:schema-version="1"` are gone, because Markdown has no place to put them.
And yet, when you push the file back unedited, the storage `mdd` reconstructs
is the first block again, byte for byte, GUID included — the diff comes out
empty and no update is sent. A CI gate asserts exactly that round trip,
storage to Markdown and back, for every one of the 82 captured pages in the
corpus ([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)).

That example carries the whole promise: **unmodified content round-trips
without loss; edited content and a documented list of constructs do not, and
the "near" is that list.** The rest of this article walks the list. For the
story of why the machinery underneath exists at all, read
[why mdd has its own IR](why-mdd-has-its-own-ir.md).

## Why "lossless" is not on the table

Confluence stores a page as namespaced XHTML in which macros, layout cells,
and links carry identity attributes — `ac:local-id`, `ac:macro-id`,
`ac:schema-version` — that Confluence itself needs back
([S28](../spec/S28-document-ir-foundation.md)). Markdown has nowhere to hold
them, and `mdd` refuses to invent a place — no `data-mdd-*` attributes, no
HTML comment trails — because the Markdown file is what humans read and edit
([S30](../spec/S30-markdown-ir-conversion.md)). Every converter faces this
fork: pollute the Markdown with metadata, or carry the metadata somewhere
else. `mdd` carries it somewhere else, and "near-lossless" is the measured
result of that choice.

## What survives, and by what mechanism

Three mechanisms produced the example above.

**Nothing is dropped silently.** A reader that meets a shape it does not
recognize must keep the source rather than discard it; the fallback contract
states this as "MUST NOT silently drop content"
([S28](../spec/S28-document-ir-foundation.md)). That is why the bogus macro
became a `:::confluence-macro` block instead of vanishing: its parameters and
body ride through opaquely, present in the file and visible in every diff.
Storage constructs with no macro shape at all surface as a fenced code block
tagged `confluence-xml` with the raw XHTML inside. Every fallback also raises
an event, and CI fails when one fires on a fixture not explicitly tagged as a
fallback case ([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)) —
falling back is allowed; falling back unexpectedly is a build failure.

**Identity is grafted back.** Since the Markdown leg drops identity
attributes, the push path re-fetches the remote storage, parses it, and
reattaches the cached tree's identity attributes and reader-only fields onto
the tree parsed from your Markdown — "fresh wins, cached fills"
([S28](../spec/S28-document-ir-foundation.md)). That is where the GUID in the
example comes from. This is production behavior, not a test-harness trick:
`mdd confluence update-page` reuses the storage it already fetched for the
diff display, and an integration test asserts that pushing an unedited export
issues no PUT at all
([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)). An earlier design
kept the cached tree in a `<page>.confluence.json` sidecar next to each file;
the sidecar was retired because page metadata already lives in the Markdown's
frontmatter and the lookup happens in-process from the fetched storage
([S31](../spec/S31-ir-normalization-and-whitespace.md)).

**Source form is recorded.** In preserving mode every node carries an
`Origin`: the exact source bytes, the surrounding whitespace, and the entity
form of each character ([S31](../spec/S31-ir-normalization-and-whitespace.md)).
A page that spells `…` as `&hellip;` gets its `&hellip;` back instead of a
normalized Unicode character, and a CDATA section keeps its trailing newline.

## What is known not to survive

The carve-outs are written down, and each one is a decision with a rejected
alternative behind it.

- **Backslash escapes.** Write `\*` in Markdown and the round-tripped file
  comes back with a plain `*` — storage holds the literal character, and
  restoring the backslash needs a context-sensitive re-escape policy that is
  deferred ([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)).
  Fixtures exercising this are expected failures on the byte-perfect gate.
- **Empty paragraphs carrying an anchor id.** Confluence's editor records the
  cursor position as a trailing empty `<p>` with a `local-id`; after a round
  trip, that invisible paragraph is gone. `mdd` considered and rejected
  inventing Markdown syntax for it, because an HTML-comment marker or an empty
  fence would either be noise in human-edited files or get stripped by other
  Markdown tooling — a silent loss anyway
  ([S30](../spec/S30-markdown-ir-conversion.md)). Corpus pages that exhibited
  the shape were corrected at the source instead of taught to the converter.
- **Inline `<kbd>` and `<samp>`.** Wrap a key name in `<kbd>` and the tags
  disappear, leaving the text behind: an allowlist gap in the Markdown
  reader's raw-HTML handling
  ([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)).
- **Text nodes over 256 KiB.** Recorded source bytes are capped per node;
  past the cap the writer falls back to its canonical render, so a huge
  embedded blob may come back reformatted
  ([S31](../spec/S31-ir-normalization-and-whitespace.md)). The alternative —
  unbounded source capture — could turn a 5 MB page into a ~10 MB tree, and
  graceful degradation on that long tail won.
- **Merged-cell tables in the Markdown surface.** A table with `colspan` or
  `rowspan` shows up in your file as a raw HTML `<table>`, not a pipe table,
  because pipe syntax cannot express the merge
  ([S30](../spec/S30-markdown-ir-conversion.md)). Content survives; the clean
  Markdown surface does not.
- **Origin across structural edits.** Split a paragraph in two and the second
  half's recorded source form is meaningless, so the edited page re-renders
  canonically — entities normalized, whitespace canonical — rather than
  replaying stale bytes
  ([S31](../spec/S31-ir-normalization-and-whitespace.md)).

Separately, some page aspects are outside the model entirely rather than lossy
within it: comments, page restrictions, and page properties are not synced,
and labels are read but not pushed back. The
[concepts page](../guide/03-concepts.md) lists these, and
[Safety](../guide/04-safety.md) covers what they mean for a push.

## Losing things on purpose

One class of loss is a feature. The converter runs in two modes: a preserving
mode used internally on the push leg so Confluence sees its own bytes back,
and a default normalizing mode for the files written to disk, which collapses
soft breaks, drops empty paragraphs, converts `&hellip;` to `…`, and trims
redundant attributes ([S31](../spec/S31-ir-normalization-and-whitespace.md)).
The goals conflict — a byte-faithful export is full of entity clutter and
trailing blank paragraphs no human wants to read — and the spec's answer is
that a single mode cannot serve both. When someone says the Markdown on disk
is not byte-identical to what a raw export would give: correct, and
intentional.

## Attachments are a different promise

None of the above applies to attachments. On pull, `mdd` downloads the binary
and, for Office formats and PDF, writes a converted `.md` sibling next to it
([S16](../spec/S16-confluence-attachment-conversion.md)). The binary is the
fidelity copy; the sibling is a convenience for grep and diff in the mirror,
and page links keep pointing at the binary. The research behind the Office
story is blunt about the direction of truth: renders between Markdown and
`.docx` are one-way authoritative, and the design never claims a byte-stable
round trip for them — divergence is detected and surfaced to a human instead
of merged ([R02](../research/R02-attachments.md)).

## Where the claim came from, and how it is defended

"Near-lossless" started as a measurement, not a slogan. In May 2026 four
candidate pipelines ran against a 35-fixture corpus; the comparison note first
recommended pandoc with a Lua writer, then reversed itself when a pure-Python
spike beat pandoc on every fidelity metric
([R12](../research/R12-confluence-ir-comparison.md)). The sibling article
[why mdd has its own IR](why-mdd-has-its-own-ir.md) tells that story.
The fidelity percentages from those spikes are history now, superseded by the
binary gate the example at the top demonstrates.

What holds today: the corpus has grown to 82 captured Confluence pages plus
Markdown-first fixtures for every CommonMark 0.31 construct, the GFM
additions, and each mdd extension
([S32](../spec/S32-ir-test-corpus-expansion.md)). The byte-perfect gate for
preserving mode and similarity floors for normalizing mode run on every
commit, and locally: `mise run ir-roundtrip` runs the round-trip suites,
`mise run ir-coverage` writes the coverage matrix to `build/ir-coverage.json`,
and both run inside `mise run ci`.

The discipline around the gates has two properties worth knowing. Known
failures are quarantined, not tolerated: a page that stops round-tripping gets
a reproducer snapshot in a strict expected-failure tier
(`tests/corpus/confluence/_xfail_snapshots/`), so the moment a fix lands the
test unexpectedly passes, CI fails, and the snapshot must move into the main
byte-perfect gate. That tier is empty at the time of writing. And thresholds
only ratchet one way: if a benchmark gate flakes, the documented response is
to raise the ceiling, never to disable the gate
([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)). One gate was
dropped rather than ratcheted — a hard limit keeping the JSON form of the
parsed tree within 10× of the source size could not be made meaningful on
small fixtures, where structural overhead produces ~30× ratios on 200-byte
pages, so it was demoted to a design goal reviewers eyeball during corpus
growth.

The conversion pipeline did not become the default on green tests alone:
promotion required the gates green for two consecutive weeks, a whole-space
sync round-tripping clean against a live tenant, and a two-week A/B against
the legacy converters with zero unexpected diffs
([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)). That is the
standard "near-lossless" is held to, and the reason the word "near" comes with
a list instead of a shrug.
