---
test_corpus:
  authoring: markdown-first
  shapes:
  - confluence-xml-fence
  - raw-block-confluence-storage
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114320/confluence-xml+fenced+code+block
  page_id: '1114320'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:24.439Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:24.903796+00:00'
---

# `confluence-xml` fenced code block

The ` ```confluence-xml ` fence is the markdown-first escape hatch
for embedding raw Confluence storage that has no first-class IR
node. Spec 030 §"Raw blocks" maps the fence to
`RawBlock(format="confluence-storage", …)`; the writer re-emits
the same fence in markdown and the raw XHTML body in Confluence
storage.

Below is a verbatim chunk of storage markup wrapped in the
fence. The IR carries the inner text byte-for-byte and the
writer re-emits it exactly:

```confluence-xml
<ac:structured-macro ac:name="info" ac:schema-version="1">
  <ac:rich-text-body>
    <p>This body is hand-authored storage markup. The
    markdown reader does <em>not</em> parse the children —
    it stores them in a RawBlock and round-trips bytes.</p>
  </ac:rich-text-body>
</ac:structured-macro>
```

A trailing paragraph confirms the fence closes cleanly and the
markdown writer resumes normal block scope.
