---
test_corpus:
  authoring: markdown-first
  shapes:
  - fallback-inline-html
  - raw-inline-html
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212604/Fallback+inline+HTML+element
  page_id: '1212604'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:32:30.684Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:32:31.202832+00:00'
---

# Fallback — inline HTML element

Spec 032 §"Fallback fixtures" pins this fixture as proof that
an inline-level HTML element with no first-class IR node
round-trips as `RawInline(format="html", …)`. CommonMark
permits inline raw HTML in any paragraph; the markdown reader
captures the open / content / close tags as a single
`RawInline` span and the writer re-emits them verbatim.

Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to interrupt the running
command. The <kbd>kbd</kbd> element is the semantic HTML tag
for keyboard input; CommonMark allows it inline and the IR
carries it through as raw HTML.

A second paragraph mixes <kbd>Esc</kbd> with **bold prose**,
*italic emphasis*, and `code` to confirm the inline parser
keeps each span distinct without collapsing the raw HTML span
into its neighbours.

Two raw inline shapes in a single line — <kbd>Tab</kbd> next
to <samp>shell output</samp> — exercise back-to-back
`RawInline` tokens and confirm whitespace handling between
adjacent raw elements.
