# 001 - Handling Confluence page moves, renames, and archives

**Status:** Research notes. Not an implementation spec.

**Problem:** Spec 009 (`mdd confluence`) describes export and round-trip
update of pages, but does not describe what happens when a page that was
previously exported has been **moved**, **renamed**, **archived**, or
**deleted** on the Confluence side between sync runs. As written, a
re-export would create a new file at the new path while leaving the old
file in place, producing duplicates and stale content in the GitLab
mirror.

We want the opposite: when something on the Confluence side shuffles
around, the mirror repo should track the change as a normal git
rename/move/delete, so that history is preserved and the mirror is a
faithful reflection of the live space.

This document captures findings on what Confluence's API exposes, what
identity is stable, and a recommended reconciliation strategy. It
deliberately stops short of prescribing CLI flags, file layouts, or
commit-message wording — those belong in a follow-up implementation
spec.

## What Confluence Cloud exposes

### Page identity

- **`id`** (numeric, string in v2 responses) is **stable across
  rename, move within space, move across spaces, archive, and
  unarchive**. It only changes on **copy** (which produces a new page).
  This is the single anchor for reconciliation — every other field is
  mutable.
- `title`, `parentId`, `spaceId`, and `status` are all mutable and may
  change between syncs without the page ID changing.

### Lifecycle states (`status` field)

The v2 API surfaces five states relevant to mirroring:

| Status      | Meaning                                                    | Visible in default `GET /spaces/{id}/pages`? |
|-------------|------------------------------------------------------------|----------------------------------------------|
| `current`   | Live, published page                                       | Yes                                          |
| `draft`     | Unpublished draft (per-user)                               | No (must request)                            |
| `archived`  | Soft-archived; still readable, hidden from default views   | No (must request)                            |
| `trashed`   | In the trash, recoverable for ~30 days                     | No (must request)                            |
| (deleted)   | Hard-deleted; `GET /pages/{id}` returns 404                | No                                           |

- `GET /spaces/{id}/pages?status=current,archived` returns both live and
  archived pages — the union we likely want to mirror.
- Trashed pages can be listed with `?status=trashed` but are not part
  of the canonical tree from a reader's perspective.
- A previously-known page that returns 404 has been hard-deleted (or
  emptied from trash). It cannot be distinguished from "never existed"
  by the API alone — we tell them apart by checking whether we have it
  locally.

### Listing the tree

- `GET /spaces/{id}/pages` is paginated (cursor-based, default
  `limit=25`, max `250`). One pass returns enough to build a complete
  tree: `id`, `parentId`, `parentType`, `title`, `status`,
  `version.number`, `version.createdAt`, `position`. Body is *not*
  included by default — fetched per-page only when needed.
- Folders (`type=folder`) appear as parents in the tree but are not
  pages and require `GET /folders/{id}` for metadata. Spec 009 already
  handles this for the create path; the same machinery applies.

### What is **not** available

- **No global change feed.** There is no "give me everything that
  changed in this space since timestamp T" endpoint that reports moves,
  renames, archives, or deletes as discrete events. Per-page
  `/pages/{id}/versions` exists but is per-page and only covers body
  edits.
- **CQL** (`lastmodified > "..."`) catches body edits and some title
  changes but is unreliable for moves and archives. It is useful as an
  optimization but cannot be the primary detection mechanism.
- **No "tombstone" listing.** When a page is hard-deleted, nothing in
  the API tells us it ever existed; we only know because we kept a
  local record.

**Implication:** detection of moves/renames/archives/deletes must be
done by **diffing the current Confluence tree against the local mirror
state**. There is no event stream to consume.

## Detecting each lifecycle event

The reconciliation algorithm is straightforward once page IDs are
treated as primary keys:

1. **Build "desired state"** from one paginated tree fetch:
   `{ page_id → (title, parent_id, status, version, position) }` for
   `status ∈ {current, archived}`.

2. **Build "current state"** from the local mirror by walking the tree
   and reading frontmatter:
   `{ page_id → (path, title, parent_id, status, version) }`. Files
   without a `page_id` in frontmatter are treated as user-authored and
   ignored (never deleted).

3. **Diff the two maps** and classify each page:

   | Page ID in desired | Page ID in local | Other field changes              | Event                     |
   |--------------------|------------------|----------------------------------|---------------------------|
   | Yes                | No               | —                                | **New page**              |
   | Yes                | Yes              | None                             | No-op (or content edit)   |
   | Yes                | Yes              | `title` differs                  | **Rename**                |
   | Yes                | Yes              | `parent_id` differs              | **Move**                  |
   | Yes                | Yes              | `title` *and* `parent_id` differ | **Rename + move**         |
   | Yes                | Yes              | `status` flipped to `archived`   | **Archive**               |
   | Yes                | Yes              | `status` flipped from `archived` | **Unarchive**             |
   | No                 | Yes              | —                                | **Trashed or deleted**    |
   | Yes (cross-space)  | Yes (this space) | `space_id` differs               | **Cross-space move**      |

4. **Apply** the changes against the working tree using `git mv` and
   `git rm` (so renames are tracked as renames in git, not as
   delete+add) and rewrite frontmatter. Then commit.

This is O(N) per sync but N is "pages in one space" — small. The
expensive call is per-page body fetch, which we already gate on
`version.createdAt` for content edits and skip entirely for pure
metadata changes.

## Recommendation: how to handle each event

### Rename

Confluence title change → file basename change.

- `git mv <old-path> <new-path>` where `<new-path>` is computed by
  re-running the existing filename-sanitization logic against the new
  title.
- Update the file's frontmatter `title`, then re-render body if the
  page's `version` also moved.
- If the rename causes a sibling collision, fall through to the
  existing collision strategy (append `(<page-id>)`).

### Move (parent change)

Confluence parent change → file moves to a different directory in the
mirror.

- `git mv <old-dir>/<file>.md <new-dir>/<file>.md`. Move the
  `<page-name>-attachments/` directory alongside it.
- If the new parent directory does not exist locally yet, create it.
- After the move, prune any directory that became empty as a result —
  but only if it never contained a `.md` file with a `page_id` (i.e.
  it was a pure container directory). Empty directories aren't tracked
  by git, so this is mostly cosmetic; the key is not to leave orphaned
  attachments folders.

### Combined rename + move

Detected as both diffs at once. Apply as a single `git mv` to the
final destination, not as two staged operations — one rename in git
history is more legible than two.

### Archive

A page going to `status=archived` is **not** a deletion: the page still
exists, has a body, and may be unarchived later. Three plausible
strategies, in order of preference:

1. **In-place with frontmatter flag (recommended).** Leave the file
   where it is, set `confluence.status: ARCHIVED` in frontmatter, and
   adjust the export header to mention the archived state and the date
   of archival. Future readers of the mirror see the page is archived
   without losing the location. Re-export still picks up subsequent
   edits if anyone touches the archived page.
2. **Relocate under `_archived/`** (mirror-root subtree that mirrors
   the live tree shape). Cleaner separation but rewrites paths on every
   archive/unarchive — more churn in git, more complexity in the path
   logic.
3. **Treat archive as deletion** (`git rm`). Simplest, but loses
   content from the mirror. The user explicitly does not want this.

**Recommendation:** option 1. Preserves content, minimal churn,
unarchive is a one-line frontmatter flip.

### Unarchive

Inverse of archive: clear the `ARCHIVED` flag, refresh the export
header. Body re-fetch happens on the normal `version.createdAt` path.

### Trashed or hard-deleted

A page ID present locally but absent from the desired-state map (after
querying `current,archived`):

- Optionally probe `?status=trashed` and `GET /pages/{id}` to
  distinguish "in trash" from "hard-deleted" — useful for the commit
  message but not strictly required for the action.
- `git rm <path>` and `git rm -r <attachments-dir>`. Git's history
  preserves the content; recovery is `git show <sha>:<path>` if
  someone needs it back.

Open question for the impl spec: should there be a `--no-delete` /
`--keep-removed` safety flag for the first few rollouts, given that a
sync run could in principle delete a large slice of the mirror if
someone misconfigures the Confluence side? I'd lean yes, defaulting
off, since the audit trail in git already mitigates the worst case.

### Cross-space move

A page that vanished from this space's tree but still resolves at
`GET /pages/{id}` with a different `spaceId`. From this mirror's
perspective it looks like a deletion. Two possible behaviors:

- **Treat as deletion in this mirror, warn the user** with the new
  space key so they know to run the sync against the other mirror
  (`mdd/confluence/<other-space>`).
- **Hand it off automatically** by computing the new mirror's path and
  doing the `git mv` across repos. Cute but introduces inter-repo
  coordination we probably don't want in v1.

**Recommendation:** warning-only for now. Cross-space moves are rare
and merit human attention.

### Page → folder conversion (and vice versa)

Confluence supports converting a page to a folder. The page ID does
not survive: a folder has its own ID space (`/folders/{id}`). From the
mirror's perspective this is a delete (page gone) plus a structural
change in the parent (a directory now where a `.md` was). Treat as
deletion of the page; the folder doesn't need a file of its own.

## State source: frontmatter vs. side-car index

Two ways to know what page IDs exist locally:

1. **Walk the mirror and read frontmatter on each sync.** Spec 009
   already requires `page_id` in frontmatter for round-trip; we can
   reuse it. O(N) file reads per sync, but N is small and reads are
   fast. Resilient: no separate state file to drift out of sync.

2. **Maintain a `.mdd-confluence-state.json` side-car** at the mirror
   root mapping `page_id → path/title/version/...`. Faster on huge
   spaces, but introduces a second source of truth, which can drift if
   anyone edits files manually or via another tool. Adds a commit
   noise file.

**Recommendation:** option 1. The frontmatter is already
load-bearing, the cost is negligible at expected space sizes, and
"every file is self-describing" matches the spec 009 design.

## Identifying which file represents which page

When walking the mirror, two paths can claim the same page:

- A user manually copied a `.md` file (now two files have the same
  `page_id` in frontmatter).
- A previous failed sync left both old and new paths in place.

Defensive behavior:

- On scan, if the same `page_id` is found in two files, abort the sync
  with a clear error naming both paths. Do not guess. Manual cleanup.
- A `.md` with malformed or missing `page_id` is treated as
  user-authored — left untouched, reported in the summary so the user
  knows it isn't being managed.

## Commit shape

Two reasonable approaches; defer the choice to the implementation
spec, but recommend the second:

1. **One commit per category per sync** — separate commits for
   renames, moves, archives, deletes, and content updates. Cleanest
   `git log`, easiest to revert one category. Most commits per sync.
2. **One commit per sync run** with a structured message body
   summarizing operations:
   ```
   chore(confluence): sync space SPACE

   - 3 pages renamed
   - 1 page moved
   - 2 pages archived
   - 1 page removed (trashed)
   - 12 pages content-updated
   ```
   Less granular history, less noise, matches the existing
   `chore(mirror): sync from <source-system>` convention from spec
   008.

**Recommendation:** option 2 by default. Add `--commit-per-change`
later if the team finds the summary too coarse to revert from.

## What goes in the implementation spec (not here)

- Exact CLI surface: is reconciliation always-on inside `export space`,
  or is it a separate `mdd confluence sync` subcommand?
- Safety flags: `--no-delete`, `--dry-run`, `--archive-mode=
  in-place|relocate|delete`.
- Whether to integrate with `mdd gitlab push` so a sync-and-push is one
  command, and whether the blacklist gate from spec 007 still applies
  to deletion commits (probably yes — same reasoning).
- Telemetry/output: what the summary line at the end of a sync looks
  like.
- Failure handling mid-sync: do we commit partial progress, or
  all-or-nothing? Suggest all-or-nothing per category, since git
  rollback is cheap and partial state is confusing.
- Behavior when running against a mirror clone that has uncommitted
  local changes — almost certainly refuse, but the wording should be
  worked out in the spec.

## Useful API references

- v2 page list: `GET /wiki/api/v2/spaces/{spaceId}/pages?status=current,archived&limit=250`
- v2 page fetch: `GET /wiki/api/v2/pages/{id}?body-format=storage&include-version=true&include-labels=true`
- v2 trash listing: `GET /wiki/api/v2/spaces/{spaceId}/pages?status=trashed`
- v2 folder fetch: `GET /wiki/api/v2/folders/{id}`
- v2 versions: `GET /wiki/api/v2/pages/{id}/versions`
- CQL search (v1, still supported): `GET /wiki/rest/api/content/search?cql=space=SPACE+AND+lastmodified+>+"YYYY-MM-DD"`
