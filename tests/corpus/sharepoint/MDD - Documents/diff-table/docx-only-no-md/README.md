---
test_corpus:
  source: sharepoint
  diff_table_cell: first-sync docx-only (no md sibling)
  introduced: 2026-05-20
---
First-sync fixture: `Foo.docx` has no `.md` sibling. Sync should run the
converter and stamp `update_office: false`.
