---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-attachments
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114373/Macro+attachments
  page_id: '1114373'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:28:05.812Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:28:06.253899+00:00'
---

# Macro — attachments

The `attachments` macro renders the current page's attachment
list. Parameters tune the columns shown and the sort order.
The macro has no body — Confluence resolves the attachment
inventory at render time.

```confluence-xml
<ac:structured-macro ac:name="attachments" ac:schema-version="1">
  <ac:parameter ac:name="patterns">.*\.pdf,.*\.png</ac:parameter>
  <ac:parameter ac:name="upload">false</ac:parameter>
  <ac:parameter ac:name="sortBy">date</ac:parameter>
  <ac:parameter ac:name="sortOrder">descending</ac:parameter>
</ac:structured-macro>
```

The fixture's page has no real attachments — the macro renders
an empty list. Storage still preserves the parameter set
verbatim.
