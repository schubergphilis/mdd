---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-pagetree
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114392/Macro+pagetree
  page_id: '1114392'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:28:08.044Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:28:08.479127+00:00'
---

# Macro — pagetree

The `pagetree` macro renders a navigable tree of pages rooted
at a chosen page (or the space root). Parameters tune the
root, the rendering style, and the inclusion of search /
expand-all controls.

```confluence-xml
<ac:structured-macro ac:name="pagetree" ac:schema-version="1">
  <ac:parameter ac:name="root">
    <ac:link><ri:page ri:content-title="Home" /></ac:link>
  </ac:parameter>
  <ac:parameter ac:name="startDepth">1</ac:parameter>
  <ac:parameter ac:name="reverse">false</ac:parameter>
  <ac:parameter ac:name="sort">natural</ac:parameter>
  <ac:parameter ac:name="excerpt">false</ac:parameter>
  <ac:parameter ac:name="searchBox">true</ac:parameter>
  <ac:parameter ac:name="expandCollapseAll">true</ac:parameter>
</ac:structured-macro>
```

The fixture exercises a `<ri:page>` nested inside a parameter
body — a less-common shape than the flat scalar parameters
elsewhere in this batch.
