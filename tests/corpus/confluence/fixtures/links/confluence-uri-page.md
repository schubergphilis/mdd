---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-confluence-page
  - confluence-uri-page
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147191/Synthetic+URI+confluence-page
  page_id: '1147191'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:26.642Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:27.071917+00:00'
---

# Synthetic URI — `confluence-page:`

Spec 030 §"Synthetic URIs" defines `confluence-page:<space>/<title>`
as the markdown-first form for a Confluence page link. The
markdown reader resolves the URI to a `ConfluenceLink(target_kind=
"page", …)` node; the writer maps it back to
`<ac:link><ri:page ri:space-key="…" ri:content-title="…" /></ac:link>`
in storage.

Bare in-space link: [the project overview](confluence-page:MDD/Home).

Cross-space link with the space key spelled out:
[external project home](confluence-page:OTHER/External+Home).

A page link with an anchor segment encoded as a
semicolon-delimited extra:
[the API section](confluence-page:MDD/API+Reference;anchor=auth-flow).

A trailing paragraph confirms the inline link parser releases
control after the closing `)`.
