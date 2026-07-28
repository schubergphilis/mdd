# 016 - Confluence attachment conversion (pull-side)

**Purpose:** Extend `mdd confluence sync` and `export` so non-image attachments are run through the converter registry, producing markdown siblings.

**Status:** Implemented (2026-05-08)

## Introduction

During `mdd confluence sync` ([S14](S14-confluence-sync.md)) and `export` ([S09](S09-confluence-command.md)),
non-image attachments — `.docx`, `.pptx`, `.pdf`, `.svg` — are downloaded and
run through the converter registry ([S15](S15-converter-registry.md)), producing markdown
siblings inside the page's `<page-name>-attachments/` directory. The original
binary stays for fidelity; the markdown sibling lets readers grep, diff, and
review in the GitLab mirror without leaving the browser.

This is the **pull side** of the bidirectional Office story described in
research 002. The push side (rendering markdown to office-format attachments)
is [S17](S17-confluence-office-publishing.md).

## Requirements

**Attachment download**
- During `mdd confluence sync`, after the page body and image
  attachments are fetched (per [S09](S09-confluence-command.md)), enumerate **all**
  attachments via `GET /wiki/api/v2/pages/{id}/attachments`.
- For each attachment whose `mediaType` and/or filename extension is
  in the converter registry, download it to
  `<page-name>-attachments/<filename>`.
- Stream downloads (do not buffer the whole body) to support large
  PDFs.
- Honour `Retry-After` on 429 responses (overrides the [S09](S09-confluence-command.md)
  fixed schedule when the header is present, capped at 60s).
- Default concurrency cap of 4 in-flight downloads (config:
  `confluence.attachment_concurrency`).

**Attachment conversion**
- After download, call `converter_for(filename)` from [S15](S15-converter-registry.md).
  If a converter is found, run it; the converter writes
  `<filename>.md` (or its declared `output_suffix`) next to the
  original. If no converter is found, leave the binary alone.
- Cache by SHA-256 of the source file: skip conversion if the
  recorded `attachments_manifest` entry's SHA matches the current
  file *and* the converter's version hasn't changed.

**Attachment manifest**

S09's frontmatter `attachments` manifest grows a per-entry
`converted_to: <filename>` field when conversion ran. The manifest is
the authoritative cache; sync uses it to skip unchanged attachments.

```yaml
attachments:
  - filename: ArchitectureSpec.docx
    sha256: 9f86d081...
    version: 3
    converted_to: ArchitectureSpec.docx.md
    converter: docling-docx
    converter_version: "2.4.0"
  - filename: BudgetSheet.xlsx
    sha256: e3b0c442...
    version: 1
    # no converted_to: not in registry
```

**Push-side reference rewriting**
- When `mdd confluence update-page` ([S09](S09-confluence-command.md)) renders markdown
  back to storage XHTML, references to attachment files (e.g.
  `[Spec](attachments/ArchitectureSpec.docx)`) continue to point at
  the binary on Confluence — not the `.md` sibling. The `.md` is a
  mirror-side artifact only.
- Note: this spec does **not** rewrite SVG references. Per user
  decision, SVGs push to Confluence as `.svg`, not as `.svg.png`. The
  PNG sibling exists for Office-side renders only.

**Error handling**
- If a converter raises, sync logs the failure with the page ID and
  attachment filename, skips the attachment, and continues. The page
  itself is still synced; the attachment-converted markdown is simply
  absent for this run. Reported in the run summary; sync exits
  non-zero per [S14](S14-confluence-sync.md)'s best-effort policy.
- Conversion failures do not block subsequent attachments on the same
  page.

**Size limits**
- No hard cap by default; rely on Confluence's per-attachment 100 MB
  limit upstream.
- Add `--max-attachment-size <MB>` to skip downloads above the
  threshold, with a warning naming the attachment. Useful for
  bandwidth-constrained first runs.
- Per-attachment file size is shown in the run summary if it exceeds
  10 MB.

## Design Approach

- The hook into [S09](S09-confluence-command.md)'s existing
  `mdd.confluence.attachments` module is minimal: after each
  attachment download, look up `converter_for(local)` and run it if
  registered, updating the manifest with the converted output path
  and the converter's version.
- The conversion-needed predicate checks SHA mismatch, converter
  version bump, **and** missing output file — so a deleted markdown
  sibling regenerates next run.
- Bound concurrent downloads with `asyncio.Semaphore(N)` (or a thread
  pool of size N if we stay synchronous). Default 4. Conversion
  itself is synchronous and sequential — converters are CPU/IO mixed
  and don't benefit from concurrency at our scales.
- HTTP retry layer is a small extension to [S09](S09-confluence-command.md)'s client: on
  429, prefer the `Retry-After` header value over the static
  schedule, capped at 60 seconds, falling through to the schedule if
  the header is absent.
- One summary line per page after attachment sync (e.g.
  `12 attachments synced (3 converted, 1 skipped, total 18 MB)`),
  aggregated into [S14](S14-confluence-sync.md)'s structured
  run summary.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [009-confluence-command](S09-confluence-command.md) — confluence export/sync command
- [014-confluence-sync](S14-confluence-sync.md) — incremental sync and best-effort policy
- [015-converter-registry](S15-converter-registry.md) — pluggable converter registry
- [017-confluence-office-publishing](S17-confluence-office-publishing.md) — push side of the bidirectional Office story
- [024-svg-rasterization](S24-svg-rasterization.md) — SVG rasterization

## Out of scope

- Push-side rendering of markdown to office-format attachments (spec
  017 handles this).
- SVG rasterization to `.svg.png` ([S24](S24-svg-rasterization.md) handles this; this spec
  uses the converter registry which [S24](S24-svg-rasterization.md) will populate).
- Adopting an existing Confluence attachment as the canonical source
  (e.g. discovering a `.docx` and turning it into a markdown master
  with the office file as a derived render). One-shot migration
  feature; deferred.
- Live re-conversion when the converter version bumps but the file
  hasn't changed: handled by including `converter_version` in the
  cache key — next run picks it up automatically.
- Custom per-page converter overrides: registry dispatch is
  sufficient.
