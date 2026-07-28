---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-bullet
  - list-ordered
  - list-nested
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/163977/Nested+mixed+lists
  page_id: '163977'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:01.390Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:01.853981+00:00'
---

# Nested mixed lists

Bullet list with a nested ordered list inside one of its items:

- First top-level bullet
- Second top-level bullet contains a numbered sub-list:
  1. First sub-step
  2. Second sub-step
  3. Third sub-step
- Third top-level bullet, back at the outer level

Ordered list with a nested bullet list inside one of its items:

1. First top-level step
2. Second top-level step contains bullets:
   - Sub-bullet one
   - Sub-bullet two
   - Sub-bullet three
3. Third top-level step

Three levels of nesting:

- Level one
  - Level two
    - Level three
  - Back to level two
- Back to level one
