# 014 - confluence sync command

**Purpose:** `mdd confluence sync` is the primary bidirectional verb for keeping a git mirror repo in lockstep with its Confluence space.

**Status:** Implemented (2026-05-08)

## Introduction

`mdd confluence sync` pulls Confluence-side changes (renames, moves, archives, deletes, edits, metadata refresh) into the mirror as proper git operations, and pushes local-side changes (new pages, edits) back to Confluence. It supersedes the original `export space` command from [S09](S09-confluence-command.md); the snapshot-only behaviour now lives behind `sync space --read-only`.

This spec extends [S09](S09-confluence-command.md) — it reuses its HTTP client, URL parsing,
filename sanitization, frontmatter schema, attachment sync, and body
conversion machinery. Read 009 first.

The motivating problem: a re-export after a Confluence-side rename, move,
archive, or delete would create a new file at the new path while leaving the
old file in place, producing duplicates and stale content in the mirror.
Confluence Cloud has **no global change feed** (no "everything that changed
since timestamp T" endpoint that reports moves, renames, archives, or deletes
as discrete events; per-page `/pages/{id}/versions` only covers body edits;
CQL `lastmodified > "…"` is unreliable for moves and archives). Detection
therefore has to be done by diffing the current Confluence tree against the
local mirror state, anchored on the page `id` — which is stable across
rename, move within space, move across spaces, archive, and unarchive (only
copy mints a new id). Every other field on a page is mutable. The
reconciliation algorithm below flows directly from those two facts.

## Requirements

- Provide `mdd confluence sync-space <space-key>` as the single verb for whole-space reconciliation.  (The dedicated `mdd confluence export space` command has been removed; `sync space --read-only` is the snapshot equivalent and adds rename/move/delete detection.)
- Sync must be bidirectional by default: pull Confluence-side changes into the mirror and push local-authored changes back to Confluence.
- Provide `--read-only` to suppress every mirror → Confluence write step (no `create page`, no content push, no Office publishing), for snapshot-style runs.
- Every page must be keyed by its stable Confluence `page_id`; paths and titles are mutable.
- Detect and handle renames, moves, archives, unarchives, content edits, deletions, cross-space moves, and new local-authored pages.
- Refuse to run if the mirror working tree has uncommitted changes.
- Produce a single structured commit per run; emit no commit if nothing changed.
- Support `--dry-run`, `--no-delete`, `--push`, `--message`, `--head`, `--max-attachment-size`, `--no-attachments`, and `--read-only` flags.
- Apply best-effort partial failure: record errors per page, commit successful operations, exit non-zero if any failure occurred.
- Leave manually-managed files (no `confluence.page_id`, not publishable) untouched.

## Design Approach

- Full reconciliation on every run: one paginated tree fetch + per-page body fetch only for pages whose `version_number` advanced. No CQL incremental, no side-car state file. Confluence has no global change feed, so partial-incremental modes can miss moves and archives.
- Identity-driven diffing: match local files to Confluence pages by `confluence.page_id` in frontmatter — never by path or title.
- Six-event diff table (new, no-op, content edit, rename, move, archive/unarchive, trashed/deleted) plus two local-only events (untracked publish, local edit push).
- Conflict detection: if a local edit is queued for push but the remote `version_number` has advanced past the local frontmatter `version_number`, skip both push and pull for that page and record it in the run summary.
- Operations applied in a fixed order to satisfy preconditions: renames/moves → collision resolution → archive/unarchive → new local pages → content pulls → content pushes → deletions → metadata-only refresh.
- Filename collision resolution: append `(page-id)` to **both** colliding files (not just the incomer).
- Git operations via `subprocess.run` (mv, rm, add, commit, status); no new Python git library dependency.
- Optional push through the active mirror backend, including the [S07](S07-data-protection.md) confidentiality blacklist gate.

## Subcommands

```
mdd confluence sync-space <space-key> [--config <file>] [--output <dir>]
                                      [--dry-run] [--no-delete]
                                      [--push] [--message <msg>]
                                      [--head <n>]
                                      [--max-attachment-size <MB>]
                                      [--no-attachments] [--read-only]
```

- `sync space` — full reconciliation between the Confluence space and
  the local mirror. See "Reconciliation algorithm" below.

`export page`, `create page`, and `update page` from [S09](S09-confluence-command.md) stay
unchanged. `sync space` is the top-level entry point for whole-space
operations, and internally calls those same primitives (create / update /
fetch) as needed.

## Reconciliation algorithm

Sync is identity-driven: every page is keyed by its Confluence
**`page_id`**, which is stable across rename, move (within space),
archive, and unarchive. Local files are matched to Confluence pages
by reading the `confluence.page_id` field in frontmatter.

### Step 1 — Build the desired state from Confluence

One paginated tree fetch of
`GET /wiki/api/v2/pages?space-id=<id>&status=current,archived&include-labels=true&include-version=true&limit=250`.
Body is **not** included; the result is a map
`page_id → { title, parent_id, status, version_number, version_created_at, position, labels, updated_by }`.
Folders that appear as parents are resolved with `GET /folders/{id}`
and added as directory-only nodes (same logic as [S09](S09-confluence-command.md)
export). Trashed and hard-deleted pages are absent from this fetch by
construction.

v2 query parameters are kebab-case (`space-id`, `include-labels`,
`include-version`); the camel-case form (`spaceId`) is silently ignored
by Atlassian and returns every page across the tenant — see
[S09](S09-confluence-command.md) for the underlying gotcha and the
companion `params=None` pagination rule.

### Step 2 — Build the current state from the mirror

Walk the output directory recursively. For each `.md` file, parse
frontmatter and classify:

- `confluence.page_id` present → record `page_id → { path, title, parent_id, status, version_number, attachments_manifest }`.
- `confluence.page_id` absent → **untracked local-authored** (publish candidate, see Step 4d).
- Frontmatter malformed or missing → **manually-managed**; sync leaves them untouched and lists them in the summary.

If the same `page_id` appears in two `.md` files, sync aborts with a
clear error naming both paths.

### Step 3 — Diff and classify

For each `page_id` in either map:

| Desired | Current | Other diff                          | Event                  |
|---------|---------|-------------------------------------|------------------------|
| Yes     | No      | —                                   | new (Confluence → mirror) |
| Yes     | Yes     | nothing                             | no-op                  |
| Yes     | Yes     | `version_number` advanced on remote | content edit (pull)    |
| Yes     | Yes     | `title` differs                     | rename                 |
| Yes     | Yes     | `parent_id` differs                 | move                   |
| Yes     | Yes     | both title and parent differ        | rename + move          |
| Yes     | Yes     | `status` flipped to `archived`      | archive                |
| Yes     | Yes     | `status` flipped from `archived`    | unarchive              |
| No      | Yes     | —                                   | trashed or deleted     |

A page whose `space_id` differs between desired and local frontmatter
is a **cross-space move** — detected by falling back to
`GET /pages/{id}` for any page that vanished from the tree; if the
response has a different `spaceId`, classify separately.

Sync also identifies **local-only events**: untracked local-authored
files (publish-as-new) and local edits where `page_id` is present and
body differs from rendered Confluence body. If the local file's
frontmatter `version_number` is **older** than the current Confluence
`version_number`, sync skips push and pull for that page and records
a conflict.

### Step 4 — Apply changes

Operations are applied in this order so each step's preconditions are
established by the previous one:

- **4a. Renames and moves** (Confluence → mirror) — `git mv` to the
  final path (rename + move is a single op in history). Move the
  `<page-name>-attachments/` directory alongside the `.md`. Create
  any missing parent directories.
- **4b. Filename collisions** — after renames are computed, siblings
  sharing a sanitized basename get `(page-id)` appended to both.
- **4c. Archive / unarchive** — set `confluence.status: ARCHIVED` (or
  back to `CURRENT`) and update the export header. No path changes.
- **4d. New pages from local-authored `.md` files** — same logic as
  `mdd confluence create-page <file>` ([S09](S09-confluence-command.md)). Default parent is
  inferred from the file's location in the mirror tree: walk up,
  first ancestor whose sibling `.md` has a `confluence.page_id` (or
  whose directory matches a Confluence folder) supplies the parent.
  Fall back to space root with a warning. Title fallback: frontmatter
  `title` → first H1 → filename.
- **4e. Content edits — pulls** — per-page body fetch only for pages
  whose remote `version_number` advanced. Re-render storage → markdown,
  refresh metadata in frontmatter, run attachment sync.
- **4f. Content edits — pushes** — same logic as
  `mdd confluence update-page <file>` ([S09](S09-confluence-command.md)). This is the
  bidirectional half: sync is symmetric.
- **4g. Deletions** — `git rm` the page and its attachments dir.
  `--no-delete` skips this step. Cross-space moves go through this
  path but the run summary names the destination space.
- **4h. Metadata-only refresh** — frontmatter rewrite, no body
  re-render, for label / `updated_at` / `updated_by` / `version_message`
  changes.

### Step 5 — Commit

After all operations are attempted, sync stages all changes
(`git add -A` scoped to the output directory) and creates **one
commit** with a structured Conventional Commit message summarising
counts per category, conflicts skipped, and cross-space moves
detected. Sections with zero items are omitted. If nothing changed,
sync exits 0 with "Nothing to sync." and no commit.

### Step 6 — Optional push

If `--push` is passed sync makes sure the mirror directory is a git
work-tree with an `origin` remote, then hands it to the active mirror
backend. Every provider-specific step below is a backend method, so which
forge this ends up on is a wiring decision, not part of this spec:

- If `.git` is missing, sync runs `git init -b main` and adds the `origin`
  the backend resolves for `MirrorTarget("confluence", <space-key>)`. The
  built-in generic-git backend resolves nothing (a plain clone already has
  its remote); a deployment-specific backend derives one, typically
  `https://<host>/<group>/<space-key>.git` from its own config. This lets
  `--push` bootstrap a previously offline export — the user can
  `mdd confluence sync-space <KEY> --output ./<KEY> --push` and have
  the directory turn into a tracked mirror in one shot.
- After init (or if the repo already existed), all dirty/untracked
  files are staged and committed with the structured Conventional
  Commit message from Step 5. For a fresh init this is the initial
  commit; sections with zero items collapse to the bare subject line.
- Before pushing, sync asks the backend to ensure the remote exists. A
  backend that can create projects does so — covering the cold-start case
  where a space has never been mirrored — and reports `"unreachable"`
  instead of failing when it cannot tell (e.g. a VPN is down, or its CLI
  is missing). In that case the ensure step is skipped and the underlying
  problem surfaces from the push attempt; the user gets one clear error,
  not two.
- The push itself goes through the backend's `push`, which applies its own
  host allow-list plus the [S07](S07-data-protection.md) confidentiality
  blacklist gate. If the current branch has no upstream tracking yet
  (first push), the generic implementation uses
  `git push -u origin <branch>`, rebasing onto `origin/<branch>` first if
  the remote already has commits.

If `--push` is passed but the run produced no commit and the mirror
was already a git repo (truly nothing to do), sync skips the push —
the previous push must have succeeded.

## Behaviour rules

- **Always-on full reconcile.** No CQL incremental, no side-car state. Performance is fine at the space sizes we see.
- **Dirty working tree refuses.** If `git status --porcelain` reports uncommitted changes in the output directory, sync aborts. No `--allow-dirty` escape hatch — manual edits and sync writes must not be commit-mixed.
- **First sync of an empty clone is a normal sync.** No special `--initial` flag; every page classifies as "new (Confluence → mirror)".
- **Best-effort partial failure.** Each operation in a try block; on failure sync records the error, skips, and continues. Commit covers what succeeded; exit code is 1 if anything failed. Next run picks up unfinished work cleanly (idempotent).
- **Manually-managed files are sacred.** A `.md` without `confluence.page_id` and without local-authored-publishable shape is never deleted, moved, or rewritten.
- **`--head`.** Caps the desired-state map (default 10) for testing.
- **`--dry-run`.** Computes the full plan and prints the would-be summary without touching files, the working tree, or Confluence. Exit 0.
- **`--read-only`.** Suppresses every mirror → Confluence write step: step 4d (create page from local-authored file), step 4f (LOCAL_PUSH content push via `update page`), and step 4i (Office publishing).  Local mirror updates from the remote, the dirty-tree check, and the commit all still run, so the user gets a clean snapshot in a single git commit with no risk of writing back to Confluence.  Composes with `--dry-run` (which is the *stronger* read-only mode — it produces no commit either).
- **`--no-attachments`.** Skips both body-image downloads and the per-page attachment sync.  Frontmatter ends up with an empty `attachments:` list.  Useful for fast text-only previews and for unblocking exports when a specific attachment fails repeatedly.
- **Atomicity.** Each `git mv` / `git rm` is atomic. On a hard crash mid-sync, the next run rebuilds state from the working tree and reconciles again — idempotent by construction. The runtime `git` binary becomes a new external dependency for sync.

## Conflicts

The conflict that matters in practice is **simultaneous edit**:
local file edited, Confluence page also edited by someone else, both
diverged from the last-known common version. Sync detects this when
a local edit is queued for push but the remote `version_number` has
advanced past the local frontmatter `version_number`. Both push and
pull are skipped for that page; it's recorded as a conflict; user
resolves with `mdd confluence update-page <file>`, which shows the
diff and either takes the local version or refreshes from Confluence.
Same conflict semantics as `update page` in [S09](S09-confluence-command.md).

## Config

No new config keys. Sync uses the same `confluence.url`,
`confluence.username`, `confluence.api_token`, and per-space
`output_dir` from [S09](S09-confluence-command.md). The mirror-repo
clone detection described there applies unchanged.

## Frontmatter additions

S09's frontmatter schema is the source of truth. Sync uses every
field that schema defines; no new fields are required. Two
clarifications:

- `confluence.status: ARCHIVED` is set on archive transitions and cleared on unarchive (S09 already defines `status` as `CURRENT | DRAFT | ARCHIVED`).
- `confluence.version_number` and `confluence.updated_at` are the load-bearing fields for the conflict check and the changed-page filter; sync rewrites them on every run that touches a page.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [007-data-protection](S07-data-protection.md) — confidentiality blacklist gate applied on `--push`
- [009-confluence-command](S09-confluence-command.md) — HTTP client, URL parsing, filename sanitization, frontmatter schema, attachment sync, body conversion, and per-verb primitives reused

## Out of scope

- Comments — same as [S09](S09-confluence-command.md).
- Confluence-side bulk operations (e.g. archiving via `mdd`).
- Cross-space-move automation (we warn; user runs sync on the destination mirror).
- A `--commit-per-change` mode. Single commit with structured summary is the default.
- Concurrency-safe runs (two `mdd confluence sync` processes against the same mirror) — single-writer assumption.
- Watch mode (long-running sync reacting to webhook deliveries).
- Sync against multiple spaces in one run.
- Sync of comments, page restrictions, page properties.
