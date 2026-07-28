---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-tight
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212455/Tight+list
  page_id: '1212455'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:43.256Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:43.646719+00:00'
---

# Tight list

A CommonMark list is "tight" when no blank lines separate its
items. The renderer omits the wrapping `<p>` inside each `<li>` —
the item's text becomes the direct child of `<li>`. Confluence
storage follows the same convention, so tight lists round-trip as
`<ul><li>text</li><li>text</li>…</ul>` without inner paragraphs.

- First tight item
- Second tight item
- Third tight item
- Fourth tight item

Tight vs loose is a structural distinction CommonMark makes at the
list level, not at the item level: a single blank line anywhere
inside the list promotes the entire list to loose. This fixture
keeps every item glued so the round-trip should yield a list of
plain text `<li>` children with no nested `<p>` wrappers.
