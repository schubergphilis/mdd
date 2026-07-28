---
test_corpus:
  authoring: markdown-first
  shapes:
  - macro-jira
  - confluence-xml-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081562/Macro+jira
  page_id: '1081562'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:27:43.098Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:27:43.555900+00:00'
---

# Macro — jira

The `jira` macro embeds a live Jira issue link or filter. The
storage form carries the issue key (or a JQL filter) plus the
linked Jira application's `serverId`. Confluence's renderer
hits the linked Jira instance at view-time to fetch the
current summary and status.

```confluence-xml
<ac:structured-macro ac:name="jira" ac:schema-version="1">
  <ac:parameter ac:name="server">System Jira</ac:parameter>
  <ac:parameter ac:name="serverId">00000000-0000-0000-0000-000000000000</ac:parameter>
  <ac:parameter ac:name="key">MDD-123</ac:parameter>
</ac:structured-macro>
```

The fixture uses a synthetic all-zero `serverId` — no live Jira
is queried at render time. Round-trip preserves the parameter
values byte-for-byte.
