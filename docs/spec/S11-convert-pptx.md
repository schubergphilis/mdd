# 011 - convert pptx

**Purpose:** Extend `mdd convert` to handle `.pptx` input, producing `<name>.pptx.md` output for round-trip with Quarto presentation projects.

**Status:** Implemented (2026-05-08)

## Introduction

This spec extends [S03](S03-convert-command.md) to handle PowerPoint
(`.pptx`) input alongside Word (`.docx`), producing `<name>.pptx.md` output
suitable for round-trip with Quarto presentation projects
([S04](S04-new-command.md)).

It also unblocks `.pptx` support in `mdd sharepoint`
([S10](S10-sharepoint-command.md)): with `.pptx` conversion in place,
the SharePoint exporter dispatches `.pptx` files the same way it dispatches
`.docx`.

## Requirements

- `mdd convert <path>` converts `.pptx` files the same way it already
  converts `.docx`: writes `<original>.pptx.md` in-place by default, or
  mirrors into `--dest-dir <dir>`.
- Incremental by default: skip `.pptx` files whose `.pptx.md` is newer
  than the source unless `--force`.
- `--file <path>` accepts a single `.pptx`; `--dry-run` lists work without
  writing; progress printed per file.
- Embedded images are extracted to
  `<original>.pptx-attachments/imageN.<ext>` and referenced from the
  markdown by relative path — same convention as `.docx`.
- Frontmatter (`title`, slide count, author, date) is pulled from `.pptx`
  core properties.

## Design Approach

**Library choice** — Docling for the body where it copes; `python-pptx`
for slide iteration, image and speaker-notes extraction, and as fallback
for shapes Docling can't handle.

**Slide-per-section output** — PowerPoint is slide-based; markdown is
flow-based. Each slide becomes an `## H2` section (named by slide title,
or `Slide N` if untitled), matching the Quarto presentation conventions
in [S04](S04-new-command.md)'s `simple-presentation.qmd`. Speaker
notes render as Quarto `::: notes` fenced divs so the same markdown
re-renders into a Quarto deck.

## Output shape

```markdown
---
title: My Deck
slides: 12
author: Leo Simons
date: 2026-05-08
---

## Slide 1 title

- Bullet
- Bullet

![](My-Deck.pptx-attachments/image1.png)

::: notes
Speaker notes for slide 1.
:::

## Slide 2 title

...
```

- Body shapes (text frames, bullet lists) render as paragraphs/lists.
- Tables render as Markdown tables when the shape supports it; otherwise
  preserved as fenced HTML.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [003-convert-command](S03-convert-command.md) — base convert command this spec extends
- [004-new-command](S04-new-command.md) — Quarto presentation conventions for output shape
- [010-sharepoint-command](S10-sharepoint-command.md) — SharePoint mirror that depends on `.pptx` conversion

## Out of scope

- Round-tripping markdown → PowerPoint (no `mdd convert --reverse`).
  Quarto's render path is the one-way authoring tool for PowerPoint.
- Slide layouts and master template extraction. The output is a single
  flat list of slides; layout fidelity belongs to Quarto, not the
  markdown export.
- Animations and slide transitions.
- Embedded video / audio (drop with warning).
