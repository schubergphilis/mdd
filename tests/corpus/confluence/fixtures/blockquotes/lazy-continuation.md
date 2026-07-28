---
test_corpus:
  authoring: markdown-first
  shapes:
  - blockquote-lazy-continuation
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1146988/Lazy+blockquote+continuation
  page_id: '1146988'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:36.144Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:36.553165+00:00'
---

# Lazy blockquote continuation

CommonMark allows blockquote continuation lines to omit the leading
`>` marker. The parser folds them into the preceding blockquote
paragraph as if the marker had been there. This is the "lazy"
continuation form and exists primarily for author convenience.

> The first line carries the marker as expected.
This second line has no `>` marker but is folded into the same
blockquote paragraph because CommonMark's lazy continuation rule
extends the quote until a blank line breaks it.
The third line is also lazy and joins the same paragraph.

After a blank line the blockquote ends, and the writer should emit
a single `<blockquote>` element wrapping one paragraph containing
all three lines (joined by soft breaks or spaces depending on the
writer's wrapping policy).
