# 018 - sharepoint sync command

**Purpose:** Bidirectional sync between `.md`/`.qmd` and `.docx`/`.pptx` in SharePoint sites mirrored via OneDrive, without office-format diff/merge.

**Status:** Implemented (2026-05-09)

## Introduction

`mdd sharepoint sync` is the bidirectional successor to `mdd sharepoint export` ([S10](S10-sharepoint-command.md)). It keeps `.md`/`.qmd` and `.docx`/`.pptx` in step inside SharePoint sites mirrored via OneDrive, detecting divergence between the two sides without implementing office-format diff/merge. When both sides change since the last sync, sync surfaces the conflict by writing a `*.from-md.docx` candidate render and refusing to overwrite either side.

`export site` is preserved as a deprecated alias that forwards to
`sync site`.  ([S14](S14-confluence-sync.md) has since dropped the
analogous `export space` alias.) The snapshot/one-way-export flow is
provided by `sync site --read-only`, matching the equivalent flag on
`mdd confluence sync-space`.

Originates from research doc 002.

## Subcommands

```
mdd sharepoint sync-site   <site-name> [--config <file>] [--output <dir>]
                                       [--dry-run] [--push] [--read-only]
                                       [--message <msg>] [--backup]
mdd sharepoint sync-folder <local-path> [--output <dir>] ...
```

`list-sites` from [S10](S10-sharepoint-command.md) is unchanged. The previously
deprecated `export site` / `export folder` forwarders are gone (S35).

## Reconciliation

For each filename pair `(Foo.docx, Foo.docx.md)` (or `.pptx` /
`.pptx.md`) inside the synced OneDrive tree, sync reads the prior
state from `.docx.md` frontmatter, hashes both sides now, and picks
an action from the diff table below.

**State carried in `.docx.md` frontmatter:**

```yaml
sharepoint:
  source_path: Folder/Foo.docx
  sync:
    office_sha256_at_sync: 9f86d081...
    md_sha256_at_sync:     e3b0c442...
    last_sync: 2026-05-08T10:30:00Z
    converter: docling-docx
    converter_version: "2.4.0"
    update_office: false
```

The `office_sha256_at_sync` field tracks the office file (`.docx` or
`.pptx`); the name is type-agnostic on purpose.

**`update_office` — the md→office opt-in gate.** Markdown → office
rendering goes through Quarto, which is lossy: shapes, custom styles,
inline metadata, etc. can degrade. To avoid clobbering an authoritative
office file with an inferior render, `update_office` defaults to
**false** and md→office only happens when the user (or the first-sync
path) explicitly sets it to `true`.

| Direction on first sync           | `update_office` stamped |
|-----------------------------------|-------------------------|
| `.docx` only → convert to `.md`   | `false`                 |
| Both present, no sync block       | `false` (docx wins)     |
| `.md` only → render to `.docx`    | `true`                  |

The user can flip `update_office` to `true` in any `.docx.md` to
opt that pair into bidirectional sync.

**Diff table:**

| `office_now == sync` | `md_now == sync` | `update_office` | Verdict |
|---|---|---|---|
| Yes | Yes | any   | **No-op** |
| No  | Yes | any   | **docx changed** → run converter (`.docx → .md`), overwrite `.md`, refresh hashes |
| Yes | No  | true  | **md changed** → render `.md → .docx` via Quarto, overwrite `.docx`, refresh hashes |
| Yes | No  | false | **SKIP** — md edits ignored; warn the user how to opt in |
| No  | No  | true  | **DIVERGENCE** → render `.md → Foo.from-md.docx`, do not touch either source, summary records the conflict |
| No  | No  | false | **SKIP** — leave both sources alone; warn the user how to opt in |

A first-sync pair (no `sync` block) is treated as:
- `.docx` only → run converter, write `.md` with fresh `sync` block,
  `update_office: false`.
- `.md` only → render via Quarto, write `.docx`, write `sync` block,
  `update_office: true`.
- Both present, no `sync` block → trust the office file as
  authoritative; convert to `.md`, stamp the block with
  `update_office: false`. (Matches the
  [S10](S10-sharepoint-command.md) "sibling `.md` exists, leave docx alone" rule for
  the *post*-first-sync state.)

After all pairs are processed, sync runs `git add -A` scoped to the
output tree and creates one commit summarising the actions, e.g.:

```
chore(mirror): sync from SharePoint site SITE-NAME

Office <-> markdown:
  3 pairs first-synced (docx -> md)
  4 pairs: md edited -> docx regenerated
  1 pair: DIVERGED (Foo.from-md.docx written for manual port)
```

`--push` invokes `mdd gitlab push` (S08) including the
[S07](S07-data-protection.md) confidentiality blacklist. Same gate semantics as
[S14](S14-confluence-sync.md).

### Cold-start bootstrap on `--push`

When `--push` runs against a mirror directory that is not yet a git
work-tree, sync bootstraps it before pushing — matching [S14](S14-confluence-sync.md)
step 6:

- If `.git` is missing, sync runs `git init -b main` and adds
  `origin → https://<gitlab.hostname>/<gitlab.sharepoint_group>/<repo-name>.git`.
  Both `gitlab.hostname` and `gitlab.sharepoint_group` come from
  `configs/gitlab.yaml` (S08); the house defaults resolve to
  `gitlab.example.com` and `mdd/sharepoint`. `<repo-name>` is
  the mapped repo name from `sharepoint-mapping.yaml` (or the normalised
  site name if no explicit mapping).
- Before pushing, sync calls `mdd.gitlab.mirror.ensure_gitlab_project()`
  on `<gitlab.sharepoint_group>/<repo-name>`. If the GitLab project
  doesn't exist yet, it is created with `visibility="internal"`. If
  GitLab is unreachable or `glab` isn't installed, the ensure step is
  skipped and the underlying problem surfaces from the push attempt; the
  user sees one clear failure rather than two.

The init + ensure-project logic is shared with `mdd confluence
sync-space` via the `mdd.gitlab.mirror` module so both commands behave
identically.

When `sync-folder` is used directly (no site identity, no mapping),
bootstrap is skipped: without a known target repo there is nowhere
safe to push. The user should pass `--output <clone-of-mirror>` or
clone the target repo manually before running with `--push`.

## Behaviour rules

**Refuse on dirty git tree.** If `git status --porcelain` shows
changes in the output tree, abort with:
`"Mirror has uncommitted changes. Commit, stash, or discard before
running sync."`. No `--allow-dirty` escape hatch.

**Skip pairs with active Word locks.** When `~$Foo.docx` exists
in the same directory (Word's lock-file convention), skip the pair
and log "skipped: file open in Word" in the summary. The next sync
picks it up after the user closes Word.

**Atomic per-file writes.** Every regenerated file goes via
`*.tmp → rename`. An interrupted sync leaves zero partial files.

**Backups optional, not default.** `--backup` copies the prior
office file to `.mdd-backups/<rel-path>/<timestamp>-<basename>`
before overwriting. Off by default (git history covers `.md`;
OneDrive version history covers `.docx`/`.pptx`); flag exists for
paranoid runs.

**Divergence handling.** When both sides changed *and*
`update_office: true`:
- Render the current `.md` to `Foo.from-md.docx` (or `.pptx`) next
  to `Foo.docx`.
- Do **not** touch `Foo.docx` or `Foo.docx.md`.
- Record in run summary with a clear instruction telling the user
  to open both in Word/PowerPoint, port changes manually, then
  re-run sync.
- Idempotent: subsequent runs keep producing the same divergence
  message until the `.from-md.docx` is removed (signalling
  resolution) and the recorded hashes match again.
- If a `.from-md.docx` already exists from a prior run, sync skips
  re-rendering (the user is presumably mid-port).

When both sides changed but `update_office: false`, sync emits a
SKIP warning and leaves both sources untouched — no candidate render
is produced.

**Markdown-only files.** A `.md` file with no `.docx` sibling is
treated as a publish candidate: render via Quarto, write the
`.docx`, write a fresh `sync` block with `update_office: true`.
Matches the symmetric "untracked local-authored .md becomes a new
Confluence page" rule from [S14](S14-confluence-sync.md).

**Office-only files.** `.docx`/`.pptx` files with no `.md` sibling
go through the appropriate converter ([S16](S16-confluence-attachment-conversion.md) / [S11](S11-convert-pptx.md))
to produce the `.md`, with the `sync` block written. Matches the
[S10](S10-sharepoint-command.md) first-encounter rule.

**Files outside the converter pairs.** Per [S10](S10-sharepoint-command.md), `.pdf` is
copied through with conversion to `.pdf.md` (one-way; no Quarto
push-back). `.xlsx`, image files, etc. follow [S10](S10-sharepoint-command.md) rules
unchanged. Sync's bidirectional logic only applies to the
office-format pairs.

**`--head N`.** Limits sync to the first N pairs (alphabetical) for
testing. Same shape as [S14](S14-confluence-sync.md).

**`--dry-run`.** Prints the plan; touches nothing.

**`--read-only`.** Suppresses every mirror → OneDrive/SharePoint write
step: `MD_TO_DOCX`, `FIRST_SYNC_MD_AUTHORITATIVE` / `MD_ONLY`, and the
`DIVERGED` candidate render are all skipped and reported on stderr
(`[skip-write] <name> (--read-only, would have run <action>)`).
Pull-side actions (`DOCX_TO_MD`, `FIRST_SYNC_DOCX_*`), the local git
commit, and the optional `--push` to GitLab still run, so the flag
yields a snapshot-style export without any chance of mutating the
office side.

## Frontmatter additions

The existing [S10](S10-sharepoint-command.md) frontmatter gains the `sync` sub-block:

```yaml
sharepoint:
  site: My SharePoint Site
  repo: My-SharePoint-Site
  source_path: Folder/Foo.docx
  source_mtime: 2026-05-08T10:30:00Z
  exported_at: 2026-05-08T10:31:42Z
  converter: docling-docx | docling-pdf | quarto-docx | copy

  sync:
    office_sha256_at_sync: 9f86d081...
    md_sha256_at_sync: e3b0c442...
    last_sync: 2026-05-08T10:30:00Z
    converter_version: "2.4.0"
    update_office: false
```

The `converter` field tracks which direction was authoritative on
last sync (`docling-docx` = docx-was-master; `quarto-docx` = md-was-
master). Useful diagnostic in the run summary; not load-bearing.

The `update_office` field gates md→office rendering: `false` (default)
treats the office file as authoritative and ignores md edits, `true`
opts in to bidirectional sync. See "Diff table" above.

## Design Approach

**Pure diff function** classifies each pair into a `PairAction`
enum (`NO_OP`, `DOCX_TO_MD`, `MD_TO_DOCX`, `SKIP_MD_UPDATE`,
`DIVERGED`, `FIRST_SYNC_*`, `WORD_LOCKED`, `MD_ONLY`).
The apply layer dispatches to [S15](S15-converter-registry.md)'s
converter / reverse-converter registries and writes atomically
(`*.tmp → rename`).

**Concurrency** — sequential by default. The bottleneck is Quarto
render and Docling conversion, both CPU-bound and not friendly to
thread-level parallelism.

## Related upstream specs

- [010-sharepoint-command](S10-sharepoint-command.md) — base SharePoint export command this extends
- [014-confluence-sync](S14-confluence-sync.md) — bidirectional sync pattern this mirrors
- [015-converter-registry](S15-converter-registry.md) — converter registry used for dispatch
- [016-confluence-attachment-conversion](S16-confluence-attachment-conversion.md) — converter chain for docx/pptx
- [017-confluence-office-publishing](S17-confluence-office-publishing.md) — Quarto reverse converter
- 008-gitlab-command — gitlab push used by --push flag
- [007-data-protection](S07-data-protection.md) — confidentiality blacklist applied on push
- [011-convert-pptx](S11-convert-pptx.md) — pptx converter used for office-only files

## Out of scope

- Office-format diff or merge (the entire reason this spec exists is
  to *avoid* implementing it).
- Rendering `.md` to `.pdf` and treating that bidirectionally. PDFs
  are one-way exports.
- Watching the OneDrive tree continuously. Sync is run on demand.
- Conflict resolution UI beyond the `*.from-md.docx` candidate. The
  user opens Word and merges manually.
