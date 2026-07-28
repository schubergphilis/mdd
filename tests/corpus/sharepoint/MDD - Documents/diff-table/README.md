---
test_corpus:
  source: sharepoint
  diff_table_cell: index
  introduced: 2026-05-20
---

# SharePoint sync diff-table fixtures

Each subfolder is a fixture pair (or single-side fixture, for the
first-sync cases) covering one cell of the [S18](../../../../../docs/spec/S18-sharepoint-sync.md)
diff table that the realistic site content does not naturally
exercise. Tests parse the `test_corpus.diff_table_cell` field in
each fixture's frontmatter to assert the cell→verdict mapping in
`mdd.sharepoint.diff.classify_pair()` is exhaustive.

The `office_sha256_at_sync` / `md_sha256_at_sync` values are chosen
deterministically:

- a 64-zero sentinel (`"0" * 64`) where the cell requires the stamped
  hash to **differ** from the live file (i.e. that side "changed since
  last sync");
- the actual current hash where the cell requires it to **match**
  (i.e. that side is "clean").

This makes the verdict reproducible across machines without
depending on Office, Docling, or Quarto being installed: the cells
are determined by the recorded vs. live hashes, both of which sync
computes locally.

| Cell | Folder |
|---|---|
| office_now != sync, md_now == sync | [`docx-changed/`](docx-changed/) |
| office_now == sync, md_now != sync, update_office=true | [`md-changed-update-true/`](md-changed-update-true/) |
| office_now == sync, md_now != sync, update_office=false (SKIP) | [`md-changed-update-false/`](md-changed-update-false/) |
| office_now != sync, md_now != sync, update_office=true (DIVERGED) | [`divergence/`](divergence/) |
| office_now != sync, md_now != sync, update_office=false (SKIP_MD_UPDATE) | [`skip-both-changed/`](skip-both-changed/) |
| first-sync, docx-only | [`docx-only-no-md/`](docx-only-no-md/) |
| first-sync, md-only | [`md-only-no-docx/`](md-only-no-docx/) |
| first-sync, both present, no sync block (docx wins) | [`both-no-sync-block/`](both-no-sync-block/) |

The "office_now == sync, md_now == sync → No-op" cell is covered by
the real-site fixtures at the corpus root (`Example-Word.docx` +
sibling, `Example-PowerPoint.pptx` + sibling, `Templated/*`,
`Markdown-First/*`).
