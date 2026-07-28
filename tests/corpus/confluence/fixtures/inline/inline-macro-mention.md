---
test_corpus:
  authoring: markdown-first
  shapes:
  - inline-macro
  - inline-macro-mention
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147164/Inline+macro+mention
  page_id: '1147164'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:22.290Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:22.729257+00:00'
---

# Inline macro — mention

User mentions in Confluence appear inline as `@name` chips that
link to the user's profile. The markdown-first form uses the
`{{confluence:mention account-id="…"}}` inline-macro syntax,
which the IR rewrites to a `<ac:link><ri:user
ri:account-id="…" /></ac:link>` in storage.

Assigned to {{confluence:mention account-id="712020:4b369b3c-df48-4aaf-90ad-a359e1f809ef"}}
for review.

A line that mixes a mention with prose:
{{confluence:mention account-id="557058:738d4176-8fd3-4b84-92d8-245731e9dfd9"}}
asked about the migration plan in last week's sync, and
{{confluence:mention account-id="712020:4b369b3c-df48-4aaf-90ad-a359e1f809ef"}}
followed up with a draft response.

The fixture uses real bot/user account IDs from this test
tenant; the resolved display names appear at render time and
are not part of the round-trip.
