---
test_corpus:
  authoring: markdown-first
  shapes:
  - entity-references-named
  - entity-references-numeric
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147059/Entity+references
  page_id: '1147059'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:50.732Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:51.144183+00:00'
---

# Entity references

CommonMark recognises both named entity references (`&amp;`,
`&copy;`, `&mdash;`) and numeric character references in decimal
(`&#8212;`) or hex (`&#x2014;`) form. The parser decodes these to
their Unicode equivalents during reading; preserving the original
spelling is a separate concern handled by Origin's `entity_form`.

Named entities: an ampersand &amp; rendered literally, a copyright
sign &copy;, an em-dash &mdash; in a sentence. Numeric decimal:
&#8212; should also become an em-dash. Numeric hex: &#x2014; same
character. The rare named form &hellip; should become a horizontal
ellipsis &#x2026; identical to the hex form.

Round-trip fidelity here depends on Origin retaining the
entity_form attribute on each Text node. Without it the writer
emits the decoded Unicode character; with it the original spelling
comes back through both legs.
