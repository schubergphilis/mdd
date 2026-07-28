---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-roadmap
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114411/Macro+roadmap-planner
  page_id: '1114411'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:28:10.871Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:28:11.305642+00:00'
---

# Macro — roadmap-planner

The `roadmap` (sometimes `roadmap-planner`) macro renders a
visual timeline with lanes, bars, and markers. The storage
form carries the entire roadmap configuration as a JSON-style
parameter blob — the macro is opaque to anything other than
Confluence's own renderer.

```confluence-xml
<ac:structured-macro ac:name="roadmap" ac:schema-version="1">
  <ac:parameter ac:name="title">Q3 milestones</ac:parameter>
  <ac:parameter ac:name="source">{"timeline":{"startDate":"2026-07-01","endDate":"2026-09-30"},"lanes":[{"title":"Backend","bars":[{"title":"Migrate auth","startDate":"2026-07-01","endDate":"2026-08-15","color":"Blue"}]},{"title":"Frontend","bars":[{"title":"New dashboard","startDate":"2026-08-01","endDate":"2026-09-15","color":"Green"}]}],"markers":[{"date":"2026-09-01","title":"Beta launch"}]}</ac:parameter>
</ac:structured-macro>
```

The JSON blob is verbatim — round-trip must preserve it
byte-for-byte through the `confluence-xml` fence's
`RawBlock(format="confluence-storage")` carrier.
