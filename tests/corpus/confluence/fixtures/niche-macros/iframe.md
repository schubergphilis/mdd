---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-iframe
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081581/Macro+iframe+creating
  page_id: '1081581'
  space_key: MDD
  space_id: '131077'
  parent_id: null
  status: current
  version: 2
  exported_at: '2026-05-13T19:30:52.907760+00:00'
  updated_at: '2026-05-13T19:30:52.460Z'
  updated_by: Leo-Bot Simons
---

# Macro — iframe

The "iframe" / widget-connector macro embeds an external page
inside a page. On Confluence Cloud the canonical storage form
is the `widget` macro carrying the embedded URL — the legacy
`iframe` macro name was retired in favour of Atlassian's smart-
embed system, so the storage shape below is what current Cloud
serialises.

```confluence-xml
<ac:structured-macro ac:name="iframe-embed" ac:schema-version="1">
  <ac:parameter ac:name="src">https://example.com/embed/dashboard</ac:parameter>
  <ac:parameter ac:name="width">800</ac:parameter>
  <ac:parameter ac:name="height">600</ac:parameter>
  <ac:parameter ac:name="frameborder">0</ac:parameter>
</ac:structured-macro>
```

Trailing prose confirms the macro stands inline in storage with
no body content. The iframe-shaped fixture is part of the
spec-032 niche-macro breadth set even though Confluence Cloud
itself rejects the legacy `iframe` macro name at storage
ingestion — see commit message for details.
