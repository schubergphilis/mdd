---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-info-card
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081534/Macro+info-card
  page_id: '1081534'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:27:40.715Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:27:41.201030+00:00'
---

# Macro — info-card

The `info-card` macro renders an inline card preview of a linked
resource. The body carries a fallback `<a>` element that
browsers without the card renderer fall back to.

```confluence-xml
<ac:structured-macro ac:name="info-card" ac:schema-version="1">
  <ac:parameter ac:name="url">https://example.com/team-page</ac:parameter>
</ac:structured-macro>
```

A trailing paragraph confirms the fence releases block scope so
the macro stands on its own line in storage.
