---
test_corpus:
  source: sharepoint
  diff_table_cell: office_now!=sync && md_now!=sync && update_office=false
  introduced: '2026-05-20'
sharepoint:
  sync:
    office_sha256_at_sync: '0000000000000000000000000000000000000000000000000000000000000000'
    md_sha256_at_sync: '0000000000000000000000000000000000000000000000000000000000000000'
    last_sync: '2026-05-20T00:00:00+00:00'
    converter: docling-docx
    converter_version: 2.92.0
    update_office: false
---
Both sides drifted; update_office is false so sync leaves both sources alone.
