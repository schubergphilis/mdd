---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-task
  - task-list
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081450/Task+list
  page_id: '1081450'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:16:24.484Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:16:24.941007+00:00'
---

# Task list

GFM task lists are unordered lists whose items start with
`[ ]` (open) or `[x]` (done). Confluence storage maps each
checked / unchecked item onto the `<ac:task-list>` macro with
nested `<ac:task>` children carrying `<ac:task-status>` and
`<ac:task-body>` elements.

- [x] Draft the proposal
- [x] Circulate for review
- [ ] Incorporate feedback
- [ ] Publish v1
- [ ] Schedule the follow-up

The fixture mixes checked and unchecked items in a single list
so the round-trip verifies both states. The item bodies are
plain text — inline formatting inside task items lives in the
`task-list-nested.md` companion fixture.
