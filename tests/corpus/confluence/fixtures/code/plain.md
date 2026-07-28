---
test_corpus:
  authoring: markdown-first
  shapes:
  - code-block
  - code-block-no-language
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/65915/Plain+code+block+no+language
  page_id: '65915'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:40.075Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:40.554074+00:00'
---

# Plain code block (no language)

A fenced code block with no language tag. Confluence storage
typically represents this as `<ac:structured-macro ac:name="code">`
with `<ac:plain-text-body><![CDATA[…]]></ac:plain-text-body>` and
no `<ac:parameter ac:name="language">`.

```
$ echo "hello"
hello
$ echo "world"
world
```

The CDATA section in storage must round-trip verbatim — the
content between the fences includes meaningful whitespace and
characters that would be HTML-escaped if treated as PCDATA.
