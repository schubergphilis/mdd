# 009 - confluence command

**Purpose:** `mdd confluence` adds Confluence Cloud integration for exporting, creating, and updating pages.

**Status:** Implemented (2026-05-08)

## Introduction

`mdd confluence` exports spaces and pages to Markdown with round-trippable
frontmatter, creates new Confluence pages from local Markdown, and pushes
local edits — including image attachments — back to Confluence. The
markdown form is the authoritative mirror; Confluence remains the
source-of-truth for the published page.

## Requirements

**Export.** One `.md` per Confluence page.  `export page` writes a single
page; whole-space exports are covered by [S14](S14-confluence-sync.md)
`sync space ... --read-only` (the dedicated one-shot `export space`
command has been removed).  Each file is self-describing for round-trip:
YAML frontmatter (schema below) plus a visible "Confluence export"
callout at the top of the body with a clickable link back to source.
Page attachments and embedded images download to
`<page-name>-attachments/` beside the `.md`, with the manifest recorded
in frontmatter.  `--no-attachments` skips all attachment downloads (text
only) — useful for fast previews and for unblocking exports when a
specific attachment fails repeatedly.

**Create.** Renders a local Markdown file to Confluence storage XHTML and
POSTs it. Required: `--space` (or `confluence.space_key` in frontmatter)
plus a title (`--title`, frontmatter, or H1 fallback). Optional
`--parent` places the new page; otherwise it lands at space root. Any
locally referenced images upload as attachments before the page POST so
storage XHTML references resolve. On success, the local file's
frontmatter is rewritten with the full Confluence metadata so subsequent
edits flow through `update page`. Idempotent guard: a `page_id` already
in frontmatter is refused with a pointer at `update page`.

**Update.** Refuses to push if frontmatter `version` is older than the
current Confluence version (conflict — abort) or if frontmatter / page_id
is missing. Default behaviour prints a summary diff and requires `--yes`
to push. `--message` sets the version comment in Confluence page
history. Image sync runs as part of update. On success, frontmatter is
rewritten with the new version and updated attachment manifest.

**Header strip and footer insert** apply to both `create` and `update`:

1. **Strip the "Confluence export" callout** (the blockquote at the top
   of the markdown body) before rendering. It exists for readers of the
   git mirror, not for the Confluence page itself.
2. **Append an MDD footer** to the rendered storage XHTML pointing at
   the mirror's browse URL for that file — one short `<sub><em>` line.
   The footer is idempotent (replaces any previous footer rather than
   appending), and omitted with a warning when no URL is available. It
   is the only `mdd`-injected element on the Confluence page.

   The URL comes from the active mirror backend's `web_url()`, not from
   any host `mdd` holds itself: which host is "ours" and what a browse
   URL looks like there is deployment knowledge. A backend with no
   remote, or no browse convention for its forge (the built-in generic
   git one), returns `None` and the footer is skipped. The shared git
   plumbing — read `origin`, reject a work-tree on another host, encode
   the branch and relative path — is `mdd.mirror.web.git_blob_url`.

**Image attachment sync** runs in both `create` and `update`. The
renderer scans storage XHTML for image references and dispatches on
three cases: external URLs pass through; existing Confluence-hosted
URLs are left alone; local files are uploaded as page attachments (or
versioned if their SHA-256 differs from the manifest, or skipped if
unchanged). Uploads happen **before** the body POST/PUT so references
resolve at render time. Filename collisions (two local files with the
same basename) are a hard error — Confluence keys attachments by
filename within a page. The v2 attachment endpoints are still maturing;
the client falls back to v1 for multipart upload as needed.

**Confidentiality.** `--push` (and therefore any pipeline that ends in a
mirror push) consults the Confluence blacklist defined in
[S07](S07-data-protection.md). Local-only export is unrestricted.

**Mirror convention.** Confluence-mastered content is mirrored to one git
repository per space. The remote URL comes from the active mirror backend,
which maps a space key to a project — for the built-in generic-git backend
that is whatever `origin` the work-tree already has; a deployment-specific
backend derives it (e.g. `https://<host>/<group>/<space-key>.git`).
`sync space SPACE` defaults `--output` to `./` when run inside a clone of
that repository (detected by comparing `origin` with the URL the backend
resolves); otherwise it suggests `git clone <remote> && cd <space-key>`
first.

## Design Approach

**API surface — Confluence Cloud v2.** REST v2 (`/wiki/api/v2/`) is the
supported path for Cloud and exposes ADF and storage body formats
cleanly. Read/write uses `body.representation=storage` (XHTML) —
storage round-trips better than ADF for Markdown conversion because the
macro vocabulary is documented and stable. Folders cannot be fetched as
pages but appear as parents; the tree builder resolves them via
`GET /folders/{id}` and includes them as directory-only nodes.
Attachment listing uses v2
(`/wiki/api/v2/pages/{id}/attachments`); v1 carried a
`Warning: 299 - Deprecated API` header.  Attachment **upload** still
uses the v1 multipart endpoint because v2 has no equivalent.

**HTTP client.** Direct `httpx` calls with a thin retry wrapper —
avoiding the heavier `atlassian-python-api` dependency for control over
v2 endpoints. Auth is HTTP Basic with `(username, resolved_token)`,
where the token is resolved on demand via
`mdd.utils.secrets.resolve_secret()` ([S07](S07-data-protection.md))
and lives only in process memory.  Retry policy: exponential backoff
(1s, 2s, 4s, 8s; max 5 attempts) on 429, 503, 5xx, `ConnectError`, and
all `httpx.TimeoutException` subclasses (Read/Connect/Write/Pool);
no retry on other 4xx; `X-Atlassian-Token: no-check` set to bypass CSRF.
Per-phase timeouts are explicit
(`Timeout(connect=30, read=30, write=30, pool=30)`) — a bare
`timeout=30.0` did not fire on TLS-level read stalls observed in
production.

**Query-param conventions (v2 API).** v2 query parameters are
**kebab-case**: `space-id`, `body-format`, `include-labels`,
`include-version`.  The camel-case form (`spaceId`) is silently ignored
by Atlassian rather than rejected, which produces the wrong result
(typically an unfiltered tenant-wide listing).  Body JSON in `POST` /
`PUT` payloads still uses camel-case (`spaceId`, `parentId`).

**Pagination loops.** Every paginated fetch is bounded by a
`MAX_PAGINATION_ITERATIONS` constant (9 today, deliberately tight)
and raises `ConfluenceError` on overshoot rather than looping
indefinitely.  Follow-up pages pass `params=None` (not `params={}`) to
`httpx.Client.request` — an empty dict would *replace* the URL's query
string, stripping the cursor embedded in `_links.next`.

**Attachment downloads.** The v2 attachment listing returns a
`downloadLink` pointing at the legacy UI binary endpoint
`/wiki/download/attachments/<id>/<name>?...`.  That path is gated to
OAuth-only on some Atlassian tenants (Atlassian's 19-Nov-2025
changelog explicitly removed several `/download/attachments/`
internal API paths), returning
`401 WWW-Authenticate: OAuth realm=...` to Basic-auth callers.  The
client therefore ignores `downloadLink` entirely and constructs the
URL from `pageId` and `id` on the v2 attachment dict:

```
/wiki/rest/api/content/{page_id}/child/attachment/{att_id}/download
```

This REST endpoint accepts Basic auth + API token even on OAuth-gated
tenants.  It 302-redirects to a CDN URL carrying a short-lived signed
JWT in the query string; httpx follows the redirect with the
Authorization header stripped automatically on the cross-origin hop.
Both `pageId` and `id` are top-level fields on every v2 listing
result and are validated as alphanumeric before path interpolation
(SSRF / traversal guard).

**Request tracing.** The `ConfluenceClient` installs request/response
event hooks on the underlying `httpx.Client` that log every call at the
custom TRACE level (5) from `mdd.utils.logging`.  CLI flags `-v`,
`-vv`, `-vvv` / `--trace`, and `--trace-bodies` raise the verbosity;
`--trace-bodies` additionally dumps request/response headers (with
`Authorization` / `Cookie` masked as `<scheme> <sha256:xxxxxxxx>`) and
body payloads truncated to 4 KiB.  Useful for diagnosing tenant-policy
oddities and redirect chains.

**Filename sanitization.** Page title → filename: replace
`<>:"/\\|?*\n\t\r` with `-`, strip leading/trailing whitespace and
dots, collapse runs of whitespace or `-`, truncate to 200 chars,
fall back to `"untitled"` if empty. On collision (same sanitized title
at the same level), append the page ID: `Title (12345).md`. Siblings
are sorted by `position` then title for deterministic ordering across
runs. Folders become directories only; only `type: "page"` nodes get a
`.md` file.

**Markdown ↔ storage XHTML.** Storage format is XHTML with `<ac:*>` and
`<ri:*>` namespaced elements. Conversion goes through the document IR
([S28](S28-document-ir-foundation.md)): storage XHTML parses into IR
nodes ([S29](S29-confluence-ir-conversion.md)) and the IR renders to
markdown ([S30](S30-markdown-ir-conversion.md)), and back. Structured
macros without a dedicated IR node fall through to the generic
`ConfluenceMacro` carrier, which the markdown writer emits as a
`:::confluence-macro {...}` fenced div — see S30 for the exact shape.
`<ac:image>` references rewrite to `![X](<page-name>-attachments/X)` on
export, and the reverse on import.

**Diff strategy for `update page`.** Re-render local md → storage XHTML,
fetch current Confluence storage, normalize whitespace, unified diff to
terminal. Confluence's own version history is the source of truth — no
merge, conflict = abort. The attachment manifest diff is shown
alongside.

## Subcommands

```
mdd confluence export-page  <page-id-or-url> [--config <file>] [--output <path>]
                                             [--no-header] [--no-attachments]
mdd confluence create-page  <markdown-file> --space <space-key> [--parent <id-or-url>]
                                            [--title <title>] [--config <file>]
                                            [--message <msg>]
mdd confluence update-page  <markdown-file> [--config <file>] [--dry-run]
                                            [--message <msg>] [--yes]
```

(Whole-space exports use ``mdd confluence sync-space`` — see
[S14](S14-confluence-sync.md).  The dedicated ``export space`` command
has been removed; ``sync space ... --read-only`` is the snapshot
equivalent and adds rename / move / delete detection over the previous
behaviour.)

- `export page` — exports a single page by ID or URL.
- `create page` — creates a new Confluence page from a local Markdown
  file, uploads any referenced local images as attachments, and writes
  full frontmatter back so future edits use `update page`.
- `update page` — reads a local `.md`, looks up its source via
  frontmatter, diffs against Confluence, syncs changed image
  attachments, and pushes the update. `--dry-run` prints the diff
  without writing.

### Title H1 on export and update

`export page` prepends `# {confluence.title}` to the markdown body
so the file is self-contained markdown (the page title is metadata
in Confluence, not part of the storage XHTML). `update page`
strips a leading H1 whose text equals `confluence.title` before
rendering markdown back to storage — re-emitting it would produce a
duplicate `<h1>{title}</h1>` in the page body.

The strip is whitespace-tolerant (trailing whitespace, optional
closing `#`s) and only triggers on an exact text match against
`confluence.title`; an H1 with a different heading or
attribute-list suffix is left intact. Consequence: an author who
intentionally writes `# {title}` as the first heading in the body
(matching the page title verbatim) will see it disappear on the
next push. That's the round-trip cost of self-contained exported
markdown; document the behaviour but do not override it per file.

### Round-trip identity grafting

`update page` MUST graft identity attributes from the remote storage
back onto the freshly-parsed local IR before rendering — see
[S33 §"R3 — Storage → IR → Markdown → IR → Storage"](S33-ir-roundtrip-testing-and-benchmarks.md).
The remote storage is already fetched at the top of the command for
the managed-page check and the diff display; the implementation
re-uses it as the cached `IR_a` for `reattach`. Without this step,
every round-trip strips `local-id`, `macro-id`, `schema-version`,
and `ac:breakout-*` from layout / section / cell / macro / paragraph
nodes — the markdown leg intentionally does not carry them.

## URL handling

Where the CLI takes a "page-id-or-url", `mdd` accepts either a bare
numeric ID or any of these Confluence Cloud URL shapes:

- `https://<host>/wiki/spaces/<SPACE>/pages/<id>` (canonical)
- `https://<host>/wiki/spaces/<SPACE>/pages/<id>/<slug>` (with title slug)
- `https://<host>/wiki/spaces/<SPACE>/pages/<id>/<slug>?focusedCommentId=...` (query stripped)
- `https://<host>/wiki/x/<base62>` (short URL — resolved via redirect)

The `host` from the URL must match `confluence.url` in config; mismatch
is a hard error to prevent accidental cross-tenant operations. Only the
page ID is pulled from the URL; everything else is informational.

## Config schema

```yaml
confluence:
  url: https://your-instance.atlassian.net
  username: your-email@example.com
  api_token: op://Employee/confluence-pat/token   # 1Password reference

  spaces:
    ENGINEERING:
      output_dir: ./output/engineering
    PRODUCT:
      output_dir: ./output/product
```

- Default config search path: `./configs/confluence.yaml`, then
  `~/.config/mdd/confluence.yaml`.
- `api_token` **must** be an `op://` reference — see
  [S07](S07-data-protection.md). Raw tokens, env-var interpolation
  for tokens, and `.env` files are not supported.
- `username` is the Atlassian account email; not a secret.
- `spaces` is nested under `confluence:`, not top-level — this is what
  [`mdd search`](S19-search-command.md) reads to find every configured
  mirror root (`confluence.spaces.<key>.output_dir`). None of the
  `mdd confluence` subcommands above read `output_dir` from config:
  `export-page` takes `--output` directly, and `sync-space` (see
  [S14](S14-confluence-sync.md)) either takes `--output` or falls back
  to `default_output_for_space()`'s origin-URL heuristic — it detects
  when the current working tree is already a clone of the space's
  mirror repo and defaults to `.` in that case. `output_dir` in config
  is `mdd search`'s bookkeeping for "where are my mirrors", not a
  setting the sync/export path consults.

## Frontmatter schema

YAML between `---` fences at top of file. Captures the readily-available
metadata from the Confluence v2 API (population requires
`include-labels=true&include-version=true&body-format=storage` plus a
follow-up `GET /users/{id}` to resolve account IDs to display names,
cached per-run).

```yaml
confluence:
  # Identity & location
  url: https://example.atlassian.net/wiki/spaces/SPACE/pages/12345/Title
  page_id: "12345"
  space_key: SPACE
  space_id: "98306"
  parent_id: "12340"                 # null for root pages
  title: My Page
  status: CURRENT                    # CURRENT | DRAFT | ARCHIVED

  # Versioning (used for conflict check on update)
  version: 7
  version_message: "Fixed typos"     # optional

  # People (account_id authoritative; display_name is convenience)
  created_at: 2023-01-25T09:40:17Z
  created_by:
    account_id: "6237c985ee1b5a0070273f6b"
    display_name: Leo Simons
  updated_at: 2026-05-08T08:12:34Z
  updated_by:
    account_id: "5e3f...a1"
    display_name: Jane Doe

  # Discoverability
  labels: [architecture, draft]

  # Export bookkeeping (mdd-managed)
  exported_at: 2026-05-08T10:30:00Z
  source_format: storage
  attachments:                       # tracked so image sync can skip unchanged
    - filename: diagram.png
      sha256: 9f86d081...
      version: 2
```

`created_*` / `updated_*` / `version*` / `status` / `labels` /
`space_id` come from the Confluence API and are refreshed on every
`export` and after a successful `create`/`update`. Email is intentionally
omitted — v2 gates email visibility on user privacy settings and `mdd`
shouldn't depend on it.

For pages **created locally** (not yet in Confluence), the user authors
a minimal frontmatter and `create page` fills in the rest:

```yaml
confluence:
  space_key: SPACE
  parent_id: "12340"        # optional
  title: New Page Title     # optional; H1 used as fallback
```

## Related upstream specs

- [007-data-protection](S07-data-protection.md) — op:// secret references, token rules, and the Confluence blacklist
- [028-document-ir-foundation](S28-document-ir-foundation.md) — the document IR that mediates markdown ↔ storage XHTML
- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — storage XHTML ↔ IR conversion
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — IR ↔ markdown conversion, including the `ConfluenceMacro` fenced-div shape

## Out of scope

- **Comments** — neither read nor write. Keeps the model focused on page
  bodies; comment threading is its own beast and the use-cases for
  mirroring discussion belong in Confluence proper.
- Server / Data Center compatibility
- Bulk `update space` (do one page at a time first; bulk later)
- Confluence label sync
- Page deletion via `mdd` (use the Confluence UI; deletion is destructive
  shared-state)
