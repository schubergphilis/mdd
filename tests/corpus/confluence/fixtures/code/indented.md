---
test_corpus:
  authoring: markdown-first
  shapes:
  - code-block-indented
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212436/Indented+code+block
  page_id: '1212436'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:31.578Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:31.978972+00:00'
---

# Indented code block

CommonMark allows code blocks formed by indenting every line of
content with four spaces (or one tab), without any fence markers.
This is the older Markdown.pl style; many modern authors prefer
fenced blocks, but the indented form is still valid CommonMark and
should round-trip through Confluence storage as a code block.

    def greet(name):
        return f"hello, {name}"

    print(greet("world"))

The four-space indent is the only thing marking the block — the
blank line above and below are part of the paragraph framing, not
the code itself. Confluence storage typically represents this as
`<ac:structured-macro ac:name="code">` with a CDATA body, same as
the fenced form, with no language parameter unless the writer can
infer one from heuristics.
