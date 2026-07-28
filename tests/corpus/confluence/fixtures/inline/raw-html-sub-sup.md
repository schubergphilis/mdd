---
test_corpus:
  authoring: markdown-first
  shapes:
  - raw-inline-html
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1146902/Raw+inline+HTML
  page_id: '1146902'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 3
  updated_at: '2026-05-13T17:27:50.594Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T17:27:50.986507+00:00'
---

# Raw inline HTML

Some inline HTML elements have no native markdown form. `<sub>` and
`<sup>` mark subscript / superscript and round-trip as `RawInline`
nodes in the IR with `format="confluence-storage"`. (We originally
tried `<kbd>` here but Confluence strips it; `<sub>` and `<sup>`
survive sanitisation cleanly.)

Water is H<sub>2</sub>O. Einstein's formula is E = mc<sup>2</sup>.
Both the `<sub>` and `<sup>` markers survive the markdown ->
Confluence storage round-trip; the IR carries them as `RawInline`
through both legs.
