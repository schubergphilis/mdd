---
test_corpus:
  authoring: markdown-first-with-raw-confluence
  shapes:
  - link-ri-attachment
  - link-ri-attachment-cross-page
  - link-inline-trailing-text
confluence:
  url: https://markdown.atlassian.net/wiki/spaces/MDD/pages/131404/Attachment+link+via+ac%3Alink
  page_id: '131404'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T20:51:40.237Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T20:51:51Z'
---

> **Confluence export**
>
> This page was exported from confluence page [Attachment link via ac:link](https://markdown.atlassian.net/wiki/spaces/MDD/pages/131404/Attachment+link+via+ac%3Alink)
> on 2026-05-11. Check Confluence for the most up-to-date version.


# Attachment link via ac:link

# Attachment link via ac:link

This fixture exercises the **true** `<ac:link>` with `<ri:attachment>`
inline reference — distinct from the `view-file` macro card that the
Confluence editor's paperclip-upload workflow produces (covered
separately by `niche-macros/view-file-macro.md`).

The Confluence UI doesn't make this shape easy to compose, so this
fixture is authored markdown-first with the inline reference written
out as a raw `{=confluence}` block. The reference points at the
attachment already uploaded to the "Attachment link" page (id
164069) via a `<ri:page ri:content-title="..."/>` child, making it a
**cross-page** attachment link.

See the file:

`<ac:link xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/repository/confluence/1.0"><ri:attachment ri:filename="attachment-sample.txt" ri:version-at-save="1"><ri:page ri:content-title="Attachment link" ri:version-at-save="1"/></ri:attachment><ac:link-body>attachment-sample.txt</ac:link-body></ac:link>`{=confluence}

for an example. And the prose continues after the link to exercise
the trailing-text-after-inline pattern (regression coverage for the
class of bug closed in #70/#71/#72).
