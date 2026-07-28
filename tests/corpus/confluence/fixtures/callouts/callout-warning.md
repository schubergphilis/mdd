---
test_corpus:
  authoring: markdown-first
  shapes:
  - callout-warning
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212512/Callout+warning+markdown-first
  page_id: '1212512'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:15.510Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:15.994766+00:00'
---

# Callout — warning (markdown-first)

The `:::callout-warning` fenced div maps to Confluence's
`warning` macro (red background). Warnings flag content the
reader must not miss — destructive operations, irreversible
choices, security caveats.

:::callout-warning
**Do not** proceed without a backup. The migration script
described below rewrites table schemas in place; recovery
without a backup requires restoring from yesterday's snapshot
and replaying all writes since.

Run `mise run backup-db` before invoking the migration.
:::
