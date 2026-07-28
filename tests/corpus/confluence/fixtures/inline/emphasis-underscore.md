---
test_corpus:
  authoring: markdown-first
  shapes:
  - emphasis-underscore
  - strong-underscore
  - strong-emphasis-underscore
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114181/Emphasis+with+underscore+delimiters
  page_id: '1114181'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:53.022Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:53.471699+00:00'
---

# Emphasis with underscore delimiters

CommonMark accepts two delimiter characters for emphasis: asterisk
(`*`) and underscore (`_`). The two forms are semantically
interchangeable in word-bounded contexts — both produce `<em>` and
`<strong>` in the rendered output — but the underscore form has
intraword restrictions the asterisk form does not. Confluence
storage normalises both to `<em>` and `<strong>` regardless of the
source delimiter.

A paragraph with _underscore emphasis_, __underscore strong__, and
___underscore strong emphasis combined___. The intraword underscore
case foo_bar_baz must not produce emphasis because CommonMark only
recognises underscore emphasis at word boundaries; foo*bar*baz, in
contrast, _would_ produce emphasis with asterisks but not here.

The round-trip should preserve the rendered semantics. The writer
may normalise to a single delimiter form (typically asterisk) when
emitting markdown again — what matters is that the storage XHTML
matches between the markdown-first and storage-first round-trip
legs.
