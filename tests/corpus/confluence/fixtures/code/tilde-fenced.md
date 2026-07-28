---
test_corpus:
  authoring: markdown-first
  shapes:
  - code-block-tilde-fence
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081360/Tilde-fenced+code+block
  page_id: '1081360'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:33.840Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:34.233925+00:00'
---

# Tilde-fenced code block

CommonMark accepts two fence characters for code blocks: backtick
(```` ``` ````) and tilde (`~~~`). The two forms are interchangeable
in semantics — Confluence storage represents either as a code macro
— but the reader has to recognise both, and the writer's choice of
which to emit on the way back is a normalisation concern.

~~~
$ curl -s https://example.com/api | jq '.results[]'
{"id": 1, "name": "first"}
{"id": 2, "name": "second"}
~~~

The body above contains a backtick-quoted string inside a JSON
pipeline; tilde fences let the author write that without needing to
escape the inner backticks. A round-trip through Confluence storage
and back should preserve the contents verbatim regardless of which
fence the writer emits.
