---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-linkify
  - linkify
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147130/Linkify+bare+URLs
  page_id: '1147130'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:16:29.000Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:16:29.424753+00:00'
---

# Linkify bare URLs

GFM's "autolink extension" (sometimes called linkify) promotes a
bare URL appearing in running prose into a clickable link without
requiring CommonMark-style `<https://…>` angle brackets or
`[label](url)` syntax. Confluence storage renders this as a plain
`<a href="…">…</a>` whose text matches the href.

Visit https://example.com for the project home page, or look at
https://example.org/path/to/file.html for a deep link with a
fragment like https://example.net/api#section-2.

Bare URLs also work mid-sentence: the spec at
https://commonmark.org/ defines the baseline, and the GFM
extensions live at https://github.github.com/gfm/. Trailing
punctuation should not be folded into the link — see
https://example.com, which keeps the comma outside the href.
