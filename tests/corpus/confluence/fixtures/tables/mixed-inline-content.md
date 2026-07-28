---
test_corpus:
  authoring: markdown-first
  shapes:
  - table
  - inline-strong
  - inline-em
  - inline-code
  - inline-link
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/131305/Table+with+mixed+inline+content+in+cells
  page_id: '131305'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:23:17.672Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:23:18.084351+00:00'
---

# Table with mixed inline content in cells

Each cell exercises a different inline span shape. The round-trip
should preserve the inline structure inside `<td>` / `<th>` without
collapsing the spans or losing the cell boundaries.

| Plain | Bold       | Emphasis  | Code        | Link                                     |
| ----- | ---------- | --------- | ----------- | ---------------------------------------- |
| one   | **bold**   | *italic*  | `code`      | [external](https://example.com)          |
| two   | **strong** | *italics* | `inline()`  | [another link](https://example.org/path) |
| three | **a b c**  | *x y z*   | `f(x, y)`   | [trailing text](https://example.net) too |
