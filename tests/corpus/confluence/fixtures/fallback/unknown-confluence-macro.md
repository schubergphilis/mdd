---
test_corpus:
  authoring: markdown-first
  shapes:
  - fallback-unknown-macro
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147246/Fallback+unknown+confluence+macro
  page_id: '1147246'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:32:25.909Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:32:26.355150+00:00'
---

# Fallback — unknown confluence macro

Spec 032 §"Fallback fixtures" pins this fixture as proof that
the `ConfluenceMacro` generic carrier round-trips an
`<ac:structured-macro>` whose `ac:name` is not in mdd's
recognised-macro registry. The macro stays opaque to the IR —
parameters and body ride through as a literal storage chunk.

```confluence-xml
<ac:structured-macro ac:name="bogus-macro" ac:schema-version="1">
  <ac:parameter ac:name="alpha">one</ac:parameter>
  <ac:parameter ac:name="beta">two</ac:parameter>
  <ac:rich-text-body>
    <p>The body is rich text inside an unrecognised macro. The
    reader does not introspect the children; the writer
    re-emits them byte-for-byte from the captured Origin.</p>
  </ac:rich-text-body>
</ac:structured-macro>
```

Trailing prose confirms the macro stands as its own block in
storage and the rest of the document continues at block scope.
