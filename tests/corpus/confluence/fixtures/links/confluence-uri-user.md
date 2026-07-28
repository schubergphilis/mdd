---
test_corpus:
  authoring: markdown-first
  shapes:
  - link-confluence-user
  - confluence-uri-user
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147210/Synthetic+URI+confluence-user
  page_id: '1147210'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:31.079Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:31.513536+00:00'
---

# Synthetic URI — `confluence-user:`

Spec 030 §"Synthetic URIs" defines `confluence-user:<accountId>`
as the markdown-first form for a user-link node — distinct from
the `{{confluence:mention}}` inline macro because this is a
linked element rather than a chip. The reader resolves the URI
to a `ConfluenceLink(target_kind="user", target="<accountId>")`;
the writer maps it back to
`<ac:link><ri:user ri:account-id="…" /></ac:link>` with the
link-body coming from the markdown link text.

Standalone user link:
[Leo-Bot Simons](confluence-user:712020:4b369b3c-df48-4aaf-90ad-a359e1f809ef).

Mid-paragraph user link to the human account:
the migration was driven by
[Leo Simons](confluence-user:557058:738d4176-8fd3-4b84-92d8-245731e9dfd9),
who also wrote the post-mortem.

Two user links in a single line to confirm the inline parser
does not collapse them:
[bot](confluence-user:712020:4b369b3c-df48-4aaf-90ad-a359e1f809ef) and
[human](confluence-user:557058:738d4176-8fd3-4b84-92d8-245731e9dfd9)
both appear on the activity feed.
