---
test_corpus:
  authoring: markdown-first
  shapes:
  - image-inline
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114113/Inline+image+markdown+form
  page_id: '1114113'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T17:26:41.696Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T17:26:42.085629+00:00'
---

# Inline image (markdown form)

A bare markdown image literal — `![alt](https://example/x.png)` —
round-trips as an `Image` node when the source is a URL Confluence
keeps as a plain `<img>` (rather than rewriting to an `<ac:image>`
macro).

![mdd logo](https://www.example.com/themes/custom/sbpv2/logo.svg)

This is the markdown-first counterpart to the existing
`images/external-url.md` fixture, which is authored through the
Confluence UI and produces `<ac:image>` instead. Having both keeps
the corpus honest about which markdown forms become which Confluence
shapes.
