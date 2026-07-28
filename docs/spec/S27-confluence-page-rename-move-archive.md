# 027 - confluence page rename / move / archive

**Purpose:** Imperative `mdd` subcommands (`rename-page`, `move-page`, `archive-page`, `unarchive-page`) that mutate a Confluence page then refresh the local mirror.

**Status:** Implemented (2026-05-23)

## Introduction

These commands close the gap left by [S14](S14-confluence-sync.md): sync is bidirectional but
propagation is Confluence → mirror for structural changes (rename, move, archive). Anything done
locally to a page's title, parent, or status is overwritten on the next sync. These commands let
users make those changes from the mirror side and have them flow the right direction.

This spec extends [S09](S09-confluence-command.md) (page primitives, frontmatter,
storage↔markdown), [S14](S14-confluence-sync.md) (sync's per-page refresh logic, dirty-tree
posture, single-commit summary), and [S26](S26-managed-elsewhere.md) (managed-elsewhere
fail-closed gate). Read those first.

## Requirements

- Provide four subcommands: `rename-page`, `move-page`, `archive-page`, `unarchive-page` under `mdd confluence` (hyphenated form, consistent with existing `export-page` / `create-page` / `update-page` / `sync-space`).
- Resolve the target page from a local `.md` file's `confluence.page_id` frontmatter; reject files without it.
- For `move-page`, accept `--parent` as a page ID, Confluence URL, or path to another local `.md`.
- Enforce same-space precondition for `move-page`; error on cross-space moves. Cross-space moves are not supported via `mdd`; the user must perform them in the Confluence UI and let `mdd confluence sync-space` reconcile both mirrors.
- For same-space `move-page`, the local file MUST land in the new parent's mirror directory after the operation completes. If any link in the new parent's ancestor chain is not yet materialised in the mirror (the page exists as a flat `.md` but not as a directory, or is absent entirely), `move-page` materialises the missing links by pulling them — same model as [S14](S14-confluence-sync.md) sync — before performing the local file move. See [§Local tree materialisation on move](#local-tree-materialisation-on-move).
- Refuse mutations on managed-elsewhere pages per [S26](S26-managed-elsewhere.md).
- Abort if the working tree has uncommitted changes within the output directory.
- Detect version drift (Confluence `version_number` ahead of local frontmatter) and abort before writing.
- Print a confirmation prompt before any API call; `--yes` skips it; `--dry-run` skips both prompt and call.
- After a successful API call, run a per-page refresh: compute new local path, `git mv` the file (and attachments dir), rewrite frontmatter, and flip frontmatter `confluence.status` between `CURRENT` and `ARCHIVED` for archive/unarchive.
- Commit the result with a structured `chore(mirror):` message; `--no-commit` stages and exits without committing.
- Print a recovery hint and exit 1 if the API call succeeded but the local refresh failed.
- Exit 0 on success or clean dry-run; exit 1 on any failure.

## Design Approach

- Follow the same imperative model as [S09](S09-confluence-command.md)'s `update-page`: Confluence is the source of truth, local file is updated after the API call, not before.
- Keep the direction unambiguous: the commands push from mirror to Confluence, not the reverse; sync handles Confluence → mirror for structural events.
- Reuse `mdd.confluence.apply` (`git_mv` + `compute_rename_path` + `resolve_collision_pair` + `is_dirty` already used by [S14](S14-confluence-sync.md)) rather than duplicating it.
- Reuse the per-page refresh logic already in `mdd.confluence.sync.renames` (the bulk event handlers `apply_renames_moves` and `apply_archive_unarchive`) by calling them with single-element event lists. If that proves clumsy, extract the per-event inner helpers (`_apply_one_rename_move`, `_apply_one_archive`) to a stable public surface. Avoid forking a parallel implementation.
- Use Confluence Cloud v2 API for rename/move; prefer the v2 archive/unarchive endpoint with v1 fallback; encapsulate choice in `confluence.client`.
- Four orchestrators (`rename_page`, `move_page`, `archive_page`, `unarchive_page`) are thin wrappers over five reusable checks plus the existing apply layer; most surface area is argument parsing, confirmation, and error messages.
- No new dependencies: uses existing `httpx`, `lxml`, `pyyaml`, and the `git` binary required by [S14](S14-confluence-sync.md).

## Implementation Notes

- **Code structure** (extends [S09](S09-confluence-command.md), [S14](S14-confluence-sync.md), [S26](S26-managed-elsewhere.md); module layout reflects post-[S36](S36-module-structure.md) sub-package split)
```
src/mdd/commands/
  confluence.py              # add 'rename-page', 'move-page',
                             #   'archive-page', 'unarchive-page' subcommands
src/mdd/confluence/
  mutate.py                  # NEW — rename_page(), move_page(),
                             #       archive_page(), unarchive_page() orchestrators
  client/__init__.py         # extend put_page() (parent_id, status) + add
                             #   archive_page() / unarchive_page() primitives
                             #   (encapsulate v2 vs v1 fallback per [S09](S09-confluence-command.md))
  apply.py                   # reuse is_dirty(), compute_rename_path(),
                             #   git_mv(), move_attachments_alongside(),
                             #   resolve_collision_pair() from [S14](S14-confluence-sync.md)
  sync/renames.py            # extract per-event helpers from the existing
                             #   apply_renames_moves() / apply_archive_unarchive()
                             #   bulk handlers so mutate.py can call them with a
                             #   single page (or call the bulk form with a
                             #   one-element event list)
tests/commands/
  test_confluence_rename.py
  test_confluence_move.py
  test_confluence_archive.py
tests/confluence/
  test_mutate.py             # orchestrator unit tests with mocked client + tmp git repo
  fixtures/mutate/           # before/after working-tree layouts
```

- **Reuse, don't duplicate.** The following already exists and is the canonical implementation — call it, do not fork:
  - `mdd.confluence.apply.is_dirty(repo_dir)` — dirty-tree check shared with sync.
  - `mdd.confluence.apply.compute_rename_path()`, `git_mv()`, `move_attachments_alongside()`, `resolve_collision_pair()` — the [S14](S14-confluence-sync.md) collision rule (`(page-id)` suffix on both siblings).
  - `mdd.confluence.paths.sanitize(title)` / `disambiguate(path, page_id)` — filename derivation per [S09](S09-confluence-command.md).
  - `mdd.confluence.frontmatter.read()` / `write()` — YAML I/O.
  - `mdd.confluence.url.parse(ref, expected_host=...)` — parses numeric IDs, full URLs, short URLs; used for `--parent <url>`.
  - `mdd.confluence.managed.classify_page()`, `load_managed_config()`, `build_page_info_from_page_data()` — [S26](S26-managed-elsewhere.md) gate; same posture as `update-page`.
  - `mdd.confluence.client.ConfluenceClient.put_page()` — already used by `update-page`. Currently takes `(page_id, title, body_xhtml, version, message)` and hardcodes `status="current"`. **For S27, extend it** (or wrap it) to accept `parent_id` and `status` so move/archive/unarchive can reuse the same path; see "API calls" below.
  - `mdd.confluence.sync.renames.apply_renames_moves()` / `apply_archive_unarchive()` — bulk event handlers; the per-event inner functions are private (`_apply_one_rename_move`, `_apply_one_archive`). Either call the bulk form with a one-element `SyncEvent` list, or promote the helpers to a stable internal surface. **Choose one approach during implementation and apply it consistently.**

  A natural shape:

```python
# in mdd.confluence.mutate (NEW)
def rename_page(file, new_title, *, client, config, repo) -> int:
    page_state = _load_local(file)
    _check_managed(page_state, client, config)
    _check_dirty(repo)
    _check_version(page_state, client)
    api_result = client.put_page(
        page_state.page_id,
        title=new_title,
        body_xhtml=_fetch_current_body(client, page_state.page_id),
        version=page_state.version + 1,
        message=message,
    )
    # Build a single RENAME SyncEvent and reuse the [S14] apply path:
    event = _event_from_api_result(api_result, EventKind.RENAME)
    apply_renames_moves([event], mirror_state, output_dir,
                        page_to_outdir, used_paths, summary)
    if not no_commit:
        repo.commit(_render_subject("rename", page_state, api_result))
    return 0
```

  The same pattern applies to `move_page` (event kind `MOVE`), `archive_page` (`ARCHIVE`), and `unarchive_page` (`UNARCHIVE`).

- **Version-drift check.** `update_page` in `mdd.confluence.update` already does this inline (compares local frontmatter `version` against the remote `version.number`). For S27, extract the check into a small reusable helper (e.g. `mdd.confluence.apply.check_version_drift(local_version, remote_version)`) and call it from both `update_page` and the four mutate orchestrators. Do not copy-paste the check.

- **API endpoint discovery.** v2 archive/unarchive endpoints have moved around in Atlassian's API history. At implementation time, confirm the current path (Atlassian docs + a single manual call against a scratch space) and centralise the choice in `confluence.client.archive_page` / `unarchive_page`. Tests mock these primitives, so the choice doesn't ripple through the test suite.

- **Confluence body re-send.** v2 PUT requires the full page representation, so rename and move must re-send the current body XHTML. Fetch it via `client.get_page(page_id, body_format="storage")` (or the equivalent get already in use). The current `put_page()` signature accepts `body_xhtml`; reuse it as-is.

- **Tests**
  - Unit: each command's argument parsing (markdown file form; parent variants for `move`).
  - Unit: managed-elsewhere refusal (mock client + [S26](S26-managed-elsewhere.md) classification fixture).
  - Unit: dirty-tree refusal (real `tmp_path` git repo with an uncommitted change).
  - Unit: version-conflict refusal (mock client returns higher `version_number` than local frontmatter).
  - Unit: cross-space rejection on `move`.
  - Unit: rename + collision (sibling with same sanitised basename) → both files get `(page-id)` suffix per [S14](S14-confluence-sync.md) rule.
  - Unit: archive flips frontmatter `status` and export header; unarchive flips them back.
  - Unit: `--dry-run` makes no API calls and no working-tree changes (assert mock client receives zero calls).
  - Unit: `--no-commit` leaves staged changes; no new commit.
  - Unit: refresh-failure recovery message when API succeeds but `git mv` fails (simulate via permissions error).
  - Integration (`@pytest.mark.integration`): live Cloud calls against a scratch space; gated on `MDD_CONFLUENCE_TEST=1`. One rename, one move, one archive, one unarchive in sequence.

## Subcommands

```
mdd confluence rename-page    <markdown-file> <new-title>
                              [--config <file>] [--message <msg>]
                              [--dry-run] [--no-commit] [--yes]
mdd confluence move-page      <markdown-file> --parent <id|url|file>
                              [--config <file>] [--message <msg>]
                              [--dry-run] [--no-commit] [--yes]
mdd confluence archive-page   <markdown-file>
                              [--config <file>] [--message <msg>]
                              [--dry-run] [--no-commit] [--yes]
mdd confluence unarchive-page <markdown-file>
                              [--config <file>] [--message <msg>]
                              [--dry-run] [--no-commit] [--yes]
```

- The first positional is always a path to the local `.md` whose
  `confluence.page_id` frontmatter identifies the target page. No
  page-id / URL form — the imperative workflow assumes the user is
  in the mirror clone editing files. (Future: a `--page` flag for
  ad-hoc use outside a clone if it actually comes up.)
- `<new-title>` for `rename-page` is the new page title verbatim.
  Quote it if it contains spaces.
- `--parent` for `move-page` accepts a page ID, a Confluence page
  URL (parsed via `mdd.confluence.url.parse` per [S09](S09-confluence-command.md)),
  **or** a path to another local `.md` whose frontmatter `page_id`
  is the parent. The markdown-file form is the natural one inside
  a clone.
- `--message` sets the version comment that appears in Confluence
  page history. Defaults: `"Renamed via mdd"`, `"Moved via mdd"`,
  `"Archived via mdd"`, `"Unarchived via mdd"`.
- `--dry-run` prints the planned operation (API call, local
  rename/move, frontmatter changes) without touching Confluence or
  the working tree.
- `--no-commit` skips the commit step; the working tree is left
  with staged changes for the user to commit.
- `--yes` skips the confirmation prompt (see "Confirmation" below).

## Why this exists separately from sync

[S14](S14-confluence-sync.md)'s sync detects rename / move / archive on the Confluence
side and replays them as `git mv` / frontmatter rewrites in the
mirror. The arrow only points one way for those events:

- A user who renames a file locally (`git mv old.md new.md`) does
  not rename the Confluence page — the next sync sees a "new local
  file" + "missing remote → trashed" situation, which at best
  produces a confusing diff and at worst a duplicate page if sync
  publishes the local file as new.
- Moving a file to a different directory has the same problem.
- Setting `confluence.status: ARCHIVED` in frontmatter does not
  archive the page; the next sync sees a status mismatch and
  reverts the frontmatter.

The fix is to make the Confluence API call the source of truth and
have `mdd` apply it, then refresh the local file. Same model as
[S09](S09-confluence-command.md)'s `update-page` for body edits — pushed to
Confluence first, frontmatter rewritten from the response.

## Behaviour

**Identity resolution.** Read `<markdown-file>`, parse
frontmatter, require `confluence.page_id`. If absent or
malformed, exit 1 with a clear message ("This file is not yet
published; run `mdd confluence create-page` first."). For
`move-page`, resolve `--parent`:
- numeric → page ID
- URL → parse via `mdd.confluence.url.parse` ([S09](S09-confluence-command.md));
  reject host mismatches with `URLMismatchError`
- path with `.md` extension → read its frontmatter, take
  `confluence.page_id` (error if absent)

**Same-space precondition.** The page being moved and its target
parent must be in the same space. Cross-space moves are out of
scope (same posture as [S14](S14-confluence-sync.md)). Error: "Cross-space moves are
not supported. Move via the Confluence UI, then run `mdd
confluence sync` against both spaces." The check runs before any
local materialisation; ancestor materialisation never crosses a
space boundary.

### Local tree materialisation on move

When `move-page` succeeds on the Confluence side, the local mirror
must end up with the moved file inside the new parent's mirror
directory. The mirror layout per [S14](S14-confluence-sync.md) is:

- A page with no children is represented as a flat `Title.md`
  file.
- A page with at least one child is represented as a
  `Title/` directory containing `Title/_index.md` plus its child
  pages and subdirectories.

A move can therefore require any combination of three changes
along the new parent's ancestor chain (parent up to space root):

1. **Promote a flat file to a directory.** The new parent is
   currently a leaf (`Parent.md`) because it had no children
   before this move. Convert to `Parent/_index.md` so it can hold
   the moved child. Repeat up the chain for every ancestor that
   is currently a leaf and needs to become a directory because of
   this move (rare in practice, but possible).
2. **Pull a missing ancestor.** The ancestor page exists on
   Confluence but has not been pulled into the local mirror at
   all. Fetch its storage XHTML, convert to markdown, write
   `Title/_index.md` (with directory promotion as needed),
   refresh frontmatter from the API response. Same code path as
   [S14](S14-confluence-sync.md)'s pull pipeline, scoped to a
   single page.
3. **`git_mv` the moved file** into the now-materialised parent
   directory.

The materialisation walks the ancestor chain from the new parent
upward, stopping at the first ancestor whose mirror representation
already exists in the expected shape. The walk MUST be bounded by
the space root; an ancestor that is reported as outside the page's
space is a precondition failure (treat as the same-space refusal
above).

Materialised ancestors are committed as part of the same
`chore(mirror): move ...` commit; the user does not need to run a
follow-up `sync-space`. The commit body MUST list every
materialised path so the change is auditable. Example:

```
chore(mirror): move "RFC-7" to "Archive 2026"

Confluence -> mirror:
  page_id: 12345
  space:   ENG
  url:     https://example.atlassian.net/wiki/spaces/ENG/pages/12345
materialised ancestors (pulled from Confluence):
  docs/Archive 2026/_index.md  (page 13500)
moved:
  docs/RFC-7.md -> docs/Archive 2026/RFC-7.md
```

If any materialisation step fails (API error, conversion error,
git error), the local refresh is aborted with the same recovery
hint as a normal refresh failure: "Confluence updated successfully
but local refresh failed: <error>. Run `mdd confluence sync-space`
to bring the mirror back in agreement." Partial materialisation is
acceptable on failure — `sync-space` will reconcile any half-built
state. The Confluence-side move is the source of truth and is not
rolled back.

[S26](S26-managed-elsewhere.md) classification applies to
materialised ancestors: pulling a managed-elsewhere ancestor uses
the same content fetch as `sync-space`. The managed-elsewhere
gate's fail-closed posture applies only to write operations
against Confluence, not to local reads, so this path is unchanged
from sync.

**Managed-elsewhere refusal.** Before any API call, classify the
page per [S26](S26-managed-elsewhere.md) by calling
`classify_page()` against the `ManagedConfig` returned from
`load_managed_config()`, with `PageInfo` built via
`build_page_info_from_page_data()` (same call sequence
`update_page` uses today). A managed-elsewhere classification
refuses the mutation with the publisher's `message`. This is the
same fail-closed posture [S26](S26-managed-elsewhere.md) applies
to `update-page` and `sync-space` pushes — rename / move /
archive are all writes.

**Confidentiality.** These commands write to Confluence, not to the git
mirror. [S07](S07-data-protection.md)'s blacklist is about
Confluence → mirror publishing and does not gate these calls. The
`--no-commit` default still applies a normal local commit (same as `mdd
confluence sync-space`); pushing the mirror is a separate step and runs
through the mirror backend and the
[S07](S07-data-protection.md) gate as usual.

**Dirty working tree.** Call `mdd.confluence.apply.is_dirty()`
against the output directory; if true, abort with the same
message as sync: `"Mirror has uncommitted changes. Commit,
stash, or discard before running."`. Same reasoning — manual
edits and mdd-managed git operations must not commit-mix.

**Confirmation.** Each command prints a one-line preview of the
planned mutation and prompts for confirmation, mirroring
[S09](S09-confluence-command.md)'s `update-page` posture
(Confluence is shared state). `--yes` skips the prompt;
`--dry-run` skips both the prompt and the actual call. Examples:
```
Rename: "Old Title" -> "New Title"
        space ENG, page 12345
Confluence URL: https://example.atlassian.net/wiki/spaces/ENG/pages/12345
Proceed? [y/N]
```
```
Move: "Architecture Plan" (page 12345)
      from parent "Design Docs" (page 12000)
      to   parent "Archive 2026" (page 13500)
Proceed? [y/N]
```

**API calls** (Confluence Cloud v2 unless noted; encapsulate any
v1 fallback in `confluence.client` per [S09](S09-confluence-command.md))
- **Rename**: `PUT /wiki/api/v2/pages/{id}` with current
  `version.number+1`, new `title`, unchanged body, status, and
  `parentId`. Body must be re-sent because v2's PUT requires a
  full page representation; fetch current storage XHTML as part
  of the operation. The existing `ConfluenceClient.put_page()`
  already accepts `body_xhtml`; **extend it to accept optional
  `parent_id` and `status`** (currently hardcoded to `"current"`)
  so rename/move/unarchive can reuse the same primitive. Add
  these params with sensible defaults to avoid breaking
  `update_page`'s call site.
- **Move**: same extended PUT with new `parentId`, unchanged
  title / body / status.
- **Archive**: prefer the v2 archive endpoint
  (`POST /wiki/api/v2/pages/{id}/archive` or the equivalent
  current path — confirm at implementation time and centralise
  in `confluence.client.archive_page`). Fall back to v1
  (`PUT /wiki/rest/api/content/{id}` with `status: "archived"`)
  only if v2 is unavailable. The `version_message` from
  `--message` is attached where the API supports it.
- **Unarchive**: the inverse — v2 unarchive endpoint, or v1 PUT
  with `status: "current"`.

If the page's current Confluence `version_number` does not match
the local frontmatter's `version_number`, abort with the same
conflict message as `update-page`: "Page was edited on
Confluence since last sync. Run `mdd confluence sync-space` (or
`update-page`) first." This applies to all four commands — we
don't quietly push past someone else's edit. Reuse the version
check that already lives inline in `update_page`; extract it to
a small helper (e.g. `apply.check_version_drift()`) and call it
from both call sites.

**Per-page refresh.** After a successful API call, the local
state is brought into agreement with Confluence by running the
same per-page refresh logic [S14](S14-confluence-sync.md) uses
for a single page. The concrete handlers in
`mdd.confluence.sync.renames` are:

- `apply_renames_moves(events, mirror, output_dir,
  page_to_outdir, used_paths, summary)` — handles `RENAME`,
  `MOVE`, `RENAME_MOVE` event kinds; performs `git_mv` +
  `move_attachments_alongside` and updates `mirror.tracked`.
- `apply_archive_unarchive(events, mirror, summary)` — handles
  `ARCHIVE` / `UNARCHIVE` event kinds; rewrites
  `confluence.status` in frontmatter and pins mtime.

Steps:

1. Fetch the page's current metadata (the response from the PUT
   typically includes everything needed; if a v1 archive call
   only returns minimal fields, follow with `GET
   /wiki/api/v2/pages/{id}?include-labels=true&include-version=
   true`).
2. Build a single `SyncEvent` representing the operation:
   - `EventKind.RENAME` for `rename-page`
   - `EventKind.MOVE` for `move-page`
   - `EventKind.ARCHIVE` / `UNARCHIVE` for archive / unarchive
3. Compute the new local path:
   - **rename**: new filename derived from new title via
     `mdd.confluence.paths.sanitize()` and
     `apply.compute_rename_path()`.
   - **move**: new directory derived from the new parent's
     ancestor chain in the mirror tree. If any ancestor is not
     yet materialised locally, pull the missing pages first
     (see [§Local tree materialisation on move](#local-tree-materialisation-on-move)).
   - **archive / unarchive**: no path change.
4. Call `apply_renames_moves([event], ...)` or
   `apply_archive_unarchive([event], ...)` as appropriate. The
   [S14](S14-confluence-sync.md) collision rule (append
   `(page-id)` to both siblings) is already implemented in
   `apply.resolve_collision_pair()` and invoked by
   `compute_rename_path()`.
5. Rewrite frontmatter via
   `mdd.confluence.frontmatter.write()`: `title`, `parent_id`,
   `status`, `version`, `version_message`, `updated_at`,
   `updated_by`, `exported_at`. (Body is unchanged for these
   operations — we only edited metadata, not the page body — so
   no storage→markdown re-conversion is needed.) Note: the
   existing `_apply_one_archive` already handles the
   `status` flip but does **not** update version /
   updated_at / updated_by — those come from the API response
   and must be written by the mutate orchestrator.
6. **Export header for archive / unarchive.** S14 step 4c
   mentions "update the export header" but the current
   `mdd.confluence.header` module has no archived variant, and
   `_apply_one_archive` does not touch the header — only the
   frontmatter status. For S27, the minimum-viable behaviour is
   to match what sync does today: flip `confluence.status` only,
   leave the export header alone. If an archived-variant
   blockquote is wanted, add it as a follow-up that updates
   `header.py` and the sync path together so both code paths
   stay aligned.

If the per-page refresh fails (e.g. network error mid-flight,
disk error during `git mv`), the Confluence-side change is
already applied and is the source of truth. Print a clear
recovery hint: "Confluence updated successfully but local
refresh failed: <error>. Run `mdd confluence sync-space` to
bring the mirror back in agreement." Exit 1.

**Commit.** After a successful refresh, `git add -A` (scoped to
the output directory) and `git commit` with a structured
message:

```
chore(mirror): rename "Old Title" -> "New Title"

Confluence -> mirror:
  page_id: 12345
  space:   ENG
  url:     https://example.atlassian.net/wiki/spaces/ENG/pages/12345
```

Subjects per command:
- `chore(mirror): rename "<old>" -> "<new>"`
- `chore(mirror): move "<title>" to "<new-parent-title>"`
- `chore(mirror): archive "<title>"`
- `chore(mirror): unarchive "<title>"`

`--message` overrides the subject (full subject, not appended).
`--no-commit` stages changes and exits without committing.

**Idempotency.** Re-running the same command after success is a
no-op: the new title / parent / status already matches Confluence
state, so the version check sees no drift. (Practically, the
version_number on Confluence has advanced past the local copy
because we just wrote, so `--yes`-ing through a stale cache
*would* trigger the conflict guard. This is fine — it
short-circuits accidental double-runs.)

**Output / exit codes.**
- 0: success (or dry-run completed cleanly)
- 1: any failure — bad args, dirty tree, conflict, managed-page
  refusal, API error, refresh error
- A run summary prints to stdout for human readability; errors
  go to stderr.

## Why no `delete`

Confluence supports moving pages to trash (recoverable) and hard
delete (admin-only). Both are destructive shared-state
operations. The pattern in this codebase is to keep destructive
operations out of `mdd` ([S09](S09-confluence-command.md)
explicitly puts page deletion out of scope). `archive-page` is
the safe substitute: it removes the page from active navigation
and surfaces the "archived" status on the mirror, while
preserving content and history. Users who genuinely want to
delete a page do it in the Confluence UI and let `mdd confluence
sync-space` reconcile the trashed state on the next run.

## Examples

```
# Rename a page
$ mdd confluence rename-page docs/Architecture.md "Architecture (2026)"
Rename: "Architecture" -> "Architecture (2026)"
        space ENG, page 12345
Proceed? [y/N] y
Renamed on Confluence (version 8 -> 9).
Renamed locally: docs/Architecture.md -> "docs/Architecture (2026).md"
[main abc1234] chore(mirror): rename "Architecture" -> "Architecture (2026)"

# Move a page under a different parent (parent is another local file)
$ mdd confluence move-page docs/RFC-7.md --parent docs/archive/index.md
Move: "RFC-7"
      from parent "Active RFCs" (page 12000)
      to   parent "Archive" (page 13500)
Proceed? [y/N] y
Moved on Confluence (version 4 -> 5).
Moved locally: docs/RFC-7.md -> docs/archive/RFC-7.md
[main def5678] chore(mirror): move "RFC-7" to "Archive"

# Archive a page (no path change)
$ mdd confluence archive-page docs/old-experiment.md --yes
Archived "Old Experiment" (page 12345).
Updated frontmatter: status CURRENT -> ARCHIVED.
[main 9abc012] chore(mirror): archive "Old Experiment"

# Dry-run a move
$ mdd confluence move-page docs/RFC-7.md --parent 13500 --dry-run
Would move: "RFC-7" (page 12345)
            from parent "Active RFCs" (page 12000)
            to   parent "Archive" (page 13500)
Would rename locally: docs/RFC-7.md -> docs/archive/RFC-7.md
(dry-run, no changes made)
```

## Related upstream specs

- [009-confluence-command](S09-confluence-command.md) — page primitives, frontmatter, storage↔markdown, URL handling
- [014-confluence-sync](S14-confluence-sync.md) — per-page refresh logic, dirty-tree posture, single-commit summary, `git mv` + collision handling
- [026-managed-elsewhere](S26-managed-elsewhere.md) — managed-elsewhere fail-closed gate

## Out of scope

- `delete page` — destructive shared-state operation. Use the
  Confluence UI; sync reconciles the trashed state.
- Cross-space moves. Error out; user moves via UI and runs sync
  on both mirrors.
- Bulk `rename / move / archive` for multiple pages in one
  command. One page per invocation; pipe / xargs / shell
  scripting if needed. (We accept that a `mdd confluence
  archive subtree <root>` would be a useful future addition.)
- Inferring rename / move from a working-tree state ("the user
  did `git mv` and now wants me to push it"). The command is
  imperative; that workflow can be a separate `mdd confluence
  push-rename` command if real demand emerges.
- Editing labels via these commands. `mdd confluence labels`
  is its own future surface area.
- `mdd confluence archive subtree <root>` — bulk archive for
  an entire page subtree. Useful but adds enough complexity
  (recursion, partial-failure semantics) to deserve its own
  spec.
- `--page <id|url>` ad-hoc form for these commands (operating
  outside a clone). Add when the imperative file-path form
  proves insufficient.
- `mdd confluence trash page` — softer than UI-trashing because
  it cleans up the mirror in one step. Defer until someone
  asks; archive covers the common case.
