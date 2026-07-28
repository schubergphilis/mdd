---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-loose
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147033/Loose+list
  page_id: '1147033'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 3
  updated_at: '2026-05-13T20:25:46.923Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T20:25:47.591167+00:00'
---

# Loose list

A CommonMark list becomes "loose" when one or more blank lines
separate its items. The renderer then wraps each item's text in a
`<p>` element inside the `<li>`. Confluence storage follows the
same rule: every item's text becomes the body of a `<p>` child of
`<li>`, instead of sitting as bare text on the `<li>` itself.

- First loose item, separated from the next by a blank line.

- Second loose item, paragraphs wrapped in `<p>` inside the `<li>`.

- Third loose item — still loose because the blank lines apply to
  the list as a whole, not to individual items.

- Fourth and final loose item.

Loose vs tight is decided at the list level: even one blank line
between items promotes every item to paragraph-wrapped. The
round-trip should preserve that structural promotion exactly.
