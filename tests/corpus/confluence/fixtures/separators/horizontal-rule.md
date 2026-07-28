---
test_corpus:
  authoring: markdown-first
  shapes:
  - horizontal-rule
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/164022/Horizontal+rule
  page_id: '164022'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:14.935Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:15.360212+00:00'
---

# Horizontal rule

Text above the rule.

---

Text below the rule. The markdown `---` becomes `<hr/>` in
Confluence storage. The round-trip should preserve the rule and
the paragraphs on either side without merging or losing the
separation.

Another section.

***

Yet another section, separated by a `***` form of horizontal rule
that markdown recognises equivalently. Confluence storage emits
the same `<hr/>` regardless of which markdown form was used.
