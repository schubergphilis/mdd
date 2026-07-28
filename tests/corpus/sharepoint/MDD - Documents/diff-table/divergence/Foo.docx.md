---
test_corpus:
  source: sharepoint
  diff_table_cell: office_now!=sync && md_now!=sync && update_office=true
  introduced: '2026-05-20'
sharepoint:
  sync:
    office_sha256_at_sync: '0000000000000000000000000000000000000000000000000000000000000000'
    md_sha256_at_sync: '0000000000000000000000000000000000000000000000000000000000000000'
    last_sync: '2026-05-20T00:00:00+00:00'
    converter: docling-docx
    converter_version: 2.92.0
    update_office: true
---
Both sides drifted since the last sync. Render Foo.from-md.docx for manual port.
