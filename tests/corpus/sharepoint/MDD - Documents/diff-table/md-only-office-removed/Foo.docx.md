---
test_corpus:
  source: sharepoint
  diff_table_cell: office removed upstream (md synced from office, no docx sibling, update_office=false)
  introduced: '2026-09-24'
sharepoint:
  sync:
    office_sha256_at_sync: 5eeb9a0fa8e40716ccbbd0f29c3019f248258b0e9f27c41f0e1e990681d5fa95
    md_sha256_at_sync: '0000000000000000000000000000000000000000000000000000000000000000'
    last_sync: '2026-09-24T00:00:00+00:00'
    converter: docling-docx
    converter_version: 2.92.0
    update_office: false
---
This markdown was synced from a `.docx` that has since been removed in SharePoint. With `update_office: false` the pair is reported, not rendered back.
