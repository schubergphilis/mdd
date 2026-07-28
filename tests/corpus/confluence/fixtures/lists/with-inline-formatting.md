---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-bullet
  - inline-strong
  - inline-em
  - inline-code
  - inline-link
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/66011/List+items+with+inline+formatting
  page_id: '66011'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:07.052Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:07.477154+00:00'
---

# List items with inline formatting

Bullet list where each item exercises a different inline span:

- Plain item, no formatting
- Item with **bold text** in the middle
- Item with *emphasis* and `inline code` together
- Item with an [external link](https://example.com) and trailing
  prose after the link
- Item with ***combined strong-emphasis*** spanning multiple words

The trailing-text-after-inline case in item four is structurally
similar to the bug fixed in mdd issue #71. This fixture catches
regressions in that area for non-`ac:link` inline elements.
