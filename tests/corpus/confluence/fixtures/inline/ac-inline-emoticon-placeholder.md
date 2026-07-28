---
test_corpus:
  authoring: markdown-first
  shapes:
  - ac-emoticon
  - ac-placeholder
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212417/Confluence+inline+ac+elements
  page_id: '1212417'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T17:26:43.961Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T17:26:44.343002+00:00'
---

# Confluence inline ac:* elements

`<ac:emoticon>` and `<ac:placeholder>` are inline Confluence elements
that have no canonical markdown form. The IR carries them as
`Emoticon` and `Placeholder` nodes. To populate them in a
markdown-first fixture we inject the raw storage XML through a
`confluence-xml` fence — that survives the round-trip and lets the
storage reader produce the typed nodes the coverage gate is looking
for.

```confluence-xml
<p>The team is on track <ac:emoticon ac:name="smile"/> and the
deadline is <ac:placeholder>insert date</ac:placeholder>.</p>
```

The IR-backed Confluence reader picks up the inline elements from the
storage snapshot and emits `Emoticon(name="smile")` plus
`Placeholder(content="insert date")` — exactly the two nodes Phase
6's coverage matrix flags as missing.
