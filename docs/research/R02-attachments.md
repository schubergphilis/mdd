# 002 - Attachment conversion and bidirectional Office sync

**Status:** Research notes. Not an implementation spec.

**Problem brief.** Two related but distinct questions:

1. **Confluence attachments.** Many Confluence pages carry `.docx`,
   `.pptx`, and `.pdf` attachments. The current spec 009 model treats
   attachments as opaque image blobs only. We want to download
   non-image attachments too, run them through the existing
   `mdd convert` pipeline (Docling for `.docx`/`.pdf`; spec 011 for
   `.pptx`), and end up with markdown alongside the page. We also
   want to consider the reverse: render `.qmd`/`.md` → `.docx`/`.pptx`
   via Quarto and re-upload the office files as new attachment
   versions, so Confluence readers always have a downloadable
   office-format copy that matches the markdown master.

2. **SharePoint bidirectional sync.** SharePoint sites have `.docx`/
   `.pptx` files edited frequently by colleagues who don't use `mdd`.
   We want a `sharepoint sync` command (analogous to spec 014's
   `confluence sync`) that keeps `.md`/`.qmd` and `.docx`/`.pptx`
   in step *without* implementing office-format diff/merge. When both
   sides diverge, surface the conflict to the user and let them
   resolve it manually in the office app.

This document captures findings on Confluence's attachment API,
relevant Atlassian Cloud limits, a proposed converter-plugin
abstraction, the bidirectional Confluence model, and the SharePoint
sync model with divergence detection. It deliberately stops short of
prescribing a CLI surface, exact frontmatter, or commit-message
shapes — those belong in follow-up implementation specs.

## Confluence attachment API

### Capability summary

| Operation                    | API                                                           | Notes                                                |
|------------------------------|---------------------------------------------------------------|------------------------------------------------------|
| List attachments on a page   | `GET /wiki/api/v2/pages/{id}/attachments`                     | v2; paginated; returns `id`, `title`, `mediaType`, `fileSize`, `version`, `downloadLink` |
| Get attachment metadata      | `GET /wiki/api/v2/attachments/{attachmentId}`                 | v2                                                  |
| List attachment versions     | `GET /wiki/api/v2/attachments/{attachmentId}/versions`        | v2                                                  |
| Download attachment binary   | `GET <downloadLink>` (signed URL from metadata response)      | The `downloadLink` is fully-qualified and short-lived |
| Upload new attachment        | `POST /wiki/rest/api/content/{pageId}/child/attachment`       | **v1 only**; multipart/form-data; `X-Atlassian-Token: nocheck` header required |
| Upload new version of existing attachment | same v1 endpoint, with `?minorEdit=true&comment=...` and matching `file` filename | Confluence keys by filename within page |
| Delete attachment            | `DELETE /wiki/rest/api/content/{attachmentId}`                | v1                                                  |

The mixed v1/v2 story is unchanged from spec 009: read on v2, write on
v1. Spec 009 already plans for this and recommends encapsulating the
choice inside `mdd.confluence.client`.

### Practical observations

- **Attachments are page-scoped, keyed by filename.** Two different
  attachments on the same page with the same filename cannot coexist;
  re-uploading the same filename creates a new *version* of the same
  attachment. This is the basis of the version-replace flow we want
  for the office-file publish path.
- **`downloadLink` URLs are signed and short-lived** (typically minutes
  to hours). Capture and use them within the same sync run; do not
  cache them across runs.
- **Body references attachments by filename**, not ID, in storage XHTML
  (`<ri:attachment ri:filename="Foo.docx"/>`). This means rename
  detection within a page is trivial (filename change = different
  attachment from the API's perspective).
- **Versioning is per-attachment**, with full history retained. Old
  versions are downloadable. We don't need to retain old binary copies
  in the mirror; git history of the rendered markdown plus
  Confluence's own version history covers it.
- **`fileSize` is in the metadata response**, so we can decide whether
  to download a given attachment without first fetching its bytes —
  important if we want a `--max-attachment-size` knob.

### Size limits

- **Per-attachment cap:** 100 MB by default on Cloud, configurable
  per-instance. Assume 100 MB until proven otherwise for a given
  instance; surface a clean error on 413 / 400 with size hint.
- **No multipart-upload protocol** in the REST API. A 90 MB upload is a
  single 90 MB POST. There is no resume-from-byte-N. A connection drop
  mid-upload means starting over.
- **Total space storage** is governed by the Confluence plan, not by
  the API. Out of scope for `mdd`.

**Practical implication:** for office files on a typical page
the size is well under 100 MB (a handful of MB). For PDFs of large
slide decks or scan-heavy documents, individual attachments can hit
50-100 MB. We should:

- Stream uploads/downloads (httpx supports this) rather than loading
  the file fully into memory.
- Surface the file size in the run summary so users see when a sync
  is dominated by one big file.
- Not hard-cap by default; offer a `--max-attachment-size` flag for
  users who want to skip large files in initial bulk syncs.

### Rate limits

Atlassian Cloud uses a **cost-based rate limit** model rather than a
fixed req/sec cap:

- Each user has a per-second budget. Budgets vary by plan (Free is
  the most constrained; Premium / Enterprise the loosest). Empirically
  for Standard plans the steady-state ceiling is in the order of
  ~50 req/sec per user, but bursts can be much higher.
- Each endpoint has a "cost". Read endpoints are cheap; multipart
  attachment uploads are among the most expensive.
- Exceeded budget → HTTP 429 with `Retry-After` (seconds).
- There is also a **concurrency cap per user** (typically ~10
  simultaneous in-flight requests). Exceeding this returns 429 even
  if the per-second budget is fine.

### Backoff and throttling: do we need more than spec 009 has?

Spec 009 already specifies:
- Retry on 429, 503, any 5xx, `ConnectionError`
- Exponential backoff (1s, 2s, 4s, 8s, 16s)
- Max 5 attempts
- No retry on other 4xx

That's enough for *correctness*: a sync run will eventually get
through, even on a saturated plan. But for *throughput* on
attachment-heavy syncs, we want two additions:

1. **Honour `Retry-After` when present.** Spec 009 says exponential
   backoff with fixed schedule. When the server tells us how long to
   wait via the header, prefer that to the schedule. Cap to a sane
   maximum (e.g. 60s) to avoid pathological waits.

2. **Self-imposed concurrency cap.** Cap concurrent in-flight
   requests at, e.g., 4 by default — well below the API's ~10 cap so
   we never hit it incidentally. A simple `asyncio.Semaphore` or a
   thread-pool-of-N covers it. Exposed as `--concurrency N` for
   power users who have looser limits.

3. **Rate budget pacing (optional).** A token-bucket limiter capping
   sustained throughput to e.g. 10 req/sec, regardless of how fast the
   server responds. This prevents one `mdd` run from monopolising a
   user's budget and breaking concurrent UI usage. Probably not needed
   for v1 — runs at the sizes we expect are unlikely to saturate the
   budget — but worth keeping in mind.

**Recommendation.** Add `Retry-After` honouring and a default
concurrency cap of 4 to spec 009's retry layer. Skip token-bucket
pacing for now; revisit if real users report problems.

## File-type → converter abstraction

Today, conversion logic lives inside `mdd convert` (`src/mdd/commands/
convert.py`) and is dispatched implicitly by extension. Specs 010 and
011 already plan to extend it to `.pdf` and `.pptx`. With Confluence
sync wanting to consume the same conversions, the dispatch logic
should be promoted to a small **registry** so callers from outside
the `convert` command can reuse it.

### Proposed shape

```python
# src/mdd/converters/__init__.py
class Converter(Protocol):
    extensions: tuple[str, ...]      # e.g. (".docx",)
    output_suffix: str               # e.g. ".docx.md"

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult: ...

class ConvertResult:
    output_path: Path
    attachments_dir: Path | None     # extracted images
    metadata: dict                   # frontmatter dict (title, etc.)
    warnings: list[str]

# Registry, keyed by extension (lowercased, with leading dot).
CONVERTERS: dict[str, Converter] = {
    ".docx": DocxConverter(),
    ".pptx": PptxConverter(),     # spec 011
    ".pdf":  PdfConverter(),
}

def converter_for(path: Path) -> Converter | None:
    return CONVERTERS.get(path.suffix.lower())
```

### What this enables

- `mdd convert` becomes a thin wrapper that walks a tree and calls
  `converter_for(path).convert(...)`.
- `mdd confluence sync` can call `converter_for(attachment.filename)`
  to convert downloaded attachments into `.md` siblings of the page.
- `mdd sharepoint sync` (proposed below) does the same for files
  found in the OneDrive tree.
- New file types (e.g. `.xlsx`, `.odt`) become a one-file addition,
  not a cross-cutting change to every command.

### Reverse converters (Markdown → Office)

For the bidirectional flows, we also need the inverse:

```python
class ReverseConverter(Protocol):
    target_extension: str            # ".docx" or ".pptx"

    def render(self, md_path: Path, *, dest: Path) -> RenderResult: ...

REVERSE_CONVERTERS: dict[str, ReverseConverter] = {
    ".docx": QuartoDocxRenderer(),
    ".pptx": QuartoPptxRenderer(),
}
```

Both reverse converters shell out to `quarto render <md> --to docx`
(or `--to pptx`) under the hood. That assumes the user has `quarto`
installed, which is already the case for spec 004 (`mdd new`). PDF
reverse rendering is via the same path (`--to pdf`) but is less
useful; defer.

### Where this lives

- `src/mdd/converters/` — package containing all converter
  implementations. Today's `mdd.commands.convert` calls into it.
- The Confluence and SharePoint commands import the registry; they
  don't reach into specific converters.

## Bidirectional Confluence: Office attachments derived from markdown

### The model

- The mirror's `.md` (or `.qmd`) is the source of truth.
- For pages that should also have a downloadable office-format copy,
  set `confluence.publish_office: docx` (or `pptx`) in frontmatter.
- On `confluence sync`, after the page body is updated, render the
  markdown to the requested office format via Quarto and upload it as
  an attachment named `<page-title>.docx` (or `.pptx`).
- Subsequent runs upload a *new version* of the same-named
  attachment. Confluence's per-attachment version history preserves
  prior copies.
- The attachment is referenced from the page body via a small
  `> Download: [Page Title.docx](attachments/...)` callout near the
  top, generated automatically.

### What about pre-existing attachments that are *not* derived?

A Confluence page may already carry attachments that the user
authored separately and uploaded directly — diagrams in a `.pdf`,
spreadsheets, signed PDFs, screenshots saved as `.png`. These should
not be touched by the publish path.

Rule of thumb:
- If the attachment's filename matches the page's publish-target
  filename (e.g. `Foo.docx` on the page "Foo"), `mdd` owns it and
  may version-update it.
- All other attachments are user-owned. Sync downloads them on the
  pull side (and converts the office-format ones into sibling `.md`
  files via the converter registry, see below) but never modifies
  them on Confluence.

### Pull-side conversion of attachments

When sync pulls a page that has `.docx`/`.pptx`/`.pdf` attachments
that are *not* the page's publish-target file:

- Download the attachment to `<page-name>-attachments/<filename>`
  (the existing image-attachments directory; it's been
  filename-keyed all along, so it scales to any file type).
- If `converter_for(filename)` returns a converter, also produce
  `<page-name>-attachments/<filename>.md` next to it. The `.md` is
  what humans read; the binary stays for fidelity / round-trip.
- The page body's link to the attachment is rewritten to the binary
  (the office file), not the `.md`. This matches the way Confluence
  itself presents attachments — clicking an attachment downloads the
  office file. The sibling `.md` is a convenience for diff /
  searchability in the GitLab mirror.

### Push-side: when the mirror updates the office file

For the publish path (frontmatter `confluence.publish_office`):

1. Render `.md` → `.docx` (or `.pptx`) via Quarto, with a stable
   reference template so output is byte-stable when input is
   unchanged.
2. Compute SHA-256 of the rendered file. Compare to
   `confluence.attachments[*].sha256` in frontmatter for the prior
   render.
3. If unchanged, skip upload (saves an expensive multipart POST).
4. If changed, upload as a new version of the same-named attachment.
   Update the manifest entry.

The render-and-hash step is the expensive part — Quarto invocations
take seconds. Cache by hashing the source `.md` first; if the source
hash matches the recorded one, skip rendering entirely.

### Open questions for the impl spec

- **Scope of `publish_office` opt-in.** Per-page frontmatter, or also
  a space-wide default in config?
- **Reference template handling.** Where does the Quarto reference
  `.docx`/`.pptx` come from? Probably committed under `templates/`
  in the mirror repo so renders are reproducible across machines.
- **Filename if title contains slashes / special chars.** Reuse the
  spec 009 sanitizer.
- **What if the user manually replaced `<title>.docx` on Confluence
  while we owned it?** Probably treat as a user-edit and warn rather
  than overwriting; the office-file conflict story mirrors the body
  conflict story (spec 009's version guard).

## SharePoint bidirectional sync

### The setup

Per spec 010, SharePoint sites are mirrored via OneDrive — files are
local on disk under the OneDrive sync root. Today `mdd sharepoint export`
walks the tree, runs converters, and writes `.md` next to the office
files. It is one-way (SharePoint → markdown) and "reads" both files
on every run.

The user's wish is to expand this into a `sync` flow:
- `.md`/`.qmd` and `.docx`/`.pptx` live side by side in OneDrive.
- Either side may be edited (markdown by `mdd` users, office files by
  colleagues using Word/PowerPoint directly).
- Sync should keep them in step **without** implementing office-file
  diff/merge.
- When both sides have changed, raise a divergence and let the user
  resolve manually.

### State model

The simplest reliable approach is to record, in `.md` frontmatter,
the SHA-256 of both files at the time of the last successful sync:

```yaml
sharepoint:
  source_path: Folder/Foo.docx
  sync:
    docx_sha256_at_sync: 9f86d081...
    md_sha256_at_sync:    e3b0c442...
    last_sync: 2026-05-08T10:30:00Z
```

On each sync run, hash both files now and compare:

| `docx_now == sync.docx_sha256_at_sync`? | `md_now == sync.md_sha256_at_sync`? | Verdict |
|---|---|---|
| Yes | Yes | No-op |
| Yes | No  | Markdown changed → render `.md` → `.docx` (and update both hashes) |
| No  | Yes | Docx changed → convert `.docx` → `.md` (and update both hashes) |
| No  | No  | **Divergence** — see below |

This needs no central state file: each `.md` is self-describing. New
markdown files (no `sync` block yet) classify as "first sync" — same
as spec 014's first-run logic.

### Divergence handling

When both files changed since the last sync, sync **must not
overwrite either**. Recommended behaviour:

1. Render the current `.md` to `Foo.from-md.docx` next to the
   existing `Foo.docx`. Same for `.pptx`.
2. Add a clear note to the run summary:

   ```
   DIVERGENCE: Folder/Foo.docx and Folder/Foo.docx.md both changed
   since 2026-05-04T... A candidate render of the latest .md is at
   Folder/Foo.from-md.docx. Open both files in Word, port changes
   manually, then re-run sync.
   ```
3. Skip both the markdown→office and office→markdown directions for
   that file pair. Sync is idempotent: subsequent runs keep producing
   the same divergence message until the user removes the `.from-md.*`
   file (signalling resolution) and the hashes line up again.

This avoids implementing diff/merge while making divergence highly
visible. It also keeps the conflict signal *inside* the file system
where the user is already working — no out-of-band notification
mechanism needed.

### Why frontmatter and not a side-car state file

- **Self-describing files** match the mdd pattern (specs 009, 010,
  014).
- **No drift surface.** A side-car file can become stale if files are
  moved manually; frontmatter stays attached to its file.
- **Survives partial syncs.** If sync crashes mid-run, the
  per-file frontmatter is updated atomically per file — no global
  state file to write.

### Office-only and markdown-only files

- A `.docx` with no `.md` sibling: standard one-way "first sync"
  behaviour from spec 010 — convert and write the `.md`, populate
  frontmatter.
- A `.md` with no `.docx` sibling: render via Quarto to produce the
  `.docx`. This is symmetric with spec 014's "untracked local-authored
  `.md` becomes a new Confluence page".
- An orphan `.from-md.*` file (no live divergence): warn in summary
  and leave it alone. User is responsible for cleaning it up.

### What happens to non-Office files in the same tree

PDFs, images, videos, spreadsheets — copy-through unchanged, same as
spec 010. Sync's bidirectional logic only kicks in for filename pairs
where both sides have a recognised converter / renderer.

### Safety mechanisms

- **Refuse on dirty git tree.** Same posture as spec 014's confluence
  sync. The mirror is checked into git (per spec 008 layout); if
  there are uncommitted changes, sync aborts.
- **Atomic per-file writes.** Render to `*.tmp`, then rename. An
  interrupted sync leaves partial files, never half-written ones.
- **Backup before overwrite (optional).** Before any auto-overwrite
  of an office file, copy the prior version to
  `.mdd-backups/<rel-path>/<timestamp>-<basename>`. Costly in disk;
  worth a `--backup` flag rather than always-on. Git history covers
  the markdown side; OneDrive's own version history covers the
  office side, so this is belt-and-braces.
- **Locking against concurrent edits.** Word locks `.docx` while it's
  open; sync should detect a `~$Foo.docx` lock file (Word's signal)
  and skip the pair if present, to avoid clashing with an active
  edit.
- **Dry-run mode.** Same as spec 014 — print the plan, touch
  nothing.

### Push to GitLab from a SharePoint sync

Spec 008's `mdd gitlab push` already handles the commit-and-push
mechanics with the spec 007 blacklist gate. SharePoint sync's
`--push` flag invokes it the same way confluence sync does. Since
the SharePoint mirror is checked into git already, the pushed
content includes the just-rendered office files — i.e. `.docx` and
`.pptx` are version-tracked in git. That's fine at the scale we
expect (LFS unnecessary at the typical sizes) but we should keep `git lfs` in
mind if any single repo grows past a few hundred MB of binaries.

## Recommendations summary

### For Confluence (extends spec 009 / 014)

1. **Add a converter registry** at `src/mdd/converters/` and refactor
   `mdd convert` to use it. Out-of-package callers (`mdd confluence`,
   `mdd sharepoint`) consume the same registry.
2. **Pull-side**: download non-image attachments to
   `<page>-attachments/`; for any extension covered by the registry,
   also produce a sibling `.md`. The page body still links to the
   binary (for fidelity); the `.md` is for grep / diff in the mirror.
3. **Push-side (opt-in via frontmatter)**: render `.md`/`.qmd` →
   `.docx`/`.pptx` via Quarto, upload as a same-named versioned
   attachment. Cache by source hash to avoid redundant Quarto runs.
4. **Add `Retry-After` honouring + a concurrency cap of 4** to spec
   009's retry layer. No need for token-bucket pacing yet.
5. **Stream uploads/downloads** rather than fully buffering. Surface
   per-attachment file size in the run summary.
6. **Don't hard-cap attachment size**; offer `--max-attachment-size`
   for the rare bulk-skip use case.

### For SharePoint (new spec, analogous to 014)

1. **Introduce `mdd sharepoint sync-site <name>`** as the
   bidirectional successor to `export site` (which becomes a
   deprecated alias, mirroring the spec 014 pattern).
2. **State lives in markdown frontmatter** (`sharepoint.sync.*` block
   with hashes for both sides). No side-car state file.
3. **Divergence** is detected by triple-hash compare; resolved by
   writing a `Foo.from-md.docx` candidate and surfacing the conflict
   in the run summary, never by auto-merge.
4. **Refuse on dirty git tree, atomic per-file writes, skip files
   with active Word locks** (`~$Foo.docx`).
5. **Markdown-only file → render to `.docx`** via Quarto, symmetric
   with the office-only-file → markdown direction.
6. **Backup is opt-in (`--backup`)**, not always-on.

### Cross-cutting

- Both sync flows want the same building blocks: converter registry,
  reverse-converter registry (Quarto wrapper), retry-with-Retry-After,
  concurrency cap. Building these in `src/mdd/converters/` and
  `src/mdd/utils/http.py` keeps the per-command code thin.
- Both sync flows benefit from a shared "compute file hash" /
  "atomic write" / "tmp-then-rename" helper. Probably already exists
  ad-hoc; consolidate.

### What is *not* recommended (and why)

- **Implementing office-format diff or merge.** Fiendishly hard, low
  marginal value, dragged into scope. Divergence detection +
  side-by-side render gets the user 90% of the value with 5% of the
  effort.
- **Token-bucket rate pacing for v1.** Adds complexity for a problem
  we haven't observed.
- **Side-car sync state files.** Two sources of truth, drift risk.
  Frontmatter is enough.
- **A general-purpose plugin protocol for third-party converters.**
  Internal registry only — adding `.xlsx` is editing one file.
  Plugin architectures should follow demand, not anticipate it.
- **Round-tripping `.qmd` ↔ `.docx` losslessly.** Quarto's render is
  one-way authoritative; Docling's read is one-way authoritative.
  We never claim byte-stable round-trip; the divergence detection
  assumes lossy renders.

## Open questions for the implementation specs

1. Does the office-file publish path go on every Confluence page by
   default, or only opt-in via `confluence.publish_office`? (Suggest
   opt-in — many pages don't need a downloadable copy.)
2. Where do Quarto reference templates live for the rendering
   pipeline — bundled in `mdd`, in the mirror repo, or per-space
   config? (Bundled is simplest; per-mirror override is ergonomic for
   branding.)
3. Should `mdd convert` start emitting frontmatter compatible with
   the SharePoint sync state model (the `sharepoint.sync` block) so
   that the first sync run after `convert` Just Works? Probably yes,
   but the convert command may not always know it's running inside a
   future sharepoint-sync mirror. Suggest: emit it when the file is
   under a directory that contains a SharePoint root marker (we'd
   need to define one — maybe `.mdd-sharepoint`), otherwise omit.
4. Is `git lfs` worth wiring up for SharePoint mirrors that contain
   substantial binary `.pptx` decks? Defer until we see real
   repo sizes.
5. For confluence sync's push-side office attachment, how do we name
   the attachment when the page title contains slashes or special
   characters? Suggest: same sanitiser as the `.md` filename, with
   `.docx` / `.pptx` appended. Document the rule in the spec.
6. Are there Confluence pages whose `.docx` attachments we want to
   *adopt* — i.e. discover the attachment, convert it, and from then
   on have markdown be the source of truth (with future syncs
   uploading the office file from markdown)? This is a one-shot
   migration concern; probably belongs in a separate `mdd confluence
   adopt-attachment` command, not as default sync behaviour.

## Useful API references

- v2 attachments list:  
  `GET /wiki/api/v2/pages/{id}/attachments?limit=250&cursor=...`
- v2 attachment metadata:  
  `GET /wiki/api/v2/attachments/{attachmentId}`
- v2 attachment versions:  
  `GET /wiki/api/v2/attachments/{attachmentId}/versions`
- v1 multipart upload (initial + replace):  
  `POST /wiki/rest/api/content/{pageId}/child/attachment` with
  `Content-Type: multipart/form-data` and headers
  `X-Atlassian-Token: nocheck`. Form field `file` for the binary,
  `comment` for the version comment, `minorEdit=true|false`.
- Atlassian rate-limit docs:  
  <https://developer.atlassian.com/cloud/confluence/rate-limiting/>
  (cost-based model, `Retry-After` header on 429).
- Quarto render to office:  
  `quarto render <file.qmd> --to docx --reference-doc=<template>.docx`
  (`pptx` analogous; reference template controls branding).
