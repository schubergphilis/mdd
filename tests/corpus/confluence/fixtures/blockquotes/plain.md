---
test_corpus:
  authoring: markdown-first
  shapes:
  - blockquote
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98328/Plain+blockquote
  page_id: '98328'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:35.845Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:36.260341+00:00'
---

# Plain blockquote

A standard markdown blockquote. Confluence storage represents
this as `<blockquote>`, **not** as a callout macro
(`<ac:structured-macro ac:name="info|tip|note|warning">`). Callouts
require Confluence-first authoring via the editor — there is no
markdown syntax for them today.

> The single most important thing about a system's design is
> that it should be obviously correct, or obviously incorrect.
> The first kind of design is easy to maintain; the second kind
> is hard to maintain. There is no third kind that pretends to
> be the first.

The blockquote spans four lines in source; the round-trip should
preserve internal line breaks and the soft wrapping.
