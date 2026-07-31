# 010 - sharepoint command

**Purpose:** `mdd sharepoint` mirrors SharePoint sites to Markdown by reading locally synced files (via OneDrive), without ever calling the SharePoint API.

**Status:** Implemented (2026-05-08)

## Introduction

`mdd sharepoint` produces a Markdown mirror of a SharePoint site by
walking the local OneDrive sync directory and running Office files
through `mdd convert`. There is no SharePoint API call: once a site is
synced to disk, the problem is a filesystem walk.

## Requirements

**User prerequisite.** The user has opened OneDrive, clicked "Sync" on
the SharePoint site(s) they want, and enabled "Always Keep on This
Device" so files are downloaded fully (not cloud-only stubs). README
covers the setup.

**Path resolution.** Default sync root is the OneDrive shared-library folder (the stable
symlink), falling back to
`~/Library/CloudStorage/OneDrive-SharedLibraries-<Tenant>`.
`sharepoint.sync_root` in config can override. macOS only for the first
cut — Windows OneDrive uses a different path shape and there's no
first-party Linux client.

Each immediate child directory of the sync root is treated as a syncable
unit. Two shapes occur:

1. **Whole document library**, named `<Site Name> - Documents`. Strip the
   suffix to derive the canonical site name.
2. **Sub-folder sync**, named after the sub-folder itself with no
   ` - Documents` suffix (e.g. `Appraisals - Leo Simons`). The apparent
   "site name" in OneDrive is the leaf folder, not the SharePoint site.

The folder name as it appears in OneDrive is what `mdd` matches against
the blacklist ([S07](S07-data-protection.md)) — which is why prefix
patterns like `Appraisal*` exist, to catch a family of personal
appraisal folders.

**Site name → repo name mapping.** Repository paths cannot contain spaces
or many special characters on any common forge, so each site has a
normalized repo name used for both the output directory and the remote
repository path. Default
normalization: trim whitespace, replace runs of whitespace or any of
`/\:*?"<>|` with a single `-`, strip leading/trailing `-`, preserve
case. Example: `HR Documentation` → `HR-Documentation`. The mapping is
committed to git so multiple contributors agree on names; sites without
an explicit entry fall back to the default rule, with `list sites`
warning so the user can decide whether to add an explicit mapping.

**Confidentiality.** The blacklist from
[S07](S07-data-protection.md) governs whether a site mirror can be
pushed to a remote. The match is on the canonical site name (before
repo-name mapping), so the blacklist is independent of the repository
name. Local-only export is unrestricted; only the `--push` path is gated.

**Per-file rules.** Walk the document library recursively. For each
file, apply the first matching rule:

1. **`<name>.docx.md` already exists next to `<name>.docx`** — copy the
   `.md` through, **leave the `.docx` alone**. Assume conversion already
   happened and the markdown is now the human-edited master.
2. **`<name>.docx`** without a sibling `.md` → run `mdd convert` to
   produce `<name>.docx.md`. Embedded images extracted to
   `<name>.docx-attachments/`.
3. **`<name>.pptx`** — same pattern as `.docx`: existing sibling `.md`
   wins, otherwise convert via [S11](S11-convert-pptx.md).
4. **`<name>.pdf`** → convert with Docling, producing `<name>.pdf.md`
   with embedded images extracted alongside.
5. **`<name>.md`** → copy through unchanged (frontmatter prepended if not
   already present).
6. **`<name>.xlsx`** → ignore. Spreadsheets aren't a useful narrative
   format for a markdown mirror.
7. **Image files** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`) as
   standalone files in SharePoint → **do not** convert or copy. Likely
   referenced from a `.docx`/`.pptx` where they are already embedded;
   copying again would create duplicates of unclear ownership.
8. **Any other extension** → log and skip.

**General rules across conversions.** Mirror the source directory
structure under `<output>/`. Atomic per-file writes (`*.tmp` then
rename). Incremental by default — skip if destination is newer than
source mtime unless `--force`. Every generated `.md` gets a SharePoint
frontmatter block and a "SharePoint export" callout pointing back to the
relative path inside the site.

## Subcommands

```
mdd sharepoint list-sites    [--config <file>]
mdd sharepoint sync-site     <site-name>  [--config <file>] [--output <dir>] [--force]
mdd sharepoint sync-folder   <local-path> [--output <dir>] [--force]
```

- `list-sites` — enumerates SharePoint sites in the local OneDrive sync
  directory, with allowed/blocked status from the
  [S07](S07-data-protection.md) blacklist and the configured
  repo-name mapping. Warns about anything that's synced as a sub-folder
  rather than a whole library.
- `sync-site` — converts a whole site (or its document library) into a
  Markdown mirror using the per-file rules above (bidirectional; see
  [S18](S18-sharepoint-sync.md)).
- `sync-folder` — same engine pointed at any local folder.

## Config schema

Per-user `mdd` config (paths and overrides only — no secrets):

```yaml
sharepoint:
  sync_root: ~/<sync root>               # optional override
  sites:
    AI:
      output_dir: ./output/ai
    "Academy Coordination":
      output_dir: ./output/academy
```

Site→repo mapping (committed to git):

```yaml
# configs/sharepoint-mapping.yaml
sites:
  "HR Documentation":
    repo: HR-Documentation
  "AI":
    repo: AI
  "Academy Coordination":
    repo: Academy-Coordination
```

Search order for the mapping: `--mapping <file>`,
`./configs/sharepoint-mapping.yaml`,
`~/.config/mdd/sharepoint-mapping.yaml`.

Per-file frontmatter on every generated `.md`:

```yaml
sharepoint:
  site: <Canonical Site Name>
  repo: <Mapped Repo Name>
  source_path: <relative-path-inside-site>
  source_mtime: 2026-05-08T10:30:00Z
  exported_at: 2026-05-08T10:31:42Z
  converter: docling-docx | docling-pdf | copy
```

## Why local sync, not the SharePoint API

- The SharePoint Graph API requires app registration, admin consent, and
  delegated permissions per tenant — high friction inside a large organisation.
- Most users already have OneDrive running. Once a site is synced,
  the problem is a filesystem walk — much like `rsync` from a local
  source.
- `mdd` runs offline against an already-cached snapshot, which is faster
  and avoids rate-limit and auth concerns.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [007-data-protection](S07-data-protection.md) — blacklist governing confidential site push
- [011-convert-pptx](S11-convert-pptx.md) — pptx conversion used by export rule 3

## Out of scope

- Writing back to SharePoint — the master here is binary Office files;
  `mdd` does not edit those.
- Windows / Linux OneDrive paths.
- API-based access for sites the user has not synced.
- Permission/ACL inspection (the blacklist is the only gate).
- `.xlsx` conversion (would need a different toolchain; deferred until
  there's a concrete use-case).
