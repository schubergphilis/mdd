---
test_corpus:
  authoring: markdown-first
  shapes:
  - raw-html-block
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212474/Raw+HTML+block
  page_id: '1212474'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:03:00.084Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:03:00.538239+00:00'
---

# Raw HTML block

CommonMark allows raw HTML at the block level. A block-level HTML
element written at column zero, surrounded by blank lines, is
passed through to the rendered output verbatim. Confluence storage
may sanitise some tags (e.g. strip `<kbd>`, `<style>`, `<script>`)
but accepts most structural elements. The IR carries block-level
raw HTML as a `RawBlock` node with `format="confluence-storage"`.

The paragraph before the raw HTML.

<div class="note">
  <p>This is a raw HTML block. The <code>&lt;div&gt;</code> and
  inner <code>&lt;p&gt;</code> are passed through verbatim because
  CommonMark recognises them as block-level HTML at column zero.</p>
  <p>Confluence renders the block as-is. The round-trip should
  preserve the wrapping <code>&lt;div&gt;</code> and its class
  attribute.</p>
</div>

The paragraph after the raw HTML. Round-trip fidelity here depends
on the writer emitting the block on its own lines with blank-line
padding above and below; otherwise CommonMark's HTML-block rule
won't recognise the same shape on re-read.
