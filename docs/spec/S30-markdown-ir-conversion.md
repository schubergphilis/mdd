# 030 - Markdown ↔ IR conversion

**Purpose:** Map markdown to and from the document IR, with 100% flavour coverage and a documented fallback policy.

**Status:** Implemented (2026-05-13)

## Introduction

This spec maps the markdown flavour mdd uses (CommonMark + GFM tables + GFM
strikethrough + GFM autolinks + GFM task lists + fenced div extensions for
callouts) to and from the document IR defined in
[S28](S28-document-ir-foundation.md), with a documented fallback policy
for content outside that flavour.

This is the pair to [S29](S29-confluence-ir-conversion.md);
together they define the bidirectional Confluence ↔ markdown
conversion path. Normalization and whitespace preservation are
[S31](S31-ir-normalization-and-whitespace.md).

The markdown surface is deliberately clean (no `data-mdd-*`
attribute leakage, no HTML comment trails) because the markdown
file is what humans read.

## Design Approach

## Module layout

```
src/mdd/markdown/ir/
  __init__.py
  reader.py          # parse_markdown(str) -> Document
  writer.py          # render_markdown(Document) -> str
  flavour.py         # configured markdown-it-py extension set
  callouts.py        # ::: fenced-div ↔ Callout
  confluence_uris.py # confluence-page: / confluence-attachment: URIs
  inline_macros.py   # {{confluence:...}} inline marker handling
  fallback.py        # passthrough (HTML, ``` confluence-xml fences)
```

`reader.py` and `writer.py` are the public entry points. Everything
else is internal.

## Markdown flavour

The IR targets the markdown shape mdd already writes today. The
parser is `markdown-it-py` configured with:

| Extension | Purpose |
|---|---|
| `commonmark` core | Paragraphs, headings, lists, code blocks, blockquote, links, images, emphasis, hard/soft breaks. |
| `table` (GFM) | GFM pipe tables; alignment row maps to `Table.align`. |
| `strikethrough` (GFM) | `~~text~~` → `Strikethrough`. |
| `linkify` (GFM autolinks) | Bare URLs become `Link`. |
| `tasklists` | `[ ]` / `[x]` checkboxes on list items → `ListItem.task: Literal["open", "done"] \| None`. |
| Custom `fenced_div` | `:::callout-tip` … `:::` blocks → `Callout`. |
| Custom `confluence_inline_macro` | `{{confluence:name key="value"}}` → `InlineMacro`. |
| Custom `confluence_fence` | ` ```confluence-xml ` → `RawBlock(format="confluence-storage")`. |

The fenced div and inline macro extensions are mdd's own
mini-plugins (~50 LOC each). They are how Confluence-specific
shapes ride through the markdown layer without polluting the
prose with raw HTML or attribute syntax.

### Synthetic URIs for Confluence link family

`ConfluenceLink` round-trips through markdown as a regular `Link`
with a synthetic URI scheme:

| `target_kind` | URI shape |
|---|---|
| `page` | `confluence-page:<space>/<title>` (space optional for same-space) |
| `attachment` | `confluence-attachment:<filename>` |
| `url` | the URL itself (no scheme prefix) |
| `user` | `confluence-user:<accountId>` |
| `blogpost` | `confluence-blogpost:<space>/<title>` |
| `shortcut` | `confluence-shortcut:<key>/<target>` |

The reader recognises these URIs in `Link.target` and converts
them back to `ConfluenceLink` at parse time. This keeps the
markdown human-readable without HTML comments or sidecar
attributes leaking into the prose.

`ConfluenceImage` follows the same pattern with
`confluence-attachment:` URIs in `Image.target` and width/height/
alignment encoded in the standard markdown image title slot:
`![alt](confluence-attachment:diagram.png "width=400 align=center")`.

The full `attributes` set (everything captured by the storage reader
in source order, including `ac:layout`, `ac:original-height`,
`ac:original-width`, `ac:custom-width`, `ac:local-id`, …) is ALSO
encoded in the URI as a semicolon-delimited extras list — e.g.
`confluence-attachment:diagram.png;align=left;layout=align-start;local-id=…;width=320`.
The title slot carries a subset for human readability; the URI
extras list is the round-trip authority. Both lists emit in
dict-insertion order so the original Confluence attribute ordering
round-trips byte-perfect.

**Bare user mention shape.** A `<ac:link><ri:user/></ac:link>` with
no `<ac:link-body>` round-trips as `[](confluence-user:<accountId>)`
— empty link text, not the account-id as text. The earlier fallback
("text = target when body is empty") collided with self-titled links
on round-trip: a parsed-back `[X](confluence-user:X)` is
indistinguishable from an explicit `<ac:link-body>X</ac:link-body>`.
The empty-text form is the unambiguous representation.

**Attachment URI handling on update.** The `mdd confluence update-page`
attachment scanner normalises `confluence-attachment:<filename>` URIs
before resolving them on disk: it strips the scheme prefix,
percent-decodes the filename, drops the markdown title slot, and
strips `;key=value` extras. Bare filenames are resolved against the
sibling `<page>-attachments/` directory (the layout `export-page`
writes) and fall back to the markdown's own directory for legacy
refs.

### Layout fenced divs

`Layout` / `LayoutSection` / `LayoutCell` round-trip as nested fenced
divs using ascending colon-fence widths so each level closes
unambiguously:

| Node | Open fence | Close fence | Info string |
|---|---|---|---|
| `Layout` | `:::layout` | `:::` | (none) |
| `LayoutSection` | `::::layout-section` | `::::` | `layout_type="<type>"` |
| `LayoutCell` | `:::::layout-cell` | `:::::` | (none) |

The `LayoutSection` info string uses bare ``key="value"`` syntax (no
``{}`` wrapper) — distinct from callout / confluence-macro
attributes — and currently carries only `layout_type`. The writer
emits a blank line immediately after the cell's opening fence and
before the cell's closing fence so the inner block content does not
lazily absorb the closing fence as paragraph continuation. Example:

```markdown
:::layout
::::layout-section layout_type="two_equal"
:::::layout-cell

Left column content.

:::::
:::::layout-cell

- Right column
- bullet list

:::::
::::
:::
```

The reader parses this token stream into the corresponding `Layout`
IR; arbitrary block content (headings, lists, tables, callouts,
nested macros) is permitted inside any `LayoutCell`.

#### Depth-aware fence counts for nested containers

The colon counts above (`:::` / `::::` / `:::::`) are the **fence
counts at the corresponding nesting depth**, not hard-coded to the
container type. Every container (Layout, LayoutSection, LayoutCell,
Callout, ConfluenceMacro) emits `3 + nesting_depth` colons and
passes `nesting_depth + 1` to its child containers. So a `Callout`
that lives at the top level uses 3 colons; the same `Callout`
nested inside `:::::layout-cell` (depth 2) uses 6 colons
(`::::::callout-tip` …).

Strict colon-count nesting makes the reader's same-count close
matching unambiguous: a 6-colon close cannot terminate a 3-colon
open. Without depth-aware counts, a `:::callout-tip` inside a
`:::::layout-cell` would terminate the outermost `:::layout` first
— the cell's body would then escape the layout entirely and
trailing close fences would leak into the next sibling as literal
`<p>:::::</p>` text.

#### Block-level inline shape

A standalone `<ac:link>` or `<ac:image>` (direct child of a
container, no `<p>` wrapper in the source) sets
`block_level=True` on the IR node (see [S29 §"Block-level inline
hint"](S29-confluence-ir-conversion.md)). The markdown leg does not
carry this flag; the storage round-trip relies on reattach grafting
it back from the cached source IR. New block-level inlines authored
in markdown (e.g. by leaving an image on its own line inside a
layout cell) acquire `block_level=True` only when re-imported from
storage.

## Implementation Notes

## Reader behaviour

`parse_markdown(md: str) -> Document`

- Parses with `markdown-it-py` plus the extensions above.
- Walks the token stream into IR nodes via a small
  `Stack`-based builder (matches the spike).
- Assigns `node_id` depth-first across the whole document.
- Synthetic-URI `Link` and `Image` nodes are post-processed in
  `confluence_uris.py` into `ConfluenceLink` / `ConfluenceImage`.
- Inline macro markers `{{confluence:name k="v"}}` are
  post-processed into `InlineMacro`.
- Fenced divs `:::callout-<kind>` are translated to `Callout`
  during the walk.
- Nested fenced divs `:::layout` / `::::layout-section` /
  `:::::layout-cell` are translated to `Layout` / `LayoutSection`
  / `LayoutCell` (see *Layout fenced divs* above).
- `attributes` are *not* populated from markdown (markdown has no
  identity surface). They come from the cached IR via `reattach()`
  when the round-trip leg fires. Typed semantic fields (`compact`,
  `omit_start`, `no_wrapper`, `body_leading_ws`, `body_trailing_ws`,
  `block_level`) are also restored by `reattach()`.

### Fallback policy

For any markdown construct outside the supported flavour, the
reader:

1. Inline HTML → `RawInline(format="html", content=<verbatim>)`.
2. Block HTML → `RawBlock(format="html", content=<verbatim>)`.
3. ` ```confluence-xml ` fences → `RawBlock(format="confluence-storage", content=<verbatim>)`.
4. Unknown fence info → `CodeBlock(language=<info>, content=...)`
   (markdown's own "fall back to a code block" semantics).
5. Records a `FallbackEmitted` event on the parse context. Calling
   code can inspect `document.fallbacks` after parse.

The reader does **not** silently drop content. Anything markdown-it
cannot parse becomes a `RawBlock(format="markdown", content=<raw>)`
covering the unparseable byte range; the writer round-trips it
verbatim.

## Writer behaviour

`render_markdown(doc: Document) -> str`

- Walks the IR depth-first, emitting markdown strings.
- Default mode is **normalising** — paragraph wrapping, list-item
  spacing, and code-fence style follow project conventions (see
  [S31](S31-ir-normalization-and-whitespace.md)). Whitespace-
  preserving mode is opt-in via a flag.
- Tables emit GFM pipe tables with column widths computed from
  cell content. Header alignment row reflects `Table.align`.
  Tables with merged cells (`colspan` / `rowspan` > 1) cannot be
  expressed in pipe-table syntax: the writer falls back to a
  block-HTML `<table>` with the `RawBlock(format="html", ...)`
  shape, preserving content and surfacing the limitation.
- `Callout` blocks emit fenced-div syntax (`:::callout-tip`, with
  matching `:::` close). Title becomes the first heading inside
  the div when present.
- `ConfluenceLink` / `ConfluenceImage` / `InlineMacro` emit the
  synthetic URI / marker shapes documented above.
- `ConfluenceMacro` (the generic carrier) emits a
  `:::confluence-macro {name="..." key="value" ...}` fenced div, using
  the same nesting-depth-aware colon-count scheme as `Callout` / `Layout`
  (see "Depth-aware fence counts" above). The macro's parameters (plus
  `name`) go in the info string; the body is nested block content when
  `rich_body` is set, or emitted as verbatim lines otherwise.
- `RawBlock(format="markdown", ...)` emits its content verbatim.
- `RawBlock(format="confluence-storage", ...)` — and any other
  `RawBlock` format the writer does not otherwise recognise — emits a
  ` ```confluence-xml ` fence around the raw content. Round-trip through
  the markdown leg is lossless because the fence content is verbatim.
- `RawBlock(format="html", ...)` emits the raw HTML verbatim
  (CommonMark-compatible).
- `attributes` are **not** emitted into markdown. They are
  invisible to the human reader and survive the round-trip via
  the reattach step (see [S28](S28-document-ir-foundation.md)
  §"Reattach"). This is the design choice that keeps markdown
  diffs clean.

### Empty paragraphs with identity

Confluence's WYSIWYG editor records the cursor position below the
last block of content as an empty `<p local-id="…" />` in the page
body. These trailing anchors carry an identity but have no visible
content — they're the click-target for "place cursor at end of
page".

Markdown has no syntax for an empty paragraph with an identity
attribute. We do **not** invent one (e.g. an HTML-comment marker or
a no-body `:::anchor` fence) because:

1. The anchor has no rendering effect — Confluence's own renderer
   collapses trailing empty paragraphs. Persisting it through
   markdown costs reader-clarity for no observable benefit.
2. Comments/reactions attached to an empty trailing anchor are
   rare in practice (the editor rarely places content references
   on the zero-height "click below" target).
3. Adding an mdd-specific marker would either show up in human-
   edited markdown (noise) or get stripped by other markdown
   tooling (silent loss anyway).

The implication is a small documented trade-off in the
[S33](S33-ir-roundtrip-testing-and-benchmarks.md) §"R3" gate:
the markdown leg does **not** preserve empty-paragraph identity
anchors. For corpus fixtures that incidentally exhibit this shape
(Confluence-first pages where the author left the cursor at the
end of the page when saving), the fix is to strip the anchor at
the source — push a corrected storage shape via `mdd confluence
update` (or a direct API PUT for confluence-first fixtures whose
markdown form can't round-trip the macros they contain) and
refresh the snapshot. We have used this approach for fixtures
131332 and 164060.

Empty paragraphs *without* identity are dropped at parse time by
the `drop_empty_paragraphs` normalisation pass — there is no
positional information to preserve. See
[S31](S31-ir-normalization-and-whitespace.md) for the pass
list.

## 100% markdown coverage

"100% coverage" in the user's brief means: every construct
expressible in the configured flavour parses, every IR node a
writer can produce renders, and round-trip through
`parse_markdown(render_markdown(doc))` is structurally identical
(modulo whitespace, see [S31](S31-ir-normalization-and-whitespace.md)).

The corpus expansion in
[S32](S32-ir-test-corpus-expansion.md) covers every
construct from the
[CommonMark 0.31 spec](https://spec.commonmark.org/0.31.2/) plus
the GFM additions plus the project-specific extensions. Each
construct is one fixture; round-trip is gated by the harness in
[S33](S33-ir-roundtrip-testing-and-benchmarks.md).

## Backwards compatibility

The existing `mdd convert` markdown writer path (used by docx /
pptx / pdf flows) is not affected. Those converters target
markdown directly via Docling / python-docx / python-pptx, not via
the IR. The IR is for *bidirectional* document conversion (today:
Confluence). Migrating other formats to the IR is a follow-up.

## Related upstream specs

- [028-document-ir-foundation](S28-document-ir-foundation.md) — document IR this spec maps to/from
- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — the paired Confluence ↔ IR conversion spec
- [031-ir-normalization-and-whitespace](S31-ir-normalization-and-whitespace.md) — normalization and whitespace preservation
- [032-ir-test-corpus-expansion](S32-ir-test-corpus-expansion.md) — per-construct test fixtures
- [033-ir-roundtrip-testing-and-benchmarks](S33-ir-roundtrip-testing-and-benchmarks.md) — round-trip test harness
