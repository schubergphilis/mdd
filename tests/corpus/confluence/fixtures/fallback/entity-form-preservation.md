---
test_corpus:
  authoring: markdown-first
  shapes:
  - fallback-entity-form
  - entity-form-preservation
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1212630/Fallback+entity+form+preservation
  page_id: '1212630'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:32:33.024Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:32:33.557454+00:00'
---

# Fallback — entity form preservation

Spec 032 §"Fallback fixtures" pins this fixture as the proof
that whitespace-preserving mode round-trips both the entity-
form spelling (`&hellip;`, `&mdash;`, `&ldquo;`) and the
Unicode-character spelling (`…`, `—`, `"`) of the same
codepoint without conflating them. Plan 106 D5 made
`entity_form` preservation universal in the writer; this
fixture exercises that promise.

The markdown-first body uses Unicode characters directly:

A sentence ending in an ellipsis…

A dash — used like a parenthetical — keeps its surrounding
spacing.

A "quoted phrase" uses curly double quotes.

The Confluence-first half lives in storage as named entities.
The IR's `Origin.entity_form` field carries the original
spelling so the writer can round-trip the right one:

```confluence-xml
<p>A sentence ending in an ellipsis&hellip;</p>
<p>A dash &mdash; used like a parenthetical &mdash; keeps its
surrounding spacing.</p>
<p>A &ldquo;quoted phrase&rdquo; uses curly double quotes.</p>
```

The fenced block's literal `&hellip;` etc. flow into the page
as storage entities; the prose above carries the same
characters as raw Unicode. The R1 preserving gate verifies
they round-trip byte-for-byte from their respective sources.
