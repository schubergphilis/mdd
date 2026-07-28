---
test_corpus:
  authoring: markdown-first
  shapes:
  - list-task
  - task-list-nested
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212493/Nested+task+list
  page_id: '1212493'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:16:26.831Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:16:27.261799+00:00'
---

# Nested task list

Task list items can contain nested sub-task lists. CommonMark's
indentation rules apply: indent a sub-list by two spaces under
its parent item's marker. Each level becomes its own
`<ac:task-list>` macro in Confluence storage, nested inside the
parent `<ac:task>`'s body.

- [x] Plan release
  - [x] Draft notes
  - [x] Get sign-off
- [ ] Ship release
  - [x] Cut branch
  - [ ] Run smoke tests
  - [ ] Publish artifacts
- [ ] Follow-up
  - [ ] Collect feedback
  - [ ] File next-iteration tickets

The two-level structure exercises the writer's recursion: each
nested `<ac:task-list>` carries its own children, and the parent
task's status is independent of the child statuses.
