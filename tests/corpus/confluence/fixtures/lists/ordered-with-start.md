---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-ordered-start
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147014/Ordered+list+with+explicit+start
  page_id: '1147014'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:40.870Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:41.285670+00:00'
---

# Ordered list with explicit start

CommonMark allows an ordered list to begin at any positive integer.
The first item's marker sets the `start` attribute on the rendered
`<ol>`; subsequent markers may be any digits — the renderer numbers
them sequentially from `start`.

5. Fifth item — this list starts at five, not one.
6. Sixth item.
7. Seventh item, slightly longer to test that wrapping does not
   break the start attribute carried on the parent `<ol>`.
8. Eighth and final item.

Confluence storage represents this as `<ol start="5">`. The round-
trip must carry the `start` attribute through both reader and
writer; dropping it silently re-numbers from one and changes the
rendered output.
