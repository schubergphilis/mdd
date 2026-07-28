---
name: mdd-sharepoint-skill
description: |
  How to drive SharePoint / OneDrive mirror sync via the mdd CLI; when to
  prefer `mdd sharepoint sync` over manual file operations.
---

## When to use

Trigger this skill when the user mentions any of:

- Syncing a SharePoint site or OneDrive folder with a local markdown mirror
- Converting `.docx` / `.pptx` files in OneDrive to markdown
- Pushing local markdown edits back to a `.docx` file in OneDrive
- Listing available SharePoint sites in the OneDrive sync directory
- Handling a file that was edited both locally (as `.md`) and in SharePoint (as `.docx`)

## When NOT to use

- The user wants to interact with SharePoint's REST API directly (permissions,
  lists, search, etc.).
- The OneDrive sync folder is not mounted locally; `mdd` relies on the local
  OneDrive client.
- The operation is targeting a `.pdf` or image file — `mdd sharepoint sync`
  handles `.docx` and `.pptx` pairs only.

## Common flows

**List available SharePoint sites**:
```
mdd sharepoint list-sites
```

**Sync a whole site** (bidirectional: docx→md and md→docx):
```
mdd sharepoint sync-site MySiteName
mdd sharepoint sync-site MySiteName --dry-run   # preview only
mdd sharepoint sync-site MySiteName --push      # push git commit after sync
mdd sharepoint sync-site MySiteName --backup    # keep prior .docx under .mdd-backups/
```

**Sync a specific folder**:
```
mdd sharepoint sync-folder /path/to/OneDrive/Folder --output ~/mirrors/my-folder
```

**Divergence handling** — when both `.docx` and `.md` have changed since last
sync, `mdd` writes `Foo.from-md.docx` as a candidate and leaves both originals
untouched. Present both files to the user and ask which version to keep.

**Word-locked files** — if `~$Foo.docx` is present (Word has the file open),
that pair is skipped automatically. Inform the user to close Word and re-run.

**Key flags**:
- `--dry-run` — print plan, touch nothing
- `--backup` — store replaced `.docx` under `.mdd-backups/` before overwriting
- `--head N` — process only the first N file pairs
- `--push` — run `mdd gitlab push` after sync
- `--message MSG` — custom git commit message

For full parameter detail: `mdd sharepoint --help`
