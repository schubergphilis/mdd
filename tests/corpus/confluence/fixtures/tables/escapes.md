---
test_corpus:
  authoring: markdown-first
  shapes:
  - table
  - table-escapes
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114219/Table+with+escaped+pipe+in+cells
  page_id: '1114219'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:16:21.564Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:16:21.991587+00:00'
---

# Table with escaped pipe in cells

GFM treats `|` as the cell separator, so a literal pipe inside a
cell must be backslash-escaped (`\|`). Confluence storage drops
the backslash and stores the pipe as plain text inside the
`<td>`, so the round-trip needs to re-introduce the escape when
the IR is rewritten back to markdown.

| Operator | Meaning         | Example      |
| -------- | --------------- | ------------ |
| `\|`     | bitwise OR      | `a \| b`     |
| `\|\|`   | logical OR      | `a \|\| b`   |
| `&`      | bitwise AND     | `a & b`      |

A second escape pair appears in prose too: the regex alternation
`foo\|bar` parses as a single text run, not two cells. The
fixture exercises both contexts so the writer can verify it
re-emits the backslash whenever a literal `|` would otherwise be
ambiguous.
