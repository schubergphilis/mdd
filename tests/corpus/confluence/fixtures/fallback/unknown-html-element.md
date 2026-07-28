---
test_corpus:
  authoring: markdown-first
  shapes:
  - fallback-unknown-html-block
  - raw-block-html
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1114430/Fallback+unknown+HTML+block+element
  page_id: '1114430'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:32:28.387Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:32:28.837236+00:00'
---

# Fallback — unknown HTML block element

Spec 032 §"Fallback fixtures" pins this fixture as proof that
a block-level HTML element with no first-class IR node
round-trips as `RawBlock(format="html", …)`. The CommonMark
parser recognises raw-HTML blocks starting at column zero; the
markdown reader maps those to `RawBlock` and the writer
re-emits them verbatim inside Confluence storage.

<details>
<summary>Click to expand the hidden section</summary>
<p>The body of a <code>&lt;details&gt;</code> element is hidden
by default in HTML renderers. Confluence storage carries the
element through unchanged, but its rich-text editor strips
the toggle behaviour at render time.</p>
<p>A second paragraph keeps the block multi-line so the round-
trip exercises whitespace preservation inside the raw HTML.</p>
</details>

A trailing paragraph confirms the raw-HTML block parser
terminates correctly on the closing `</details>` tag and
returns control to the document's block scope.
