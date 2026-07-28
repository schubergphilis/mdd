---
test_corpus:
  authoring: markdown-first
  shapes:
  - callout-panel
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081507/Callout+panel+markdown-first
  page_id: '1081507'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:17.744Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:18.180605+00:00'
---

# Callout — panel (markdown-first)

The `:::callout-panel` fenced div maps to Confluence's `panel`
macro — a generic boxed container with no specific connotation,
used for highlighting a quoted passage or summary. Panels often
carry parameters (title, background colour) in Confluence; this
fixture stays minimal to exercise the bare macro shape.

:::callout-panel
A panel body can hold any block content the rich-text editor
accepts: paragraphs, lists, sub-headings, code blocks. The IR
preserves the inner block structure as children of the
`Callout(kind="panel")` node.

- First child item
- Second child item

A trailing paragraph closes the panel body before the fence.
:::
