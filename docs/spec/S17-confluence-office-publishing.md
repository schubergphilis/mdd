# 017 - Confluence office publishing (push-side)

**Purpose:** Render opted-in markdown pages to `.docx`/`.pptx` via Quarto and upload them as versioned Confluence attachments.

**Status:** Implemented (2026-05-09)

## Introduction

When a Confluence-mirrored markdown file opts in via frontmatter,
`mdd confluence sync` renders it to `.docx` (or `.pptx`) using Quarto
and uploads the result as a versioned attachment on the same Confluence
page. Confluence readers get a downloadable office-format copy that
always reflects the markdown master.

This is the **push side** of the bidirectional Office story from
research 002. The pull side (downloading and converting attachments)
is [S16](S16-confluence-attachment-conversion.md).

## Requirements

**Opt-in via frontmatter**
- A page is published with an office-format attachment when its
  frontmatter contains:
  ```yaml
  confluence:
    publish_office: docx          # or pptx; or both as a list
  ```
- Absent or empty → no office publish. This is per-page; no global
  default.
- Either `docx`, `pptx`, or `[docx, pptx]`. Other values are an
  error.

**Render via Quarto**
- Reuse the Quarto invocation pattern from [S04](S04-new-command.md) (`mdd new`):
  `quarto render <md> --to <docx|pptx> --reference-doc=<template>`.
- Reference template default: bundled with `mdd` under
  `templates/quarto/`. Override per-mirror via
  `confluence.publish_office_template_dir`.
- A `quarto` binary is a runtime dependency; if absent, sync skips
  the office-publish step for the page and warns loudly (don't
  silently swallow).

**Attachment naming**
- The attachment is named using the [S09](S09-confluence-command.md) sanitiser: same rule
  used for the page's `.md` filename, with `.docx` or `.pptx`
  suffix appended.
- Filename collisions on the page (e.g. a user-uploaded `Foo.docx`
  already exists) are a hard error. The user must rename one in
  Confluence before sync can publish.

**Upload as versioned attachment**
- Use the v1 multipart endpoint ([S09](S09-confluence-command.md)). Same-named upload
  creates a new version; Confluence retains prior copies in
  per-attachment version history.
- Attachment manifest in frontmatter records the published file's
  SHA-256 and version number.

**Cache to avoid redundant renders**
- Render is expensive (Quarto + pandoc). Skip it if the source
  markdown's SHA-256, the reference template's hash, and the Quarto
  version all match what's recorded.
- Cache state lives in frontmatter:
  ```yaml
  confluence:
    publish_office: docx
    publish_office_state:
      docx:
        source_sha256: 9f86d081...
        template_sha256: e3b0c442...
        quarto_version: "1.6.0"
        attachment_filename: My-Page.docx
        attachment_sha256: 1a2b3c...
        attachment_version: 4
  ```

**Body link to the attachment**
- After upload, the rendered Confluence storage XHTML gets a small
  callout near the top of the body:
  ```html
  <p><sub><em>Download as <a
      href="<attachment-url>"><filename>.docx</a>
      (this attachment is generated from the markdown source)</em></sub></p>
  ```
- Idempotent: re-runs detect the existing callout (by string) and
  replace it. Same strip-then-insert pattern as the MDD footer in
  [S09](S09-confluence-command.md). If `publish_office: [docx, pptx]`, both links
  appear in one line.

**Error handling**
- A Quarto render failure for one page does not stop sync; the page
  is logged in the failure summary and the rest of sync continues
  ([S14](S14-confluence-sync.md) best-effort policy).
- Upload 5xx / 429 is retried per [S09](S09-confluence-command.md)'s retry layer with
  [S16](S16-confluence-attachment-conversion.md)'s `Retry-After` honouring.

## Design Approach

**Reverse converter** — Quarto rendering is exposed as a reverse
converter (registered in [S15](S15-converter-registry.md)'s `REVERSE_CONVERTERS`) so any
caller can use it; the Confluence-specific wiring (cache check,
upload, callout insertion) lives separately.

**Render-and-upload flow** (per page with `publish_office`):
hash source → check cache → render to temp file → hash output (skip
upload if byte-identical to cached) → upload via v1 multipart →
update frontmatter cache → strip/insert body callout.

**Concurrency** — renders are CPU-heavy and run sequentially;
uploads share the [S16](S16-confluence-attachment-conversion.md) attachment concurrency cap of 4.

**Reference template hash** — hashed into the cache key, so a
template change triggers re-render of all pages that use it.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [004-new-command](S04-new-command.md) — Quarto invocation pattern reused here
- [009-confluence-command](S09-confluence-command.md) — sanitiser, v1 upload, retry layer, MDD footer pattern
- [015-converter-registry](S15-converter-registry.md) — REVERSE_CONVERTERS registry
- [016-confluence-attachment-conversion](S16-confluence-attachment-conversion.md) — pull side; Retry-After honouring; attachment concurrency cap

## Out of scope

- Two-way sync of the office attachment back into the markdown.
  The office file is one-way derived; users edit markdown.
- Customising Quarto render flags per page beyond the reference
  template. (Page-level rendering hints can come later if needed.)
- Adopting an existing Confluence-side `.docx` as the canonical
  source. Out of scope (deferred from [S16](S16-confluence-attachment-conversion.md)).
