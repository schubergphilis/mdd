---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-external
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/131272/External+URL+link
  page_id: '131272'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:53.583Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:54.070727+00:00'
---

# External URL link

A paragraph containing a single external URL link. Confluence
storage typically emits this as a plain `<a href="…">` element,
not as `<ac:link><ri:url …/></ac:link>` (the `ac:link` shape is
reserved for content-aware references).

See [the Pandoc homepage](https://pandoc.org) for the canonical
reference on document conversion. The link target round-trips
verbatim, with the surrounding sentence preserved.
