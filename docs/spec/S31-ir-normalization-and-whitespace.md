# 031 - IR normalization and whitespace preservation

**Purpose:** Define normalising and preserving modes for IR converters, where both modes share the same IR but differ in reader metadata and writer behaviour.

**Status:** Implemented (2026-05-13)

## Introduction

The IR converters ([S29](S29-confluence-ir-conversion.md), [S30](S30-markdown-ir-conversion.md)) require two modes: a default *normalising* mode that produces clean, diff-friendly output, and an opt-in *preserving* mode that round-trips byte-perfectly.

Three of the Confluence-converter fidelity fixes listed in
[S29](S29-confluence-ir-conversion.md) (preserving trailing
empty paragraphs, default `start="1"`, HTML-entity-vs-Unicode form)
are whitespace / encoding concerns that deserve a coherent design
instead of ad-hoc plumbing, and live here.

## Requirements

- Provide a default *normalising* mode for human export: clean, diff-friendly, cache-keyable output.
- Provide an opt-in *preserving* mode for round-trip / sync: byte-perfect fidelity so Confluence sees its own bytes back on untouched content.
- Both modes share the same IR; the mode is a flag on `parse_*` / `render_*`, defaulting to normalising.
- The cache layer always uses normalising mode for its key (`sha256(normalised_markdown) → cached_IR`); the writer that emits to Confluence uses preserving mode on cache-hit content.
- Each block and addressable inline carries an optional `origin` field (`Origin` dataclass) populated in preserving mode, `None` in normalising mode.
- IR JSON schema is `mdd_ir_version: 2`; `Origin` is an additive field, omitted when null.

## Design Approach

- **Normalising mode** (default for human export): apply the normalisation passes pipeline. Output is canonical, diff-friendly, cache-keyable.
- **Preserving mode** (default for round-trip / sync): skip normalisation, keep every byte / attribute / entity form observable.
- A normalising pass is a pure function `Document -> Document`; the pipeline is a tuple; preserving mode is the tuple's empty prefix.
- `Origin` metadata is captured on parse and re-emitted on render when present; dropped (or normalised) when absent.
- The mode is a property of the call site, not of the IR — the same `Document` can be re-rendered in either mode at any time.

## Implementation Notes

- Normalisation passes live in `mdd.ir.normalize`; each pass is a separate function.
- `origin = None` on every node in normalising mode (cheaper, smaller JSON, no encoding-of-source-bytes concern).
- `raw_bytes` in JSON is base64-encoded with a `"@base64"` marker key; `entity_form` is a sorted list of `[offset, entity_string]` tuples for deterministic diff.
- Preserving mode roughly doubles the per-node memory footprint; expected ~50 ms on the 35-fixture corpus vs ~31 ms for normalising mode — both well below the pandoc baseline (2895 ms).

## Why two modes

The merge engine needs **byte-perfect** round-trip on untouched
content — otherwise every sync silently rewrites the page. Humans
reading exported markdown want **clean** output — no rendered
`&hellip;` clutter, no trailing blank paragraphs, no zero-padding
on ordered lists. These goals conflict; a single mode can't serve
both.

The split:

- **Normalising mode** (default for human export): apply the
  normalisation passes below. Output is canonical, diff-friendly,
  cache-keyable. This is what `mdd confluence export` writes to
  the markdown file on disk.
- **Preserving mode** (default for round-trip / sync): skip
  normalisation, keep every byte / attribute / entity form
  observable. This is what runs internally during the push leg so
  Confluence sees its own bytes back when the user didn't edit.

The IR carries enough metadata to support both. The choice of
mode is a flag on `parse_*` / `render_*`, defaulting to
normalising. The cache layer always uses normalising mode for its
key (so `sha256(normalised_markdown) → cached_IR`); the writer
that actually emits to Confluence uses preserving mode on
cache-hit content.

## Normalisation passes

A normalising pass is a pure function `Document -> Document`. The
default `parse_markdown(..., normalize=True)` runs the full
pipeline; individual passes are addressable for tests and for the
preserving mode (which runs none of them).

| Pass | What it does | Why |
|---|---|---|
| `collapse_soft_breaks` | `SoftBreak` inside a `Paragraph` becomes a single space. | Aligns markdown's "source line wrap" with HTML's "whitespace collapses." |
| `tighten_lists` | `tight=True` when every `ListItem` has exactly one `Paragraph` child. | Matches CommonMark's tight-vs-loose decision. |
| `default_ordered_start` | Drop `start=1` (it round-trips back as `1` from the writer). | Tighter markdown surface. **Skipped in preserving mode** — spike fix #2. |
| `normalise_entities` | Convert HTML named entities (`&hellip;`) to Unicode (`…`) where the character is safe. | Cleaner reading. **Skipped in preserving mode** — spike fix #5. |
| `normalise_whitespace` | Collapse runs of internal whitespace inside `Text`; trim leading/trailing on `Paragraph`. | Matches HTML whitespace collapse. |
| `drop_empty_paragraphs` | Remove `Paragraph(inline=[])` and `Paragraph(inline=[Text(" ")])`. | **Skipped in preserving mode** — spike fix #1. |
| `attach_callout_kind` | Map prose conventions (`> [!tip] …`) → `Callout(kind="tip")`. | Lets humans write GFM-style alerts that round-trip cleanly. |
| `dedupe_attrs` | Remove `attributes` keys that the writer would emit by default anyway (e.g. keys whose value equals the element's default). | Tighter IR JSON. |

Each pass is a separate function in `mdd.ir.normalize`. The
pipeline is a tuple; the preserving mode is the tuple's empty
prefix.

## Whitespace preservation model

The IR cannot represent "every byte" of source markup directly
without ceasing to be an AST. Instead, *origin metadata* is
captured on parse and re-emitted on render when present, and
dropped (or normalised) when absent.

Each block and addressable inline carries an optional `origin`
field:

```python
@dataclass(frozen=True)
class Origin:
    """Lossless source-form metadata. Optional — only populated in preserving mode."""
    source_format: Literal["confluence-storage", "markdown", "html"]
    raw_bytes: bytes          # the exact source slice
    leading_ws: str           # whitespace before this node in the source
    trailing_ws: str          # whitespace after
    entity_form: dict[int, str]   # codepoint offset → original entity, if any
```

Behavioural rules:

- **Reader (preserving):** records `Origin` on every node. `raw_bytes`
  is set for `Text` leaves and for `RawBlock` / `RawInline`; for
  structural nodes only `leading_ws`, `trailing_ws`, and
  `entity_form` are populated.
- **Reader (normalising):** `origin = None` on every node. Cheaper,
  smaller JSON, no encoding-of-source-bytes concern.
- **Writer (preserving):** when `origin` is present, emits
  `leading_ws` / `entity_form` re-substituted into the output
  *before* falling back to its default emission rules.
- **Writer (normalising):** ignores `origin` entirely and emits
  canonical form.

The cache-hit round-trip (the production merge case) uses
preserving mode on both legs so source bytes survive. The
cache-miss path (user-edited markdown) uses normalising mode
because there is no `Origin` to honour.

## Encoding-form tracking

The `&hellip;` ↔ `…` problem (the fifth fidelity fix listed in
[S29](S29-confluence-ir-conversion.md)) is a special case of
the `entity_form` field:

- The Confluence reader, when in preserving mode, records each
  HTML entity it decodes against the codepoint offset in the
  decoded `Text.content`.
- The Confluence writer, when emitting `Text` content, consults
  `Origin.entity_form` and re-emits the original entity at the
  recorded offset instead of the canonical Unicode form.
- The markdown leg passes `Origin` through untouched (it is on
  the IR node, not in the markdown surface) so the round-trip via
  the cache preserves it.

The same mechanism handles CDATA trailing-newline normalisation
on `CodeBlock` content.

## `Origin` JSON shape

`Origin` is serialised to JSON like every other dataclass field,
with these specific rules:

- `raw_bytes` becomes a base64-encoded string with a `"@base64"`
  marker key, to avoid encoding-trip concerns.
- `entity_form` is a sorted list of `[offset, entity_string]` tuples
  for deterministic diff.
- `Origin` is omitted entirely when null (avoiding a size explosion
  for normalising-mode IRs).
- `raw_bytes_truncated` is `true` when the per-node cap fired
  (see §"`Origin.raw_bytes` size cap"); the field is omitted when
  `false`, so an absent flag means "untruncated".

The schema version is `mdd_ir_version: 2`; `Origin` is an additive
field. Normalising-mode JSON is forward-compatible with future
preserving-mode loaders (the loader treats absence as "no origin
metadata available").

## On-disk persistence

There is no on-disk IR sidecar in production. An earlier design
called for `<page>.confluence.json` next to each markdown file
(`SidecarCache`); that design was retired in P03 phase 5 because
production metadata (page id, version, update timestamp) already
lives in the markdown's YAML frontmatter, and the cache-key
lookup happens in-process from the remote-storage parse rather
than from a persisted file. The IR JSON serialisation
([S28](S28-document-ir-foundation.md) §"JSON serialization") is
still available for tests and for future RPC use, but is not
written to disk during normal `mdd confluence` runs.

## `Origin.raw_bytes` size cap

The reader enforces a 256 KiB cap on `Origin.raw_bytes` per node
(`mdd.ir.nodes.ORIGIN_RAW_BYTES_CAP`). Above the cap the
dataclass drops `raw_bytes` and flips `raw_bytes_truncated = True`;
preserving-mode writers consult that flag and fall back to their
canonical render for that node instead of replaying a partial
slice. This trades byte-perfect fidelity for graceful degradation
on the long-tail of pages with multi-megabyte text leaves:

- IR JSON stays bounded — the 10× ratio gate
  ([S33](S33-ir-roundtrip-testing-and-benchmarks.md) §"R4")
  remains reachable on real content.
- Round-trip fidelity is preserved for everything under the cap;
  beyond it, the writer emits the canonical IR form which is the
  same path the cache-miss / normalising-mode legs already use.
- The flag survives JSON round-trip so a downstream consumer that
  re-loads the IR still sees the "do not replay" signal.

Tested in `tests/ir/test_origin_size_cap.py`.

## Performance impact

Preserving mode roughly doubles the per-node memory footprint
(every `Text` leaf carries `raw_bytes` + `entity_form`).
Normalising mode runs the full 35-fixture corpus in ~31 ms;
preserving mode lands around ~50 ms. Both stay well below the
pandoc baseline (2895 ms) the earlier converter generation
measured against.

The trade is heavily favourable: 20 ms of work to keep merge
semantics byte-perfect is invisible against any I/O the sync
loop does.

## When each mode runs

| Caller | Mode | Rationale |
|---|---|---|
| `mdd confluence export-page` | normalising | Human reads the markdown file. |
| `mdd confluence sync-space` (any mode) | normalising on pull | Writes to disk. |
| `mdd confluence sync` pull leg | normalising | Writes to disk. |
| `mdd confluence sync` push leg (cache hit) | preserving | Confluence sees its own bytes back. |
| `mdd confluence sync` push leg (cache miss) | normalising | No `Origin` to preserve; user edited the file. |
| `mdd confluence sync` merge (3-way) | preserving on both legs | Tree diff over `Origin`-stripped IRs; merged output uses `Origin` from whichever side didn't change a given subtree. |
| Test harness (round-trip) | both, separately | Catches drift in either mode. |

The mode is a property of the call site, not of the IR. The same
`Document` can be re-rendered in either mode at any time.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — Confluence storage ↔ IR conversion
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — Markdown ↔ IR conversion

## Open questions

1. **`Origin.raw_bytes` size budget.** *Decided 2026-05-13:* cap
   `Origin.raw_bytes` at **256 KiB** per node, drop the bytes and
   set `raw_bytes_truncated = True` above that, and have writers
   fall back to their canonical render for truncated nodes. See
   §"`Origin.raw_bytes` size cap" above. (Was: A 5MB Confluence
   page with long-form prose could blow up the IR JSON to ~10MB.)
2. **`Origin` survival across structural edits.** If the user
   splits a paragraph in two, the second half's `Origin` is no
   longer meaningful. The cache-miss heuristic (re-parse without
   origin) covers this. Whether finer-grained per-subtree origin
   matters is a merge-engine question; defer.
3. **Mode-flag plumbing in the public API.** Two options: a
   `mode: Literal["normalising","preserving"] = "normalising"` kwarg
   on every `parse_*` / `render_*`; or a `IRConfig` object passed
   through. The kwarg is simpler; pick on first impl.
