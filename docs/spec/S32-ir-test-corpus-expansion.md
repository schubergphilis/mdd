# 032 - IR test corpus expansion

**Purpose:** Expand `mdd/test-confluence/MDD` to a complete coverage matrix of every non-deprecated Confluence storage shape and markdown construct.

**Status:** Implemented (2026-05-13)

## Introduction

An initial 35-fixture Confluence corpus, hosted in the sibling
`test-confluence/MDD` repository, predates this spec. This spec
defines the *complete* corpus the IR converters need to gate on.
The expanded corpus drives the roundtrip and benchmark suite in
[S33](S33-ir-roundtrip-testing-and-benchmarks.md). Shape
lists below refer back to [S29](S29-confluence-ir-conversion.md)
(Confluence mapping table) and [S30](S30-markdown-ir-conversion.md)
(markdown flavour table).

## Requirements

- **Every IR-recognised shape has at least one focused fixture.** A
  shape with no fixture is undefined behaviour by definition.
- **Every CommonMark 0.31 construct plus the configured GFM /
  custom extensions has at least one focused markdown-first
  fixture.** "100% markdown coverage" in the user's brief is
  defined concretely below.
- **Every fallback path has at least one fixture.** Unknown
  macros, unknown HTML elements in storage, raw HTML in markdown,
  ` ```confluence-xml ` fences — each gets an explicit fixture that
  documents the expected fallback behaviour.
- **Per-shape aggregation in the harness keeps working** — every
  new fixture carries the `test_corpus.shapes` frontmatter list
  established by the initial corpus.

## Design Approach

- Authoring split: roughly half the fixtures Confluence-first,
  roughly half markdown-first.
- **CommonMark + GFM markdown fixtures:** markdown-first (the
  source of truth is the markdown). Pushed via `mdd confluence
  create page`.
- **Confluence-specific macro / link / image fixtures:**
  Confluence-first (authored in the UI to get authentic storage
  XHTML, then exported via `mdd confluence export`).
- **Fallback fixtures:** mixed per the fixture — `unknown-html-
  element.md` is markdown-first (we author the raw HTML we want);
  `unknown-confluence-macro.md` is Confluence-first (we configure
  the macro in the editor).
- Each fixture's frontmatter records its authoring origin:

```yaml
test_corpus:
  authoring: confluence-first | markdown-first
  shapes:
    - <shape-tag>
  introduced: 2026-05-12
  fallback: false   # or true for fallback/ fixtures
```

## Implementation Notes

- The same `mise run refresh-corpus` task established in research note R08
  captures the new pages into `MDD/_snapshots/<page_id>/`. The
  expansion is one commit per category:
  1. Markdown fixtures (CommonMark + GFM + extensions).
  2. Confluence-first macro / link / image fixtures.
  3. Fallback fixtures.
  4. Snapshot refresh.
- Each step ends in a commit to `mdd/test-confluence/MDD`. The
  mdd-side commit that wires the expanded shapes into the harness
  follows in the same MR train as the spec-029 / spec-030
  implementation.
- `mise run ir-coverage` (defined in [S33](S33-ir-roundtrip-testing-and-benchmarks.md))
  emits a report listing:
  - Every IR node class and the count of fixtures exercising it.
  - Every fallback path and the count of fixtures exercising it.
  - Every CommonMark / GFM construct and its fixture count.
- The CI gate (per [S33](S33-ir-roundtrip-testing-and-benchmarks.md))
  fails when any IR node class, fallback path, or CommonMark / GFM
  construct has zero fixtures. New IR features cannot land without
  a fixture; new corpus shapes cannot land without an IR mapping or
  an explicit fallback.

## Coverage matrix

### Confluence storage shapes

Add fixtures for every row from
[S29](S29-confluence-ir-conversion.md)'s "First-class
element mappings" table that does not yet have one. Concretely
(against the current 35-fixture state):

- **Headings:** the existing corpus covers h1–h3. Add h4 / h5 /
  h6 fixtures.
- **Inline:** existing covers `strong`, `em`, `code`. Add
  `<s>` / `<del>` strikethrough fixture; add `<sup>` / `<sub>`
  fixture (currently falls back, see below).
- **Lists:** add nested-mixed (`ol` inside `ul` inside `ol`), task
  lists (Confluence's `<ac:task-list>` macro), and a loose-list
  fixture (blank lines between items).
- **Tables:** add header-row-only, alignment-per-column, `<th>` in
  body rows, multi-paragraph cell content, and a table with a
  table caption.
- **Code:** add code-with-tab-content (CDATA stress test) and
  code-with-collapse-parameter (`<ac:parameter ac:name="collapse">`).
- **Callouts:** existing covers `tip`, `panel`. Add `info`,
  `note`, `warning`, plus a callout with explicit title parameter
  and a callout containing another callout.
- **`ac:link` family:** existing covers `ri:page` (same-space),
  `ri:attachment`. Add `ri:page` (cross-space via `ri:space`),
  `ri:url`, `ri:user`, `ri:blog-post`, `ri:shortcut`, plus a
  link with `ac:link-body` (display text different from target).
- **`ac:image`:** existing covers basic shape. Add image with
  size attrs, alignment, alt text, and image with `ri:url`
  source.
- **Layout:** add `two_equal`, `three_equal`, and `single`
  layout-section fixtures. Add a layout with nested macros
  inside cells.
- **Inline ac:** add `<ac:emoticon>`, `<ac:placeholder>`,
  `<ac:mention>` (user mention via `<ri:user>`).
- **Niche macros (passthrough):** add `expand`, `info-card`,
  `jira`, `toc`, `panel` with non-default colour params, `iframe`,
  `attachments` macro, `pagetree`, `roadmap-planner`. These
  exercise the `ConfluenceMacro` generic carrier and the
  preserving-mode `attrs` plumbing.

### Markdown constructs (CommonMark 0.31 + GFM + extensions)

One fixture per construct, under
`MDD/fixtures/markdown/<category>/<construct>.md`. These are
**markdown-first** fixtures: authored as markdown, pushed to
Confluence, and the storage XHTML captured into `_snapshots/`.

CommonMark sections (numbering matches the spec):

| § | Construct | Fixture name |
|---|---|---|
| 4.1 | Thematic break | `thematic-break.md` |
| 4.2 | ATX headings (h1–h6) | `heading-atx-{1..6}.md` |
| 4.3 | Setext headings | `heading-setext.md` |
| 4.4 | Indented code block | `code-indented.md` |
| 4.5 | Fenced code block (backtick + tilde) | `code-fenced-backtick.md`, `code-fenced-tilde.md`, `code-fenced-info.md` |
| 4.8 | Paragraph (incl. soft-break / hard-break) | `paragraph-softbreak.md`, `paragraph-hardbreak-spaces.md`, `paragraph-hardbreak-backslash.md` |
| 4.9 | Blank lines | covered by other fixtures |
| 5.1 | Block quote (nested, lazy continuation) | `blockquote-nested.md`, `blockquote-lazy.md` |
| 5.2 | List items (bullet, ordered with start) | `list-bullet.md`, `list-ordered-start.md` |
| 5.3 | Tight vs loose list | `list-tight.md`, `list-loose.md` |
| 6.1 | Backslash escapes | `backslash-escapes.md` |
| 6.2 | Entity & numeric character refs | `entity-references.md` |
| 6.3 | Code spans | `code-span.md` |
| 6.4 | Emphasis & strong (variants) | `emphasis-star.md`, `emphasis-underscore.md`, `strong-star.md`, `strong-underscore.md`, `emphasis-mixed.md` |
| 6.5 | Links (inline, ref, autolink) | `link-inline.md`, `link-reference.md`, `link-autolink.md`, `link-title.md` |
| 6.6 | Images | `image-inline.md`, `image-reference.md` |
| 6.7 | Autolinks | `autolink.md` |
| 6.8 | Raw HTML (inline + block) | `raw-html-inline.md`, `raw-html-block.md` |
| 6.9 | Hard line breaks | covered above |

GFM additions:

| Construct | Fixture |
|---|---|
| Tables (basic, alignment, escapes) | `table-basic.md`, `table-alignment.md`, `table-escapes.md` |
| Strikethrough | `strikethrough.md` |
| Task lists | `task-list.md`, `task-list-nested.md` |
| Linkify (bare URL) | `linkify.md` |

mdd-specific extensions (per [S30](S30-markdown-ir-conversion.md)):

| Construct | Fixture |
|---|---|
| `:::callout-tip` fenced div (+ each kind) | `callout-tip.md`, `callout-info.md`, `callout-note.md`, `callout-warning.md`, `callout-panel.md` |
| `{{confluence:status colour="Green"}}` inline macro | `inline-macro-status.md`, `inline-macro-mention.md` |
| ` ```confluence-xml ` fence | `confluence-xml-fence.md` |
| Synthetic URI `confluence-page:` | `confluence-uri-page.md` |
| Synthetic URI `confluence-attachment:` | `confluence-uri-attachment.md` |
| Synthetic URI `confluence-user:` | `confluence-uri-user.md` |

### Fallback fixtures

Each fallback path gets one fixture under
`fixtures/fallback/`:

- `unknown-confluence-macro.md` — a `<ac:structured-macro
  ac:name="bogus-macro">` confirms `ConfluenceMacro` generic carrier
  round-trips.
- `unknown-html-element.md` — a `<details><summary>…</summary>…</details>`
  block confirms `RawBlock(format="html", ...)` round-trips.
- `inline-html.md` — `<kbd>…</kbd>` inline confirms
  `RawInline(format="html", ...)` round-trips.
- `entity-form-preservation.md` — `&hellip;` (storage-first) vs
  `…` (markdown-first) confirms whitespace-preserving mode
  round-trips both.
- `merged-cells.md` — a `colspan=2` / `rowspan=2` table confirms
  the IR carries the structure and the markdown writer falls back
  to HTML `<table>` cleanly.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — Confluence storage shape mapping table
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — markdown flavour table
- [033-ir-roundtrip-testing-and-benchmarks](S33-ir-roundtrip-testing-and-benchmarks.md) — roundtrip and benchmark suite driven by this corpus
