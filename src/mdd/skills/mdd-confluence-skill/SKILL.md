---
name: mdd-confluence-skill
description: |
  How to drive Confluence sync and page operations via the mdd CLI; when to
  prefer `mdd confluence` over the Confluence REST API directly.
---

## When to use

Trigger this skill when the user mentions any of:

- Syncing or mirroring a Confluence space to a local git repository
- Pulling the latest Confluence pages into a local mirror
- Pushing local markdown edits back to Confluence
- Creating a new Confluence page from a local markdown file
- Updating an existing Confluence page
- Renaming, moving, archiving, or unarchiving a Confluence page from the mirror
- Checking who owns or manages a Confluence page
- Exporting a single Confluence page to markdown

## When NOT to use

- The user wants to call the Confluence REST API directly for an operation `mdd`
  does not expose (e.g. comments, page restrictions, space permissions).
- The operation targets a page that is "managed elsewhere" (Sphinx, TechDocs,
  another publisher): `mdd` will refuse the push and the user should go to the
  source system instead.
- The user is working with Confluence Data Center (on-prem); `mdd` targets
  Confluence Cloud only.

## Common flows

**Full bidirectional space sync** (most common):
```
mdd confluence sync-space MYSPACE
```
Pulls remote changes, reconciles renames/deletes, then pushes local edits.
Add `--dry-run` to preview the plan without touching anything.
Add `--push` to automatically push the resulting git commit to GitLab after sync.

**Single-page update** (after editing a mirror file):
```
mdd confluence update-page docs/my-page.md
mdd confluence update-page docs/my-page.md --dry-run   # preview diff
mdd confluence update-page docs/my-page.md --yes        # skip confirmation
```

**Create a new page**:
```
mdd confluence create-page docs/new-page.md --space MYSPACE
mdd confluence create-page docs/new-page.md --space MYSPACE --parent <id-or-url>
```

**Export a single page** (read-only, no git commit):
```
mdd confluence export-page <page-id-or-url>
```

**Rename / move / archive / unarchive a page** (spec S27):
```
mdd confluence rename-page    docs/page.md "New Title"        --yes
mdd confluence move-page      docs/page.md --parent <id|url|other.md>
mdd confluence archive-page   docs/page.md                    --yes
mdd confluence unarchive-page docs/page.md                    --yes
```
Each command mutates Confluence first, then refreshes the local mirror
(file rename for `rename-page`; frontmatter `confluence.status` flip for
`archive-page` / `unarchive-page`) and commits a single
`chore(mirror): …` summary. Add `--dry-run` to preview without writing;
`--no-commit` to leave staged changes for the user.

**Check current user / managed-elsewhere status**:
```
mdd confluence whoami
```

**Key flags for `sync space`**:
- `--dry-run` — print plan, touch nothing
- `--no-delete` — skip deleting files whose pages were deleted in Confluence
- `--head N` — process only the first N pages (useful for testing)
- `--max-attachment-size MB` — skip downloading attachments above this size
- `--push` — run `mdd gitlab push` after sync
- `--message MSG` — custom git commit message

For full parameter detail: `mdd confluence --help`
