---
test_corpus:
  authoring: markdown-first
  shapes:
  - paragraph
  - paragraph-boundary
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/164003/Multiple+paragraphs
  page_id: '164003'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:12.173Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:12.613367+00:00'
---

# Multiple paragraphs

First paragraph. Short and plain.

Second paragraph, separated from the first by exactly one blank
line in markdown source. The round-trip should preserve the
paragraph boundary as a `<p>` element break in storage XHTML
without merging the two into one paragraph.

Third paragraph, with intentionally trailing whitespace at the
sentence boundaries to confirm the converter normalises it
predictably.

Fourth and final paragraph, present so that the page contains an
even number of paragraphs — if any rendering pass injects or drops
the first or last paragraph, the count check catches it.
