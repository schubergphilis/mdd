---
test_corpus:
  authoring: markdown-first
  shapes:
  - paragraph
  - inline-text
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98308/Plain+paragraph
  page_id: '98308'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:17:29.489Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:17:29.908616+00:00'
---

# Plain paragraph

This page exercises the simplest possible Confluence storage element:
a single paragraph of plain text with no inline formatting, no
links, no macros.

If round-trip works for this fixture, the basic markdown → storage
XHTML → markdown loop is intact. If it fails, every other fixture
will fail too — this is the smoke-test bottom of the corpus.

The page is intentionally short so that any whitespace or escape-
handling drift shows up quickly in a diff.
