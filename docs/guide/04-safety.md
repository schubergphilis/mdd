# Safety

> [!CAUTION]
> `mdd` is beta software that writes to production document systems. It is
> written almost entirely by AI agents under human review, it has had no
> independent security review, and it has no stable release. If you read
> one thing here, read this: point it at a scratch space first, run
> `--dry-run` before every unfamiliar operation, and keep the mirror in
> git so you have something to go back to.

This page is organized by operation, because that is how damage happens.
Each section says what changes, what it overwrites, and what you can get
back.

## Which commands write, and where

| Command group | Writes to |
|---|---|
| `mdd convert`, `mdd new`, `mdd pdf` | local files only |
| `mdd search`, `mdd confluence whoami`, `mdd sharepoint list-sites` | nothing |
| `mdd confluence export-page` | local files only |
| `mdd skills install`, `mdd skills uninstall` | your skills directory |
| `mdd ai rewrite`, `mdd ai index` | local files, and only with `--apply` |
| `mdd ai review` | a local report file |
| `mdd confluence create-page`, `update-page`, `rename-page`, `move-page`, `archive-page`, `unarchive-page` | Confluence |
| `mdd confluence sync-space` | local files, Confluence, git |
| `mdd sharepoint sync-site`, `mdd sharepoint sync-folder` | local files, your OneDrive folder, git |

Two entries deserve a second look.

`mdd sharepoint` writes into the locally OneDrive-synced folder, not to a
SharePoint API. That is not a smaller blast radius. OneDrive uploads what
`mdd` writes, so an overwritten `.docx` in that folder becomes a new
version in SharePoint moments later, for everyone.

The `mdd ai` commands send file content to whichever AI gateway you
configured. That is a third party receiving your documents. Whether that is
acceptable is a decision about your data, not about `mdd`.

## What a Confluence push does

A push replaces the live page body with a render of your local Markdown.
There is no merge and no three-way anything. The previous body becomes a
version in Confluence page history.

Three specific behaviors surprise people:

**The first `# H1` in the file sets the page title.** `mdd` reads the title
from the body, not from frontmatter, and sends it with every update. Edit
the H1 and the next push renames the Confluence page. If the file has no
H1, the filename stem is used.

**`mdd` appends one footer line** to the rendered page, pointing at the
mirror. It replaces its own previous footer rather than stacking, and it is
skipped when no browse URL is available. It is the only element `mdd`
injects into a Confluence page.

**Attachments are upload-only.** Local images referenced from the body are
uploaded, or re-uploaded as a new attachment version when their content
hash changed. Attachments already on the page that your file does not
reference are left alone. `mdd`'s Confluence client issues no HTTP DELETE
at all, so it cannot delete a page or an attachment. Archiving is a status
change, and `mdd confluence unarchive-page` reverses it.

Two guards fire before any push and abort it:

- An **empty body** after the export header is stripped. Overriding this
  needs `--allow-empty`.
- A body **under 10% of the length** of the live page. Overriding this
  needs `--allow-shrink`.

Both exist to catch accidental content loss, and both are crude length
checks rather than anything semantic. They will not catch a push that
deletes half a page.

## What a push does to a page that changed remotely

`mdd` compares the `confluence.version` in your local frontmatter against
the live version number.

If the remote has moved ahead, a single-page `mdd confluence update-page`
aborts with a version-drift error and pushes nothing. Inside
`mdd confluence sync-space`, the same page is recorded as a conflict and
skipped in **both** directions: not pushed, and not pulled either, so your
local edit is not overwritten while you deal with it. Resolve it by
re-exporting the page, reconciling the two versions by hand, then pushing.

There is also a narrower race. If somebody saves the page between `mdd`
fetching it and `mdd` writing it, Confluence rejects the write with a 409
and `mdd` reports a conflict. Nothing is written.

## What `mdd` does not model

Anything in this list is invisible to `mdd`. It is not read, not written,
and not carried across a round-trip:

- **Comments.** Neither inline nor page comments.
- **Page restrictions.** `mdd` reads them only to decide that a page is
  read-only for you, and never sets them. That read is advisory and can
  fail open — see the cascade table below.
- **Page properties** and content properties.
- **Labels on push.** Labels are exported into frontmatter, but a push does
  not write them back.

Those objects live in Confluence and are not touched by a body update, so a
push does not destroy them. The risk is different: `mdd` shows you a
Markdown file that looks like the whole page, and it is not the whole page.

Inside the body, [Concepts](03-concepts.md) lists the constructs that do
not survive a round-trip byte-for-byte. Unrecognized macros survive as
opaque `confluence-xml` blocks rather than being dropped.

## Pages managed by other automation

If another system publishes a Confluence page — a docs pipeline, an
external sync job — `mdd` must not fight it. The "managed elsewhere"
mechanism detects those pages and blocks every push to them.

Detection runs on every push attempt, as a five-layer cascade in this
order:

| | Layer | Kind |
|---|---|---|
| 1 | the page's space is in a configured managed list | guarantee |
| 2 | an ancestor page is a configured managed subtree root | guarantee |
| 3 | the last author's account id belongs to a configured publisher | guarantee |
| 4 | the page body matches a publisher's marker pattern | guarantee |
| 5 | the Confluence restrictions say you cannot update the page | advisory |

The distinction in that last column matters, and it is the one thing to
take away from this section.

**Layers 1–4 are guarantees.** Each is a local comparison between the page
data `mdd` already has and your config. There is no network call and
nothing to time out. If a page matches one of them, it is blocked, every
time.

**Layer 5 is advisory, and it fails open.** Checking page restrictions
means asking the Confluence API. That call can fail — an outage, an
expired token, a response shape this client does not understand — and when
it does, `mdd` cannot tell "you may update this page" from "I could not
find out". It proceeds with the push. That is deliberate: a Confluence
hiccup must not silently block all publishing.

What it no longer does is hide it. A failed check logs a warning naming
the page, and `mdd confluence sync-space` reports the total at the end of
the run:

```
Restriction check unverified: 3 — pushed without confirming update
permission (Confluence restriction API call failed; see warnings above)
```

The same count goes into the sync commit message, so the mirror's git
history records it too. If you see that line, three pages were pushed
without the permission check having actually run. Whether that matters
depends on whether those pages were restricted — which is exactly what
`mdd` could not determine. Re-run the sync once Confluence is healthy to
get a real answer.

So: do not rely on layer 5 to protect a page. If a page must never be
pushed, name it in layers 1–4 — a managed space, a managed subtree, a
publisher account id, or a body marker — or, for whole spaces, use the
confidentiality blacklist below. Confluence restrictions are a useful
backstop, not a control `mdd` can promise to enforce.

A match on any layer is final. There is no `--force` for it, no
frontmatter escape hatch, and no per-page bypass. `mdd confluence
update-page` exits with the publisher's message; `mdd confluence
sync-space` skips the page and reports it in the run summary, and the run
still exits 0 because that is expected steady state. Pulling a managed
page always works, and the exported file carries a header saying who owns
it and where to edit it.

To bypass a wrong detection you edit `configs/external-publishers.yaml` to
remove the fingerprint, which leaves a diff in git. That friction is the
point. [S26](../spec/S26-managed-elsewhere.md) covers the details.

## The confidentiality blacklist, and what it does not cover

`configs/data-protection.yaml` lists Confluence space keys and SharePoint
site names that must not leave their source system. Matching is
case-insensitive, exact by default, with a trailing `*` for a prefix match
and no other wildcards.

Both halves are enforced, and enforcement happens at the *entry point* of
each command — before anything is fetched or written, not just before a
push:

| Command | Checks |
|---|---|
| `mdd confluence sync-space` | the space key you passed |
| `mdd confluence export-page` | the space the page belongs to |
| `mdd confluence rename-page`, `move-page`, `archive-page`, `unarchive-page` | the space of any page pulled to materialise the change |
| `mdd sharepoint sync-site`, `sync-folder` | the site name, derived from the folder |
| `mdd search --exclude-blacklisted` | drops blacklisted roots from results |
| `mdd sharepoint list-sites` | reports each site's blacklist status, changes nothing |

`mdd confluence create-page` and `update-page` are not in that table. They
push a local file up to Confluence, which moves content the other way, so
there is nothing for the blacklist to protect.

A match aborts the whole run. Nothing is written, no partial mirror is left
behind, and `--dry-run` is checked too — it is not a way to preview a
blacklisted space. The error names the space or site, the pattern it
matched, and the file that declares that pattern, because entries union
across several files and "edit the config" is not useful advice when four
of them could be the one.

Three things to be aware of:

**A blacklisted space cannot be exported locally either.** The gate is at
the entry point, so exporting to a plain local directory is refused just
like a push. There is no "just for me" copy. If you need one, remove the
entry — which leaves a diff in git, which is the point.

**A data-protection config is required, not optional.** This is the one
thing on this page likely to stop you before you start. With no
`data-protection.yaml` found anywhere, `mdd confluence sync-space`,
`export-page`, the page-mutating Confluence commands and
`mdd sharepoint sync-site` / `sync-folder` **refuse to run at all** — a
hard error and exit 1, not a warning you can ignore. That applies even if
you want to protect nothing: `mdd` will not assume an allow-all on your
behalf, because a missing file would then silently disable the control.

You are most likely to hit this if you installed `mdd` from a built
package rather than from a source checkout. A checkout carries
`configs/data-protection.yaml`; a package does not.

The fix, which works for every install shape:

```bash
mkdir -p ~/.config/mdd
cat > ~/.config/mdd/data-protection.yaml <<'EOF'
confluence:
  blacklisted_spaces: []
sharepoint:
  blacklisted_sites: []
EOF
```

Both sections have to be present. Empty lists mean "protect nothing" —
that is a decision you are recording, not a default you inherit. Add the
space keys and site names you want protected to the lists.

The error itself says all of this, including the file contents, so you do
not need this page in front of you when it happens:

```
blacklist config: No data-protection blacklist found, and one is required.
  Sync and export refuse to run until a blacklist declares which Confluence
  spaces and SharePoint sites must never leave their source system.
  To proceed, create ~/.config/mdd/data-protection.yaml containing:
  ...
```

**The file shipped in this repository is a template.** Its
`blacklisted_spaces` list is empty and its site list is illustrative. An
empty blacklist blocks nothing — enforcement being wired up does not
protect a space you have not listed. Entries combine across the bundled
file, `~/.config/mdd/data-protection.yaml`, a `./configs/` copy, and any
`--blacklist` argument, so you extend the list rather than replacing it.

What the blacklist is not: a filter on what gets pulled into the mirror
page by page. That is `.mddignore`, and the two do not interact. The
blacklist works at whole-space and whole-site granularity, which is the
unit an operator can actually review.

The built-in git mirror backend applies no data-protection gate of its own
— its source says so, and that is deliberate. A deployment that supplies
its own mirror backend can add a second gate in its push path, and `mdd`
ships the helper for doing so: it infers the source system from the
work-tree and checks the matching list, refusing a work-tree it cannot
identify. That is defence in depth, not the mechanism. The blacklist holds
without it, because the entry-point check has already run by the time
anything reaches a push.

## Dry runs, prompts, and where there are none

`--dry-run` is available on both sync commands and on every single-page
Confluence mutation. It computes the full plan, prints it, and touches
nothing. Use it.

Confirmation prompts are narrower than you might assume:

| Operation | Prompts? |
|---|---|
| `mdd confluence update-page` | yes, after printing a diff; `--yes` skips it |
| `mdd confluence rename-page`, `move-page`, `archive-page`, `unarchive-page` | yes; `--yes` skips it |
| `mdd confluence create-page` | **no** |
| `mdd confluence sync-space` | **no**, for any of its writes |
| `mdd sharepoint sync-site`, `sync-folder` | **no** |

`mdd confluence sync-space` calls the same push code as `update-page` with
confirmation already suppressed. It creates pages, pushes bodies and
publishes Office attachments without asking. The empty-body and shrink
guards still run, and managed pages are still skipped, but nothing stops
to check with you. This is the command most likely to surprise you, and
`--read-only` is how you take the write half off the table while keeping
the pull.

Both sync commands refuse to run when the mirror working tree has
uncommitted changes, so a sync never mixes your edits into its own commit.
There is no override. That check asks git, so it does nothing if your
output directory is not a git repository — one more reason to make it one.

`--prune-ignored` deletes local mirror files matching `.mddignore`. It logs
every deletion, it is per invocation and never sticky, and combining it
with `--read-only` is rejected outright.

## Recovery

What you can actually get back:

**A Confluence page body.** Every push creates a new page version, and
`--message` sets the version comment. Confluence keeps previous versions
and you restore one from the page's version history in the Confluence UI.
`mdd` has no restore command.

**A local mirror file.** Only from git. A pull overwrites the file in
place. Sync makes one commit per run, so `git log` on the mirror shows what
each run changed and `git revert` or `git checkout` gets a file back. If
the mirror is not in git, an overwritten file is gone.

**A page deleted in Confluence.** Sync removes it from the mirror with
`git rm`, so it stays in git history. `--no-delete` keeps the local copy.
Restoring the page itself is a Confluence operation.

**A `.docx` overwritten by a SharePoint sync.** `--backup` copies the prior
file to `.mdd-backups/<path>/<timestamp>-<name>` before overwriting, and is
off by default. Beyond that you are relying on SharePoint's own version
history, which is a tenant setting rather than something `mdd` guarantees.
Check whether it is on for your library before you need it.

When both sides of a SharePoint pair changed, `mdd` writes a candidate
render to `Foo.from-md.docx` and touches neither original. Port the changes
by hand in Word, delete the candidate, and re-run.

## What has not been reviewed

Read [SECURITY.md](../../SECURITY.md) before deploying this anywhere that
matters. In short:

- There has been **no independent security review** of this codebase.
- It is written almost entirely by AI agents. The human review is real, and
  it is not an audit.
- There is no 1.0. Breaking changes land between `0.x` minor versions.
- The data-protection support described above exists
  ([S07](../spec/S07-data-protection.md)) and has not been independently
  reviewed either. Nobody wired up its Confluence half for months, and
  nobody noticed — which is the kind of thing a review is for.
- `mdd ai` output comes from a model. It can be wrong.

Report vulnerabilities privately. Do not include real customer data, live
credentials, or content from a private space in a report.
