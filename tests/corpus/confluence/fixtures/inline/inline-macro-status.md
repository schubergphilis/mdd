---
test_corpus:
  authoring: markdown-first
  shapes:
  - inline-macro
  - inline-macro-status
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212531/Inline+macro+status
  page_id: '1212531'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:25:20.127Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:25:20.566413+00:00'
---

# Inline macro — status

The `{{confluence:status ...}}` inline macro is the markdown-first
authoring form of Confluence's status pill. Spec 030 §"Inline
macros" pins the curly-brace syntax: `{{confluence:<name> key="value"
…}}` resolves to a `<ac:structured-macro ac:name="<name>">…
</ac:structured-macro>` with one `<ac:parameter>` per key.

Current project status: {{confluence:status title="On track" colour="Green"}}.
After yesterday's incident the build status flipped briefly to
{{confluence:status title="At risk" colour="Yellow"}} before
recovering. A failed migration would show
{{confluence:status title="Blocked" colour="Red"}} until
remediation completes.

Inline status pills compose with surrounding inline shapes —
**bold** prose around {{confluence:status title="In review" colour="Blue"}}
keeps the macro intact and the bold span unbroken.
