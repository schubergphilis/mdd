---
test_corpus:
  authoring: markdown-first
  shapes:
  - line-break
  - soft-break
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114133/Line+breaks
  page_id: '1114133'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T17:26:46.237Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T17:26:46.616770+00:00'
---

# Line breaks

A line with two trailing spaces  
forces a hard break (the markdown two-space form).

A line with a backslash\
also forces a hard break (the GFM backslash form).

A paragraph that wraps onto
the next source line without trailing spaces becomes a soft break —
which Confluence storage flattens to a single line.

Three different ways to break a line, three different round-trips:
trailing-space breaks and backslash breaks both round-trip as
`<br/>`; soft breaks collapse to whitespace.
