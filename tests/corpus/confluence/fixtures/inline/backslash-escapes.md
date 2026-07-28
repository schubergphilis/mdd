---
test_corpus:
  authoring: markdown-first
  shapes:
  - backslash-escapes
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081405/Backslash+escapes
  page_id: '1081405'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:48.487Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:48.880482+00:00'
---

# Backslash escapes

CommonMark allows the author to escape any ASCII punctuation
character with a leading backslash. The parser strips the
backslash and treats the following character as a literal — so
`\*` is a literal asterisk, not the start of an emphasis run.
Confluence storage represents the escaped character as the literal
text; the leading backslash does not survive.

A literal asterisk: \*. A literal underscore: \_. A literal
backtick: \`. A literal backslash: \\. A literal hash: \#. A
literal pipe: \|. A literal bracket pair: \[ and \].

The round-trip must reproduce the literal characters in the
Confluence storage output. On the way back to markdown, the writer
is free to re-escape only the characters that would otherwise be
ambiguous in context — over-escaping introduces visual noise that
diff-based round-trip tests catch.
