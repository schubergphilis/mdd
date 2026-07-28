# 029 - Confluence storage XHTML ↔ IR conversion

**Purpose:** Map Confluence storage XHTML to and from the document IR defined in [S28](S28-document-ir-foundation.md).

**Status:** Implemented (2026-05-13)

## Introduction

This spec defines `parse_confluence_storage` and `render_confluence_storage` in `src/mdd/confluence/ir/`, replacing the existing converter pair `storage_to_md.py` and `md_to_storage.py`. The new converters key off the typed IR rather than direct markdown ↔ XHTML walking, provide first-class handling of every element shape in the test corpus, and apply a documented fallback policy for everything else — never silently dropping content.

## Requirements

- Replace the converter pair `src/mdd/confluence/storage_to_md.py` and
  `src/mdd/confluence/md_to_storage.py` with `parse_confluence_storage`
  and `render_confluence_storage` in `src/mdd/confluence/ir/`, keyed
  off the typed IR rather than direct markdown ↔ XHTML walking.
- The markdown side moves to [S30](S30-markdown-ir-conversion.md).
- Handle every element shape in the test corpus with a first-class mapping.
- Provide a documented fallback policy for unknown elements — never silently drop content.
- Preserve identity attributes (`ac:macro-id`, `ac:local-id`) and passthrough attributes (`style`, `data-*`, `class`).
- Writer must be purely deterministic: same input IR always emits the same XHTML bytes.
- Satisfy the byte-perfect round-trip guarantee required by the merge engine (per [S33](S33-ir-roundtrip-testing-and-benchmarks.md)).
- Close the five fidelity fixes listed under "Implementation Notes" below before the production gate.
- Keep `storage_to_md.py` and `md_to_storage.py` as deprecated thin wrappers for one release; remove them in the following release.

## Design Approach

- Parse with `lxml.etree` in recovery mode to tolerate whitespace-only text content and unbalanced elements.
- Walk the resulting tree depth-first, dispatching per element name via `elements.py`.
- Assign `node_id` as `b00001`, `b00002`, … depth-first across the whole document.
- Populate the node's `attributes: dict[str, str]` from `etree.attrib.items()` in source order; lxml preserves source attribute order. Child-element data (`ri:version-at-save`, `ri:local-id`, etc.) goes into typed fields on the node class.
- Set typed semantic fields (`compact`, `omit_start`, `no_wrapper`, `body_leading_ws`, `body_trailing_ws`) instead of magic-string keys in `attributes`.
- Emit `RawBlock(format="confluence-storage", ...)` / `RawInline(...)` for unrecognised elements; record a `FallbackEmitted` event on `document.fallbacks`.
- Block-vs-inline decision driven by a per-element "context" table rather than hard-coded rules.
- Writer emits `node.attributes` in dict-insertion order — preserving source attribute ordering byte-perfect. No identity-first / passthrough-sorted reordering.
- Use CDATA-wrapped bodies for `CodeBlock` content via `cdata.wrap()`.
- Unknown IR node subclasses are a programming error — every node defined in [S28](S28-document-ir-foundation.md) must have a writer entry; the corpus-coverage gate enforces this.

## Implementation Notes

- `reader.py` and `writer.py` are the public entry points; everything else (`elements.py`, `attrs.py`, `macros.py`, `links.py`, `images.py`, `cdata.py`, `fallback.py`) is internal.
- The `identity.reattach` mechanism from [S28](S28-document-ir-foundation.md) grafts `node_id`, missing `attributes` keys, and reader-only typed fields (`origin`, `trailing_ws`) from a cached IR onto a freshly parsed one when structure matches; the production call shape is two parse+render cycles with `reattach` in between.
- `RawBlock(format="confluence-storage", ...)` and `RawBlock(format="xhtml", ...)` are intentionally interchangeable on the storage side; other `RawBlock` formats become an HTML comment wrapping a `<pre>`.
- Five fidelity fixes required before the byte-perfect round-trip gate: (1) preserve trailing/empty paragraphs through the cache leg; (2) always emit `start="1"` on `<ol>` even when default; (3) plumb `attributes` through `ConfluenceMacro`'s writer and honour `rich_body` vs `plain_body`; (4) add standalone-vs-inline hint on `ConfluenceLink`; (5) preserve HTML-entity form vs Unicode-char form per token (the `&hellip;` → `…` regression, tracked by [S31](S31-ir-normalization-and-whitespace.md)).
- Deprecated wrappers log a deprecation note on import; they are removed in the cutover release once the IR is the default for `mdd confluence`.

## Module layout

```
src/mdd/confluence/ir/
  __init__.py
  reader.py          # parse_confluence_storage(str) -> Document
  writer.py          # render_confluence_storage(Document) -> str
  elements.py        # element-name → handler dispatch tables
  attrs.py           # source-order attribute helpers
  macros.py          # callout / structured-macro mappings
  links.py           # ac:link / ri:* family handling
  images.py          # ac:image handling
  cdata.py           # CDATA preservation for code macros
  fallback.py        # per-format fallback emission (xhtml passthrough)
```

## Reader behaviour

`parse_confluence_storage(storage: str) -> Document`

- Parses with `lxml.etree` in recovery mode. Storage XHTML is
  *almost* well-formed XML but Confluence occasionally emits
  whitespace-only-text content and unbalanced elements; recovery
  mode tolerates both.
- Walks the resulting tree depth-first, dispatching per element
  name in `elements.py`. Each handler returns one IR node (or a
  list, for elements that flatten — e.g. `<ac:layout>` siblings).
- Assigns `node_id` as `b00001`, `b00002`, … depth-first across
  the whole document.
- Populates `node.attributes` from `etree.attrib.items()` in source
  order; lxml preserves lxml-source attribute order so the original
  Confluence attribute ordering round-trips byte-perfect.
- Child-element data (e.g. `ri:version-at-save` on `<ri:attachment>`,
  `ri:local-id` on `<ri:user>`) goes into typed fields on the
  relevant node class rather than into `attributes`.

### First-class element mappings

| Storage XHTML | IR node | Notes |
|---|---|---|
| `<p>` | `Paragraph` | Empty `<p></p>` preserved (matters for the trailing-paragraph case from note 013). |
| `<h1>`–`<h6>` | `Heading(level=N)` | |
| `<ul>` | `BulletList` | `tight` inferred from `<li>` shape (one block child → tight). |
| `<ol>` | `OrderedList(start=...)` | `start` preserved verbatim. |
| `<li>` | `ListItem` | |
| `<blockquote>` | `BlockQuote` | |
| `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` | `Table` / `TableRow` / `TableCell` | `colspan` / `rowspan` carried natively. `<th>` in body rows becomes a cell with an attribute marker. |
| `<hr/>` | `HorizontalRule` | |
| `<br/>` | `LineBreak` | |
| `<strong>`, `<b>` | `Strong` | |
| `<em>`, `<i>` | `Emph` | |
| `<code>` | `Code` | |
| `<s>`, `<del>` | `Strikethrough` | |
| `<a href="...">` | `Link` | |
| `<img src="...">` | `Image` | Non-`ac:image` HTML image. |
| `<ac:structured-macro ac:name="code">` | `CodeBlock` | `language` from `<ac:parameter ac:name="language">`. Content from `<ac:plain-text-body><![CDATA[…]]>`. |
| `<ac:structured-macro ac:name="tip\|info\|note\|warning\|panel">` | `Callout(kind=...)` | Title from `<ac:parameter ac:name="title">` when present. Body from `<ac:rich-text-body>`. |
| `<ac:structured-macro ac:name="X">` (any other) | `ConfluenceMacro(name="X", ...)` | Generic carrier. Parameters → `params`; rich body → `rich_body` blocks; plain body → `plain_body` string. |
| `<ac:link>` + `<ri:page>` | `ConfluenceLink(target_kind="page", ...)` | `space_key` from sibling `<ri:space>` if present. |
| `<ac:link>` + `<ri:attachment>` | `ConfluenceLink(target_kind="attachment", target=filename)` | |
| `<ac:link>` + `<ri:url>` | `ConfluenceLink(target_kind="url", target=value)` | |
| `<ac:link>` + `<ri:user>` | `ConfluenceLink(target_kind="user", target=accountId)` | `ri:local-id` (per-mention identifier for collaborative-edit tracking) carried in `ConfluenceLink.user_local_id`. A bare `<ri:user/>` child (no `<ac:link-body>`) round-trips with empty `body_tokens`; the writer must not synthesise a link body. |
| `<ac:link>` + `<ri:blog-post>` | `ConfluenceLink(target_kind="blogpost", ...)` | `ri:posting-day` → `ConfluenceLink.posting_day`. |
| `<ac:link>` + `<ri:shortcut>` | `ConfluenceLink(target_kind="shortcut", ...)` | |
| `<ac:image>` | `ConfluenceImage` | `source_kind` from child element. Editor decorations (`ac:width`, `ac:height`, `ac:align`, `ac:alt`, `ac:layout`, `ac:original-height`, `ac:original-width`, `ac:custom-width`, `ac:local-id`) carried in `attributes` in source order. `ri:version-at-save` on the child `<ri:attachment>` is stored in `ConfluenceImage.attachment_version` and re-emitted on the child by the writer. |
| `<ac:emoticon ac:name=...>` | `Emoticon` | |
| `<ac:placeholder>` | `Placeholder` | |
| `<ac:layout>`, `<ac:layout-section>`, `<ac:layout-cell>` | `Layout` / `LayoutSection` / `LayoutCell` | Preserved structurally; not flattened. `ac:type` / `ac:breakout-mode` / `ac:breakout-width` / `ac:local-id` on the section ride in `attributes` in source order (and are reattached from the cached source IR on round-trip — the markdown leg does not carry them). |

### Fallback policy

For elements not in the table above, the reader:

1. Emits `RawBlock(format="confluence-storage", content=<verbatim>)`
   for block-level shapes, or `RawInline(format="confluence-storage", ...)`
   for inline shapes.
2. Records a `FallbackEmitted` event on the parse context with the
   element name, line number (when available), and a one-line
   excerpt. Callers can inspect `document.fallbacks` to see what
   fell through.
3. **Never silently drops** content — even unknown wrappers
   serialise their children inside the raw block so text remains
   diff-visible.

The block-vs-inline decision is made by a small per-element
"context" table: e.g. `<ac:structured-macro>` is treated as inline
when its only parent context is a `<p>`, block otherwise. This
replaces the hard-coded inline-vs-block decisions in the current
`storage_to_md.py`.

## Writer behaviour

`render_confluence_storage(doc: Document) -> str`

- Walks the IR depth-first, emitting storage XHTML strings.
- Emits `node.attributes` in dict-insertion order. Source attribute
  ordering is preserved byte-perfect because the reader populated
  `attributes` from `etree.attrib.items()` in source order.
- Uses CDATA-wrapped bodies for `CodeBlock` content via
  `cdata.wrap()` (matches Confluence's own emission shape).
- Emits `RawBlock(format="confluence-storage", ...)` content
  verbatim; emits `RawBlock(format="xhtml", ...)` content verbatim
  too (the two formats are intentionally interchangeable on the
  storage side). Other `RawBlock` formats become an HTML comment
  wrapping a `<pre>` with the raw content (visible, surface-loss).
- Writer is purely deterministic — same input IR always emits the
  same XHTML bytes. Attribute ordering, namespace prefixes,
  self-closing-tag choice, and entity-encoding are all fixed.

The "decent fallback" for shapes the writer doesn't yet handle: an
IR node with an unknown subclass is a programming error, not a
runtime concern — every node defined in [S28](S28-document-ir-foundation.md)
must have a writer entry. The corpus-coverage gate enforces this.

## Identity and round-trip guarantee

Per [S28](S28-document-ir-foundation.md), `identity.reattach`
grafts `node_id`, missing `attributes` keys, and reader-only typed
fields (`origin`, `trailing_ws`) from a cached IR onto a freshly
parsed one when the structure matches. The contract for this pair:

```
storage → parse → render → storage'      # without reattach: differs in node_id
storage → parse → render → parse → reattach(cached=parse(storage)) → render → storage''
```

The second form (the production call shape) MUST yield
`storage'' == storage` on every fixture in the corpus once the
five fidelity fixes (see "Implementation Notes") have landed. The
third roundtrip test in [S33](S33-ir-roundtrip-testing-and-benchmarks.md)
enforces this as the production gate.

## Block-level inline hint

A `<ac:link>` or `<ac:image>` that appears as a **direct child of a
block container** (e.g. directly inside `<ac:layout-cell>` with no
`<p>` wrapper) sets `block_level=True` on the resulting IR node
(`ConfluenceLink.block_level` / `ConfluenceImage.block_level` — typed
`bool` fields, **not** stored in `extras`). The storage writer reads
the flag and emits the inline bare instead of synthesising a `<p>`
wrapper on the round-trip. Image-only layout cells and standalone
user mentions both rely on this. Set only by the storage reader's
`read_blocks_from_container`; never set by the markdown leg.

## Fidelity fix status

The five fidelity fixes from "Implementation Notes" are all
resolved:

1. **Preserve trailing / empty paragraphs through the cache leg.** Shipped — empty paragraphs self-close to `<p />` to match Confluence storage shape (commit `b144918`).
2. **Always emit `start="1"` on `<ol>` even when default.** Shipped during the initial Confluence writer port.
3. **Plumb `attributes` through `ConfluenceMacro`'s writer; honour `rich_body` vs `plain_body` distinction.** Shipped during the initial port; `reattach` grafts ConfluenceMacro shape (name, params, rich_body, plain_body) lost through the markdown leg.
4. **Standalone-vs-inline hint on `ConfluenceLink`.** Shipped during the initial port — a top-level `<ac:link>` is not re-wrapped in `<p>` on render.
5. **Preserve HTML-entity form vs Unicode-char form per token** (the `&hellip;` → `…` regression). Shipped via universal entity-form re-emission (commit `7d8fd4a`); see [S31](S31-ir-normalization-and-whitespace.md) for the whitespace-preserving mode mechanics.

Two fixtures remain xfailed under R3-preserving (`1081405`
backslash escapes, `1212604` inline `<kbd>` / `<samp>`); both are
markdown-converter work, not Confluence-converter work.

## Backwards compatibility

`src/mdd/confluence/storage_to_md.py` and
`src/mdd/confluence/md_to_storage.py` are **deleted** (commit
`0153d7b`, 2026-05-13). They were kept as deprecated wrappers
during phases 2–6 of the IR rollout and removed at the cutover
alongside the rewrite of `export.py` / `update.py` / `create.py` /
`attachments.py` to call the IR converters directly.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [014-confluence-sync](S14-confluence-sync.md) — existing sync flow
- [028-document-ir-foundation](S28-document-ir-foundation.md) — IR types and identity contract
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — markdown side of the converter pair
- [031-ir-normalization-and-whitespace](S31-ir-normalization-and-whitespace.md) — whitespace-preserving mode (entity form tracking)
- [033-ir-roundtrip-testing-and-benchmarks](S33-ir-roundtrip-testing-and-benchmarks.md) — corpus-coverage gate and round-trip tests
