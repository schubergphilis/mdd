---
test_corpus:
  authoring: markdown-first
  shapes:
  - blockquote-nested
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1081379/Nested+blockquotes
  page_id: '1081379'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:38.405Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:38.827368+00:00'
---

# Nested blockquotes

Blockquotes can nest. The number of leading `>` markers on a line
sets the nesting depth; Confluence storage represents this as
`<blockquote>` elements nested inside each other, one per depth
level.

> Outer quote, depth one.
>
> > Inner quote, depth two — a reply quoted inside the outer
> > author's text.
> >
> > > Deeper quote, depth three. Practical use of three-deep
> > > quoting is rare, but the parser must support it and the
> > > writer must emit three nested `<blockquote>` elements
> > > without collapsing them.
> >
> > Back to depth two for the closing thought.
>
> Closing line of the outer quote.

The round-trip should preserve the nesting depth at every line.
