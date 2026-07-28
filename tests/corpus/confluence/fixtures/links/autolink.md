---
test_corpus:
  authoring: markdown-first
  shapes:
  - autolink-uri
  - autolink-email
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081424/Autolinks
  page_id: '1081424'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:55.383Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:55.786944+00:00'
---

# Autolinks

CommonMark autolinks are URIs or email addresses wrapped in angle
brackets without any link text. The parser emits a link whose text
equals the URI; Confluence storage represents this as a plain
`<a href="…">…</a>` with matching text and href. Autolinks are the
shortest possible link form in CommonMark.

A URI autolink: <https://example.com/path?q=1&r=2>. An email
autolink: <noreply@example.com>. Mixed in prose: visit
<https://markdown.atlassian.net> for the test tenant, or contact
<bot@leosimons.com> for credentials questions.

Round-trip should preserve the autolink form rather than promoting
it to a full `[text](url)` link, because the storage XHTML in both
cases is `<a href="X">X</a>`, and any writer that emits
`[https://example.com](https://example.com)` adds visual noise the
reader cannot distinguish from the autolink shape.
