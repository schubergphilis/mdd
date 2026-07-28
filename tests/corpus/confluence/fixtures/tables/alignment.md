---
test_corpus:
  authoring: markdown-first
  shapes:
  - table
  - table-alignment
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114200/Table+with+per-column+alignment
  page_id: '1114200'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:16:19.179Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:16:19.609057+00:00'
---

# Table with per-column alignment

GFM extends CommonMark tables with per-column alignment markers on
the header separator row: `:---` is left-aligned (the default),
`---:` is right-aligned, and `:---:` is centered. Confluence
storage carries the alignment through to `<td>` / `<th>` styling.

| Left   | Right | Center |
| :----- | ----: | :----: |
| Alice  |    42 |  short |
| Bob    |   1.5 |  middle item |
| Charlie | 1000 |   end  |

The leading `:` on the first column and the trailing `:` on the
second column make those columns left- and right-aligned. The
third column has `:` on both sides, centering it. The data rows
themselves carry no alignment hints — the renderer derives them
from the separator row.
