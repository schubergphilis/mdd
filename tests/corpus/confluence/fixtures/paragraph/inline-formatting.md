---
test_corpus:
  authoring: markdown-first
  shapes:
  - paragraph
  - inline-strong
  - inline-em
  - inline-code
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98431/Inline+formatting
  page_id: '98431'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:09.697Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:10.115437+00:00'
---

# Inline formatting

A single paragraph that exercises every inline span the markdown
reader produces: **strong text**, *emphasis*, ***strong emphasis
combined***, and `inline code` with a literal backtick `` ` `` inside
it. The round-trip should preserve each span and the spacing between
them without introducing stray whitespace or escape characters.

Confluence storage represents these as `<strong>`, `<em>` (sometimes
nested for combined emphasis), and `<code>`. The fixture checks that
the storage emission matches what Confluence's editor would write
when the same span is composed in the UI.
