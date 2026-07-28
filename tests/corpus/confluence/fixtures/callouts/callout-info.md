---
test_corpus:
  authoring: markdown-first
  shapes:
  - callout-info
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081469/Callout+info+markdown-first
  page_id: '1081469'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:10.932Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:11.368795+00:00'
---

# Callout — info (markdown-first)

The `:::callout-info` fenced div maps to Confluence's `info`
macro (blue background). This fixture exercises the
markdown-first authoring path for the info kind.

:::callout-info
**Heads up.** Info callouts highlight context the reader needs
to keep going without alarm. They are not warnings — use
`:::callout-warning` for those.

A second paragraph keeps the macro body multi-block: the IR
should preserve both paragraphs as children of the same
`Callout(kind="info")` node.
:::
