---
test_corpus:
  authoring: markdown-first
  shapes:
  - image-external-url
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/131253/Image+referenced+by+external+URL
  page_id: '131253'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 3
  updated_at: '2026-05-11T19:39:12.206Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:39:12.740841+00:00'
---

# Image referenced by external URL

A paragraph containing a markdown image where the source is an
external `https://` URL. Confluence storage emits this as
`<ac:image><ri:url ri:value="…"/></ac:image>`.

![Markdown logo](https://upload.wikimedia.org/wikipedia/commons/thumb/4/48/Markdown-mark.svg/120px-Markdown-mark.svg.png)

The image rendering depends on Confluence's ability to fetch the
URL at render time. We use a small PNG from Wikimedia Commons
(stable URL, public-domain logo) because:

- SVG images via `ri:url` render inconsistently in Confluence
  Cloud — the editor often shows "Preview unavailable" even when
  the storage XHTML is well-formed.
- Confluence's content security configuration may block fetches
  from arbitrary domains; Wikimedia is broadly allowlisted.

For the round-trip fidelity test, the only invariant that matters
is that the URL is preserved verbatim in storage XHTML — the
visual render is a bonus, not the contract.
