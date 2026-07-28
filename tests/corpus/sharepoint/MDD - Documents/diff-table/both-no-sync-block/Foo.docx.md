---
test_corpus:
  source: sharepoint
  diff_table_cell: first-sync both-present no-sync-block (docx wins)
  introduced: '2026-05-20'
---
First-sync fixture: both files present, no `sharepoint.sync` block yet. Sync should trust the docx, convert it, and stamp `update_office: false`.
