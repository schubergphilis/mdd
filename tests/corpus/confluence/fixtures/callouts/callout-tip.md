---
test_corpus:
  authoring: markdown-first
  shapes:
  - callout-tip
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114259/Callout+tip+markdown-first
  page_id: '1114259'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:08.663Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:09.094394+00:00'
---

# Callout — tip (markdown-first)

The `:::callout-tip` fenced div is the markdown-first authoring
form of the Confluence tip callout. Spec 030 §"Fenced divs" pins
the syntax: three (or more) colons, the kind, a blank or content
line, then a matching close fence with the same colon count.

:::callout-tip
This tip body exercises the markdown reader's fenced-div plugin
end to end. The IR emits a `Callout(kind="tip")` block; the
Confluence writer maps it back to `<ac:structured-macro
ac:name="tip">…</ac:structured-macro>`.

The body can hold **bold**, _italic_, `inline code`, and even a
bulleted list:

- a child item
- another item with [a link](https://example.com)
:::

Trailing paragraph after the callout to confirm the close fence
terminates the macro and prose resumes at block scope.
