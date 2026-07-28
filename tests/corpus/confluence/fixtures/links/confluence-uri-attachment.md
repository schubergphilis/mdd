---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-confluence-attachment
  - confluence-uri-attachment
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114339/Synthetic+URI+confluence-attachment
  page_id: '1114339'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:28.879Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:29.316530+00:00'
---

# Synthetic URI — `confluence-attachment:`

Spec 030 §"Synthetic URIs" defines `confluence-attachment:<filename>`
as the markdown-first form for an attachment reference. The
reader resolves the URI to a `ConfluenceLink(target_kind=
"attachment", target="<filename>")` for link contexts, or to a
`ConfluenceImage(source_kind="attachment", …)` when the URI
appears inside a markdown image (`![alt](…)`). The writer maps
both back to `<ri:attachment ri:filename="…" />` in storage.

A textual attachment link:
[download the migration plan](confluence-attachment:migration-plan-v2.pdf).

An attachment image (rendered inline as the image macro):
![architecture diagram](confluence-attachment:architecture.png).

A cross-page attachment uses the `page` extra segment to point
into another page's attachment list:
[the legacy PDF](confluence-attachment:legacy.pdf;page=MDD/Old+Page).

A trailing paragraph confirms the URI parser releases control
after each closing `)`.
