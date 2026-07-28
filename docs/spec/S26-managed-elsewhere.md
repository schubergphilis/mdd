# 026 - Externally-managed Confluence pages

**Purpose:** Detect Confluence pages maintained by external automation and block `mdd` pushes; pull/export remains allowed.

**Status:** Implemented (2026-05-09)

## Introduction

Pages authored by external automation systems (e.g. `docs-pipeline` Sphinx publisher, `technical-documentation` external sync) must not be overwritten by `mdd`. Pushes are strictly blocked; pull (export) still works. The mirror's exported markdown carries a clear "managed by X — edit at <url>" header so readers see immediately that local edits will not round-trip.

This spec extends `mdd confluence sync` ([S14](S14-confluence-sync.md)) and the related
push paths ([S09](S09-confluence-command.md) `update page`, [S17](S17-confluence-office-publishing.md) office publishing,
[S21](S21-ai-rewrite-and-index.md) `ai rewrite --apply`, [S21](S21-ai-rewrite-and-index.md) `ai index --apply`).
Originates from research doc 005.

## Requirements

**Detection cascade (in priority order, on every push attempt)**

For each page about to push, evaluate the following signals. A
match at any layer classifies the page as managed-elsewhere; later
layers don't run.

1. **`managed_spaces`**: page's `space_key` is in the configured
   list → match.
2. **`managed_subtrees`**: page's ancestor chain contains a
   configured `root_page_id` → match. (Walk ancestors via the v2
   API's `parentId` chain or via `GET /pages/{id}?include-ancestors=
   true`.)
3. **Publisher account ID**: page's `version.authorId` is in any
   `external_publishers[*].account_id` list → match.
4. **Body marker regex**: page body's storage XHTML matches any
   `external_publishers[*].body_marker_patterns` regex → match.
5. **Page restrictions**: `GET /content/{id}/restriction` shows
   the current user is not in the "update" allow-list → match
   (separate `READ_ONLY` reason; not classified as a publisher
   match).

If none match, the page is normally pushable.

**Strictly fail-closed: no override mechanism**

A detected managed page **cannot be pushed via `mdd`**. There is
no `--force-managed` flag, no `mdd.managed_override: true`
frontmatter escape, no per-page bypass. The intended workflow is:
edit upstream, let upstream's automation re-publish. If the user
genuinely needs to bypass this — e.g. mis-detected page — they
must edit `configs/external-publishers.yaml` to remove the matching
fingerprint, push, then restore the config.

This is a deliberate strictness choice: the only stable way to
co-exist with upstream automation is to not write to its pages at
all.

**Push-side enforcement**
- `mdd confluence update-page <file>`: if detection fires, exit 1
  with the configured publisher's `message`. Body and frontmatter
  are unchanged.
- `mdd confluence sync`: if detection fires for a page that
  otherwise would be pushed (new local file, local edit, office
  attachment publish), the page is **skipped**. The skip is
  reported in the run summary. Sync exits 0 if nothing else
  failed — managed-page skips are expected steady state, not
  errors.
- `mdd confluence sync` continues to **pull** managed pages
  normally (read-only operation; always allowed).
- S17 (`publish_office`): refuses to upload office
  attachments to managed pages. Skip recorded in summary.
- S21 (`ai rewrite --apply`, `ai index --apply`): refuses to
  mutate source files for managed pages. Producing
  `*.rewrite.md` candidates and `INDEX.md` reports without
  `--apply` continues to work (read-only operation).

**Pull-side stamping**

When sync exports / pulls a managed page, two changes happen:

1. **Frontmatter stamp**:
   ```yaml
   confluence:
     page_id: "12345"
     # ... existing fields ...
     managed_by: docs-pipeline
     managed_source_url: https://gitlab.example.com/tat/docs-pipeline
     managed_reason: PUBLISHER_ACCOUNT_MATCH      # or BODY_MARKER, MANAGED_SPACE, MANAGED_SUBTREE, READ_ONLY
   ```

2. **Replaced export header** in the markdown body. The standard
   [S09](S09-confluence-command.md) export header:
   ```
   > **Confluence export**
   >
   > This page was exported from confluence page [<title>](<url>)
   > on <YYYY-MM-DD>.
   ```
   becomes, for managed pages:
   ```
   > **Confluence export (managed by docs-pipeline)**
   >
   > This page is published from
   > <https://gitlab.example.com/tat/docs-pipeline>.
   > Edit there; this mirror is read-only.
   > Exported on 2026-05-08.
   ```

The [S09](S09-confluence-command.md) strip-on-push rule that removes the export header
before sending body XHTML to Confluence already handles both
shapes (matches `> **Confluence export`).

**Run summary additions**

`mdd confluence sync` summary gets a new section, grouped by
publisher:

```
chore(mirror): sync from Confluence space MCQF

Confluence -> mirror:
  4 content updates, 1 renamed

Skipped (managed elsewhere):
  - 23 pages from docs-pipeline
  - 4 pages from technical-documentation
  - 2 pages read-only restricted

Mirror -> Confluence:
  (no actions; all candidates were managed-elsewhere)
```

When the section is empty (no managed skips), it's omitted.

**`mdd confluence whoami` helper**
- `GET /wiki/api/v2/users/current` returns the authenticated
  user's `accountId` and `displayName`.
- Print:
  ```
  You are authenticated as:
    accountId:   5e3f...your-id
    displayName: Leo Simons

  Configured external publishers:
    docs-pipeline        accountId 5e3f...sbpcb-bot       (no match)
    technical-documentation    accountId 5e3f...techdocs-bot    (no match)
  ```
- Useful for populating `external-publishers.yaml`: the user runs
  whoami when impersonating each known external system and copies
  the printed `accountId`.

## Design Approach

**Fail-closed with no override.** The cascade priority order
(`managed_spaces` → `managed_subtrees` → publisher account ID →
body marker regex → page restrictions) means the cheapest checks
run first and the most-likely-wrong checks (regex on body) run
last. Restrictions get their own `READ_ONLY` reason because they
mean something different — the current user lacks permission,
not that another system owns the page.

The classification is pure once the page and config are loaded;
the same `classify_page` function is called from every push site
(`update page`, sync apply, office publishing, `ai rewrite/index
--apply`). Each push site either errors out (single-page
operations) or skips and records a summary entry (bulk sync).

**Pull-side stamping** runs on every exported page so readers see
the "managed by X" header in the mirror itself, not only when
they attempt to push. This makes the failure mode discoverable
before they try to edit.

**Reasons enum.** `MANAGED_SPACE`, `MANAGED_SUBTREE`,
`PUBLISHER_ACCOUNT_MATCH`, `BODY_MARKER`, `READ_ONLY` — both for
internal classification and for the `managed_reason` frontmatter
stamp.

## Subcommands

```
mdd confluence whoami [--config <file>]
```

No new sync subcommands; behaviour is layered onto existing ones.

`mdd confluence whoami` prints the current user's `accountId` and
`displayName`, plus a side-by-side comparison against any
configured `external_publishers` so the user can populate the
config easily.

## Config schema

**Shared library** at `configs/external-publishers.yaml`,
committed to the `mdd` repo:

```yaml
external_publishers:
  - name: docs-pipeline
    account_ids:
      - "5e3f...placeholder-bot-account-id"
    body_marker_patterns:
      - 'View source on GitLab.*docs-pipeline'
    source_url: https://gitlab.example.com/tat/docs-pipeline
    message: |
      This page is published by the docs-pipeline Sphinx
      automation. Edit the source RST in {source_url}; the next
      CI run will republish.

  - name: technical-documentation
    account_ids:
      - "5e3f...placeholder-techdocs-bot-account-id"
    body_marker_patterns: []
    source_url: https://gitlab.example.com/SaaS/technical-documentation
    message: |
      This page is part of the SaaS Technical Documentation
      bundle, synced from GitLab. Edit the markdown in
      {source_url}; the sync tool will republish.

managed_spaces:
  - space_key: MCQF
    publisher_name: docs-pipeline

managed_subtrees:
  - space_key: saas
    root_page_id: "844137445"
    publisher_name: technical-documentation
```

**Per-user overrides** at `~/.config/mdd/external-publishers.yaml`
or `./configs/external-publishers.local.yaml`. Users may add
additional publishers / spaces / subtrees, or extend `account_ids`
on existing entries. Same merge semantics as the [S10](S10-sharepoint-command.md)
SharePoint mapping override.

`message` supports `{source_url}` and `{publisher_name}`
substitution for cleaner authoring.

## Related upstream specs

- [009-confluence-command](S09-confluence-command.md) — update page, export page, strip-on-push header rule
- [014-confluence-sync](S14-confluence-sync.md) — sync push/pull paths this spec layers onto
- [017-confluence-office-publishing](S17-confluence-office-publishing.md) — office attachment publishing blocked for managed pages
- [021-ai-rewrite-and-index](S21-ai-rewrite-and-index.md) — ai rewrite/index --apply blocked for managed pages
- [010-sharepoint-command](S10-sharepoint-command.md) — override merge semantics referenced for config

## Out of scope

- Override mechanism for pushing to managed pages. Strictly fail
  closed; the user edits config to remove a fingerprint if a
  legitimate override is needed.
- Auto-discovery (`mdd confluence detect-publishers SPACE`).
  Deferred.
- Confluence label-based detection. Body marker regex covers a
  superset of label use-cases (labels show in storage XHTML
  surrounding metadata in some renderings). Add explicit
  label-detection later if a publisher needs it.
- Cross-space publisher detection for SharePoint or Lucid mirrors.
  Those systems don't have the same multi-publisher dynamic in
  practice; revisit if it becomes a problem.
- Migration of existing mirrors. There are no production mirrors
  yet; first-sync detection handles all cases automatically.
