---
test_corpus:
  authoring: markdown-first
  shapes:
  - heading-setext-h1
  - heading-setext-h2
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1146947/Setext+h1+heading
  page_id: '1146947'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:22.689Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:23.164989+00:00'
---

Setext h1 heading
=================

A paragraph after a setext-form h1. CommonMark allows two heading
styles: ATX (`#` prefix) and setext (an underline of `=` for h1 or
`-` for h2 on the line below the title). Confluence storage uses
`<h1>` / `<h2>` in either case, so the round-trip should normalise
both forms to the same XHTML.

Setext h2 heading
-----------------

A paragraph after a setext-form h2. Note that setext headings cannot
go below level two — there is no `~` underline for h3 in CommonMark.
The reader should accept this shape and the writer is free to emit
either ATX or setext on the way back; what matters is that the
storage representation is identical.
