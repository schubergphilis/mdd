---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-external
  - link-inline-trailing-text
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/65975/Multiple+inline+links+in+one+paragraph
  page_id: '65975'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:56.297Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:56.530261+00:00'
---

# Multiple inline links in one paragraph

A single paragraph with three external links interleaved with
prose. Two of them have text trailing immediately after the
closing bracket — the pattern that triggered mdd issues #70 and
#71 for `ac:link`. This fixture exercises the same trailing-text
case for ordinary `<a href>` elements.

Visit [Pandoc](https://pandoc.org), then read about
[Quarto](https://quarto.org/) and finally browse
[docling](https://docling-project.github.io/docling/) to compare
the three approaches. Each link is followed by punctuation,
whitespace, or further prose — the round-trip should preserve all
three.
