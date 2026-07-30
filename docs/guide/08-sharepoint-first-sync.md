# Your first SharePoint sync

SharePoint is not Confluence with different nouns. Read this section before
you run anything; almost every prerequisite and failure mode differs.

## How this is different

`mdd` never calls a SharePoint or Microsoft Graph API. It reads the folder
your OneDrive client has already synced to your disk, and writes back into
that same folder. OneDrive does the uploading.

Four consequences follow:

- **There are no credentials to configure.** Your OneDrive client holds the
  authentication. `mdd` sees a directory.
- **macOS only.** The sync root is discovered under
  `~/Library/CloudStorage/`. Windows OneDrive uses a different path shape
  and there is no first-party Linux client.
- **A write is not local.** Overwriting a `.docx` in the OneDrive folder
  publishes a new version to SharePoint for everyone, seconds later. The
  absence of an API does not make this safer.
- **The unit of content is a binary Office file**, not a page. `mdd`
  converts `.docx`, `.pptx` and `.pdf` to Markdown with Docling, and
  renders Markdown back to Office with Quarto. Both directions lose
  information in ways a page body does not.

That last point drives the whole design. The Markdown-to-Office render
loses shapes, custom styles and inline metadata, so `mdd` refuses to do it
by default. Every file pair carries an `update_office` flag in frontmatter,
which starts as `false` for anything that came from an Office file. Until
you flip it, Markdown edits are ignored and reported as skipped.

## 1. Get a site you are allowed to break

Create a SharePoint site, or a document library in one, that nobody
depends on. Put a couple of Word documents in it, ideally with an image and
a table, so the conversion has something to chew on.

Check the blacklist before you start. `mdd sharepoint` calls the
confidentiality check at the start of every run, before it converts
anything, so a site whose name matches an entry in
`configs/data-protection.yaml` aborts the whole command rather than only
the push. The shipped file blocks names like `Board`, `Governance`,
`Appraisal*` and `Customer-*`. Pick a scratch site name that does not
collide with one.

## 2. Sync the site into OneDrive

In the browser, open the document library and choose **Sync**. Then, in
Finder, right-click the synced folder and enable **Always Keep on This
Device**.

That second step is not optional. Without it, OneDrive leaves cloud-only
placeholder stubs on disk, and `mdd` walks a tree of files that have no
content in them.

Wait for the sync to finish before continuing.

## 3. Confirm `mdd` can see it

```bash
mdd sharepoint list-sites
```

This is read-only and touches nothing. For each folder it can sync, it prints
the site name, the folder name it came from, whether the folder is a whole
document library or a sub-folder, the repository name it would use, and
whether the blacklist allows it.

Two things to check in that output.

**The site name.** A whole library appears as `<Site Name> - Documents` in
OneDrive, and `mdd` strips the suffix. A sub-folder sync appears under the
sub-folder's own name, which is not the site name at all. The name shown
here is what every other command and the blacklist match against.

**The repository name.** Sites with no entry in
`configs/sharepoint-mapping.yaml` fall back to a default rule and are
flagged. If the derived name matters to you, pin it in the mapping file.

If the command reports that it cannot find a sync root, and you have more
than one tenant synced, the discovery is ambiguous. Use
`mdd sharepoint sync-folder <path>` against the folder directly.

## 4. Sync read-only into a mirror

Create an empty git repository for the mirror. Plan the run first:

```bash
mkdir -p ~/mirrors/scratch-site && cd ~/mirrors/scratch-site && git init
mdd sharepoint sync-site "Scratch Site" --output ~/mirrors/scratch-site --read-only --dry-run
```

`--dry-run` prints the plan and writes nothing. `--read-only` suppresses
every write back into the OneDrive folder: no Markdown-to-Office render,
and no divergence candidate. The Office-to-Markdown half and the local git
commit still run.

Then run it for real, still read-only:

```bash
mdd sharepoint sync-site "Scratch Site" --output ~/mirrors/scratch-site --read-only
```

`--head 5` caps the run while you are getting your bearings. The first run
of any conversion downloads Docling's models, roughly 500 MB into
`~/.cache/docling/`, so give it time.

The summary line counts every category: first syncs in each direction,
conversions each way, divergences, skips for `update_office: false`, skips
for `--read-only`, ignored paths, Word-locked files, corrupt files, no-ops
and errors. Read it. It is the fastest way to see that something you
expected to happen did not.

## 5. Look at what it produced

The mirror copies the source directory structure. Each `Foo.docx` gets a
`Foo.docx.md` sibling with extracted images in `Foo.docx-attachments/`.
A PDF converts to `Foo.pdf.md` one way only. Plain `.md` files are copied
through. Spreadsheets and standalone image files are skipped by design,
the latter because they are usually already embedded in a document.

Every generated file carries a `sharepoint:` frontmatter block and a
"SharePoint export" callout naming the source path. The interesting part is
the `sync` sub-block:

```yaml
sharepoint:
  site: Scratch Site
  source_path: Handbook/Onboarding.docx
  converter: docling-docx
  sync:
    office_sha256_at_sync: 9f86d081...
    md_sha256_at_sync: e3b0c442...
    last_sync: 2026-05-08T10:30:00Z
    update_office: false
```

Those two hashes are how divergence is detected: `mdd` re-hashes both sides
on every run and compares them against what it recorded. `update_office:
false` is the gate described above.

Read one of the converted files next to the original in Word. Conversion
quality is the thing that decides whether this workflow is useful for your
content, and no amount of documentation substitutes for looking.

## 6. Only then, the write path

To let Markdown edits flow back into an Office file, set
`update_office: true` in that file's frontmatter. It is per pair and
deliberate.

```bash
mdd sharepoint sync-site "Scratch Site" --output ~/mirrors/scratch-site --dry-run
mdd sharepoint sync-site "Scratch Site" --output ~/mirrors/scratch-site --backup
```

Without `--read-only`, that run renders your Markdown to `.docx` through
Quarto and overwrites the file in the OneDrive folder. There is no
confirmation prompt. `--backup` copies the previous Office file to
`.mdd-backups/<path>/<timestamp>-<name>` first; it is off by default, and
for your first write it is worth the disk.

A Markdown file in the tree with no Office sibling is treated as a publish
candidate: `mdd` renders it to `.docx` and stamps `update_office: true`,
because in that direction Markdown was authoritative from the start.

`mdd sharepoint sync-folder <path> --output <dir>` runs the same engine
against any local folder. It has no `--read-only` flag, and it requires
`--output`.

## Failure modes you will actually hit

**Cloud-only files.** If "Always Keep on This Device" is off, files on disk
are stubs. Turn it on and let OneDrive finish.

**Multiple tenants synced.** Sync-root discovery gives up rather than
guessing. Use `sync-folder` with an explicit path.

**"Mirror has uncommitted changes."** Sync refuses on a dirty output tree,
with no override. Commit or stash.

**The blacklist blocked the run.** The site name matched an entry. The
match is on the name OneDrive shows, which for a sub-folder sync is the
sub-folder name. `mdd sharepoint list-sites` shows you what is being
matched.

**A pair reports `DIVERGED`.** Both the `.docx` and the `.md` changed since
the last sync, and `update_office` was `true`. `mdd` writes
`Foo.from-md.docx` next to the original and touches neither source. Open
both in Word, port the changes by hand, delete the candidate, and re-run.
Until the candidate is gone, every run repeats the same message.

**Markdown edits are silently ignored.** They are not silent, but they are
easy to miss: the summary counts them under `skipped(update_office=False)`.
Flip the flag in that file's frontmatter to opt the pair in.

**"skipped: file open in Word."** A `~$Foo.docx` lock file exists. Close
Word and re-run.

**Quarto is missing.** Markdown-to-Office rendering needs it. Install
Quarto, or stay read-only.

**The first run takes forever.** Docling downloads models once. Later runs
reuse the cache.

**A file you did not want got converted.** Add a `.mddignore` at the mirror
root with gitignore-style patterns. It filters the source side before
conversion, so it also saves the time. It does not delete anything already
synced unless you ask for that explicitly.

[S10](../spec/S10-sharepoint-command.md) and
[S18](../spec/S18-sharepoint-sync.md) are the design record for this
command, including the full reconciliation table.
