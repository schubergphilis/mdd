# 028 - Document Intermediate Representation (foundation)

**Purpose:** Typed, in-process Python IR for documents supporting bidirectional Confluence ↔ markdown sync with identity, provenance, and JSON serialization.

**Status:** Implemented (2026-05-13)

## Introduction

This spec is the foundation for specs
[029](S29-confluence-ir-conversion.md) (Confluence converters),
[030](S30-markdown-ir-conversion.md) (markdown converters),
[031](S31-ir-normalization-and-whitespace.md) (normalization +
whitespace preservation),
[032](S32-ir-test-corpus-expansion.md) (test corpus expansion), and
[033](S33-ir-roundtrip-testing-and-benchmarks.md) (roundtrip
testing).

The IR is a pure-Python tree of typed dataclasses with stable
node identity, optional source provenance (`Origin`), and a
versioned JSON serialization. It exists because the previous
direct Confluence-storage ↔ markdown converter pair could not
provide byte-perfect round-tripping or first-class identity for
diff / merge tooling.

## Requirements

- The IR node hierarchy (block + inline tiers).
- A single `attributes: dict[str, str]` per node carrying all XML/HTML
  attributes in source order, plus typed fields for semantic data
  (child-element data, internal whitespace/rendering markers).
- JSON serialization with a versioned schema.
- The public Python API: `parse_*`, `render_*`, `Document`,
  `to_json`, `from_json`, `reattach`.
- The `RawBlock` / `RawInline` fallback contract (mechanics — the
  fallback *policy* per format lives in
  [S29](S29-confluence-ir-conversion.md) and
  [S30](S30-markdown-ir-conversion.md)).

## Design Approach

- Two tiers — block nodes form the tree; inline tokens are the leaves
  inside text-bearing blocks. All nodes are `@dataclass(frozen=True)`
  to make `from_json(to_json(ir)) == ir` a real invariant.
- `RawBlock` and `RawInline` are the universal escape hatch for
  unrecognised shapes; readers MUST NOT silently drop content.
- `to_json` / `from_json` satisfy round-trip equality, schema
  versioning, stable key order, and human-readable formatting (two-space
  indent, `ensure_ascii=False`).
- `identity.reattach()` grafts `node_id`, missing `attributes` keys, and
  reader-only typed fields (`origin`, `trailing_ws`) from a cached tree
  onto a freshly-parsed tree, keeping unmodified content byte-identical
  across a round-trip.
- The package lives at `src/mdd/ir/` (not under `confluence/`) because
  it is a cross-cutting representation; both `mdd.confluence.*` and
  `mdd.markdown.*` depend on `mdd.ir`.

## Implementation Notes

- All block nodes carry `node_id`, `attributes`, and typed semantic
  fields; addressable inline tokens (`ConfluenceLink`, `ConfluenceImage`,
  `InlineMacro`) carry `attributes` and typed fields too.
- `attributes: dict[str, str]` is populated by the reader from the
  source element's attributes in source order (lxml preserves source
  order). The writer emits it in dict-insertion order, preserving
  source attribute ordering byte-perfect on the round-trip.
- `reattach()` grafts cached `attributes` keys onto fresh when fresh
  lacks them ("fresh wins, cached fills"). Identity keys
  (`ac:local-id`, `ac:macro-id`, `ac:schema-version`) survive this way
  because the markdown leg drops them, so fresh has nothing to "win" with
  and cached fills the slot. ``ConfluenceImage`` is the exception:
  its ``ac:local-id`` round-trips through the URI scheme so the fresh
  side already carries it (and the writer emits it in source position,
  not at a fixed slot).
- Top-level JSON dict has `mdd_ir_version: int` (currently `1`);
  loaders refuse unknown major versions with a clear error.
- The pure-Python IR pipeline lives in `src/mdd/ir/` with: module
  split, promoted `RawBlock`/`RawInline` contract, `FallbackEmitted`
  event, and locked JSON schema.

## Why a typed IR

`storage_to_md.py` and `md_to_storage.py` share no vocabulary;
every Confluence shape is encoded twice, once per direction, with
`{=confluence}` fenced raw blocks as the only escape hatch. Merge,
provenance, identity tracking, and a third format (eventually
`.docx`, `.pptx`, `.html`) all share the same root cause: there is
no representation either converter can attach metadata *to*.

A typed IR fixes this once. Every node has identity, every node
serialises to JSON losslessly, and every direction-specific
converter is a thin walker over a shared shape.

## Module layout

```
src/mdd/ir/
  __init__.py        # public API surface
  nodes.py           # block + inline dataclasses
  document.py        # Document container; metadata; iteration helpers
  identity.py        # reattach() and provenance/identity helpers
  serialize.py       # to_json / from_json + schema version
  fallback.py        # RawBlock / RawInline helpers
  errors.py          # IRError, FallbackEmitted, ValidationError
```

The package lives at `src/mdd/ir/` (not under `confluence/`)
because it is a cross-cutting representation. `mdd.confluence.*`
and `mdd.markdown.*` (new — see [S30](S30-markdown-ir-conversion.md))
both depend on `mdd.ir`.

## Node model

Two tiers — block nodes form the tree; inline tokens are the leaves
inside text-bearing blocks. All nodes are `@dataclass(frozen=True)`
to make `from_json(to_json(ir)) == ir` a real invariant.

### Block nodes

| Node | Notes |
|------|-------|
| `Paragraph(inlines: list[Inline])` | The most common block. |
| `Heading(level: int, inlines: list[Inline])` | `level ∈ {1..6}`. |
| `BulletList(items: list[ListItem], tight: bool)` | `tight` controls blank-line rendering. |
| `OrderedList(items: list[ListItem], start: int, tight: bool)` | `start` preserved verbatim — see [S31](S31-ir-normalization-and-whitespace.md). |
| `ListItem(blocks: list[Block])` | Always block-tier children, even for one-line items. |
| `BlockQuote(blocks: list[Block])` | Nests arbitrarily. |
| `CodeBlock(language: str | None, content: str, info: str | None)` | `info` preserves the raw fence info string. |
| `Table(header: TableRow | None, rows: list[TableRow], align: list[Align])` | Header is optional. `align` covers `default`/`left`/`right`/`center`. |
| `TableRow(cells: list[TableCell])` | |
| `TableCell(blocks: list[Block], colspan: int, rowspan: int)` | Merged cells supported natively (see [S29](S29-confluence-ir-conversion.md)). |
| `HorizontalRule()` | |
| `Callout(kind: Literal["tip","info","note","warning","panel"], title: str | None, blocks: list[Block])` | The canonical structural macro. |
| `ConfluenceMacro(name: str, params: dict[str,str], rich_body: bool, body: list[Block], plain_body: str \| None, attributes: dict[str,str])` | Generic carrier for non-callout structural macros. |
| `Layout(sections: list[LayoutSection])` | |
| `LayoutSection(layout_type: str, cells: list[LayoutCell])` | |
| `LayoutCell(blocks: list[Block])` | |
| `RawBlock(format: str, content: str)` | Fallback. See "Fallback contract". |

### Inline tokens

| Token | Notes |
|------|-------|
| `Text(content: str)` | Plain text leaf. |
| `Strong(inline: list[Inline])` | |
| `Emph(inline: list[Inline])` | |
| `Code(content: str)` | Inline code. |
| `Strikethrough(inline: list[Inline])` | GFM. |
| `Link(target: str, title: str \| None, inline: list[Inline])` | Plain markdown link. |
| `Image(target: str, title: str \| None, alt: str)` | |
| `LineBreak()` | Hard break. |
| `SoftBreak()` | Source line wrap inside a paragraph. |
| `ConfluenceLink(target_kind: Literal["page","attachment","blogpost","url","anchor","user","shortcut"], target: str, body_tokens: list[Inline], block_level: bool, space_key: str, version_at_save: str, posting_day: str, page_title: str, page_space_key: str, user_local_id: str, attributes: dict[str,str])` | `<ac:link>` family. Typed fields hold child-element data (`<ri:page>` / `<ri:attachment>` / `<ri:user>` …); `attributes` carries source-order `<ac:link>` attributes. |
| `ConfluenceImage(source_kind: Literal["attachment","url"], source: str, block_level: bool, attachment_version: str \| None, attributes: dict[str,str])` | `<ac:image>` with `<ri:attachment>` or `<ri:url>` child. `attachment_version` holds `ri:version-at-save`. |
| `InlineMacro(name: str, params: dict[str,str])` | `<ac:structured-macro>` used inline (status, mention, …). |
| `Emoticon(name: str)` | `<ac:emoticon>`. |
| `Placeholder(content: str)` | `<ac:placeholder>`. |
| `RawInline(format: str, content: str)` | Fallback. See "Fallback contract". |

### Identity and provenance fields

Every addressable node carries:

- `node_id: str` — provenance label assigned depth-first on parse
  as `b00001`, `b00002`, …. Stable across one round-trip on
  unmodified content via `identity.reattach()` (see below).
- `attributes: dict[str, str]` — all XML/HTML attributes on the
  source element, in source order (lxml preserves order). Carries
  both Confluence identity attributes (`ac:macro-id`, `ac:local-id`,
  `ac:schema-version`) and passthrough HTML attributes (`style`,
  `class`, `data-*`, etc.). The writer emits it in dict-insertion
  order, so source attribute ordering round-trips byte-perfect.
  Empty for nodes that carry no attributes.

In addition, node classes that hold **child-element data** or
**internal rendering markers** promote these to typed fields
rather than magic-string keys in `attributes`:

| Node | Typed field | Replaces |
|---|---|---|
| `OrderedList` | `omit_start: bool = False` | `attrs["_no_start"]` |
| `BulletList`, `OrderedList` | `compact: bool = False` | `attrs["_compact"]` |
| `CodeBlock` | `no_wrapper: bool = False` | `attrs["_no_code_wrapper"]` |
| `Callout`, `ConfluenceMacro` | `body_leading_ws: str = ""` | `attrs["_body_leading_ws"]` |
| `Callout`, `ConfluenceMacro` | `body_trailing_ws: str = ""` | `attrs["_body_trailing_ws"]` |
| every block class | `trailing_ws: str \| None = None` | `attrs["_trailing_ws"]` — inter-block whitespace captured from the source. `None` means "not captured, writer falls back to `\n`"; `""` is a meaningful captured value ("no whitespace between blocks"). |
| `ConfluenceImage` | `attachment_version: str \| None = None` | `extras["version-at-save"]` |
| `ConfluenceLink` | `space_key`, `version_at_save`, `posting_day`, `page_title`, `page_space_key`, `user_local_id` | `extras["space-key"]` etc. |

The `block_level: bool` field on `ConfluenceLink` and
`ConfluenceImage` (set by the storage reader when the element
appears as a direct child of a block container) was already a
typed field and is unchanged.

`Text`, `Strong`, `Emph`, `Code` carry no `attributes` field —
they have no Confluence-side identity worth preserving.

The reattach mechanism grafts every cached `attributes` key absent
from the fresh node — fresh wins if it carries a value, cached fills
in what's missing (`_merge_attributes_onto` in `mdd.ir.identity`).
This recovers Confluence identity (`ac:local-id`, `ac:macro-id`,
`ac:schema-version`) and passthrough HTML attrs (`style`, `class`,
`data-*`) that the markdown leg drops. `ConfluenceImage` is a special
case: its `ac:local-id` round-trips through the markdown URI scheme,
so the fresh side carries it in the right source-order position and
no graft is needed.

## Fallback contract

`RawBlock` and `RawInline` are the universal escape hatch. Each
carries a `format` tag (string) and an opaque `content` string. The
contract for converters:

- **Reader-side:** when the reader encounters a shape it does not
  recognise, it MUST emit `RawBlock` / `RawInline` with `format` set
  to the source format (`"xhtml"`, `"html"`, `"markdown"`,
  `"confluence-storage"`, …) and `content` set to the verbatim
  source bytes (UTF-8). It MUST NOT silently drop content.
  Optionally, the reader emits a structured `FallbackEmitted` event
  on a `IRContext` that callers can use to log / surface what fell
  through.
- **Writer-side:** when the writer encounters a `RawBlock` /
  `RawInline` whose `format` it understands, it MUST emit the
  content verbatim. When `format` does not match the writer's
  target, the writer MUST emit a clean visible surface (markdown
  fenced code block tagged `{=<format>}` for storage-to-markdown,
  HTML comment plus `<pre>` for the markdown-to-storage path). The
  default behaviour is "preserve content, surface fidelity loss in
  the diff" — never "drop silently."

Per-format policy (which shapes are first-class vs. which fall back)
lives in [S29](S29-confluence-ir-conversion.md) (Confluence)
and [S30](S30-markdown-ir-conversion.md) (markdown). The IR
itself only defines the mechanism.

## JSON serialization

`to_json(doc) -> dict` and `from_json(data) -> Document` are
required to satisfy:

1. **Round-trip equality.** `from_json(to_json(d)) == d` for every
   IR the spec allows. Enforced by a property test against the
   corpus (see [S33](S33-ir-roundtrip-testing-and-benchmarks.md)).
2. **Schema version.** Top-level dict has `mdd_ir_version: int`,
   currently `1`. Loaders refuse unknown major versions with a
   clear error.
3. **Stable key order.** Output keys are sorted; values reuse the
   IR's own structural order (list order, dict order in dataclass
   field order). This is what makes the on-disk JSON sidecar a
   useful diff target.
4. **Human-readable.** Two-space indent, `ensure_ascii=False`.
   Optimised for `git diff`, not for size.

The serialised form is a stable RPC / debugging payload if ever
needed (e.g. when calling out to language-foreign tooling); it is
not persisted to disk in production.

## Reattach

`identity.reattach(fresh: Document, cached: Document) -> Document`
walks both trees structurally; where the structural shape matches,
it grafts `node_id`, every cached `attributes` key absent from
fresh, and reader-only typed fields (`origin`, `trailing_ws`) from
cached onto fresh. Fresh wins where it carries a value; cached fills
in what's missing. The semantic contract: if the user did not edit a
block, the round-trip output is byte-identical to the original.

The cache key driving the cached-IR lookup is
`sha256(canonical_markdown)` — "canonical markdown" is the markdown
produced by the IR writer in default (normalising) mode (see
[S31](S31-ir-normalization-and-whitespace.md)). The cache-miss
path returns an IR without preserved identity; callers detect this
and treat it as "edits since last sync."

Production metadata (page id, version, update timestamp) lives in
YAML frontmatter on the markdown file (`mdd/confluence/frontmatter.py`),
not in a separate sidecar cache file. There is no on-disk
`<page>.confluence.json` in production.

## Public API

```python
from mdd.ir import (
    Document,
    parse_confluence_storage,   # (str) -> Document        # S29
    parse_markdown,             # (str) -> Document        # S30
    render_confluence_storage,  # (Document) -> str        # S29
    render_markdown,            # (Document) -> str        # S30
    to_json,                    # (Document) -> dict
    from_json,                  # (dict) -> Document
    reattach,                   # (fresh, cached) -> Document
    RawBlock, RawInline,
    FallbackEmitted,            # event type for callers that want to log
)
```

`Document` carries `blocks: list[Block]` plus metadata
(`source_format`, `parsed_at`, `fallbacks: list[FallbackEmitted]`).
It is the only IR type external code is expected to import beyond
`RawBlock` / `RawInline`.

## Related upstream specs

- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — Confluence storage XHTML mapping rules
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — Markdown mapping rules
- [031-ir-normalization-and-whitespace](S31-ir-normalization-and-whitespace.md) — Normalization passes and whitespace preservation
- [032-ir-test-corpus-expansion](S32-ir-test-corpus-expansion.md) — Test corpus expansion
- [033-ir-roundtrip-testing-and-benchmarks](S33-ir-roundtrip-testing-and-benchmarks.md) — Roundtrip testing and benchmarks

## Out of scope

- Confluence storage XHTML mapping rules → [S29](S29-confluence-ir-conversion.md).
- Markdown mapping rules → [S30](S30-markdown-ir-conversion.md).
- Normalization passes and whitespace preservation
  → [S31](S31-ir-normalization-and-whitespace.md).
- The merge / 3-way / conflict UX (downstream of this foundation;
  not in this spec series).
