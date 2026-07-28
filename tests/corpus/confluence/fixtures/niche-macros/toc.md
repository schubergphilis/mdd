---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-toc
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212568/Macro+toc
  page_id: '1212568'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:27:45.417Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:27:45.911363+00:00'
---

# Macro — toc

The `toc` macro renders a generated table of contents from the
current page's headings. Parameters tune the rendering — heading
depth, output style, type (list vs flat). The macro has no
body; everything is in `<ac:parameter>` children.

```confluence-xml
<ac:structured-macro ac:name="toc" ac:schema-version="1">
  <ac:parameter ac:name="maxLevel">3</ac:parameter>
  <ac:parameter ac:name="minLevel">2</ac:parameter>
  <ac:parameter ac:name="type">list</ac:parameter>
  <ac:parameter ac:name="outline">false</ac:parameter>
</ac:structured-macro>
```

## Section A

A child heading so the TOC has something to render against.

### Sub-section A.1

A grandchild heading to test the maxLevel=3 parameter.

## Section B

Second top-level child.
