---
test_corpus:
  authoring: markdown-first
  shapes:
  - callout-note
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081488/Callout+note+markdown-first
  page_id: '1081488'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:13.168Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:13.610587+00:00'
---

# Callout — note (markdown-first)

The `:::callout-note` fenced div maps to Confluence's `note`
macro (yellow background). Notes are softer than warnings — a
sidebar to the main flow.

:::callout-note
This is a note. The body is one paragraph plus an inline
`code span` and an _italic phrase_. The round-trip should
keep the inline structure intact inside the macro.
:::

A trailing paragraph confirms the close fence releases the
block-scope back to the document body.
