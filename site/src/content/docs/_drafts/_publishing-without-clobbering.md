# Publishing to Confluence without clobbering it

A Confluence space is not an empty target. It has pages nobody told you
about, subtrees maintained by automation that has never heard of `mdd`,
macros the tool does not model, and a rename history. Pointing a
bidirectional sync at shared state like that is a destructive operation
waiting to happen: a push replaces the whole live page body with a render
of your local Markdown, with no merge step in between
([Safety](../guide/04-safety.md)).

This article is about the mechanisms that stand between an operator and
that outcome — what each one protects, what was tried and rejected on the
way to it, and where the gaps are. It is not a how-to:
[Safety](../guide/04-safety.md) and
[Your first Confluence sync](../guide/07-confluence-first-sync.md) cover
the procedures.

## Nothing tells you what changed

The first obstacle to safe publishing is that Confluence Cloud has no
change feed. There is no "everything that changed since timestamp T"
endpoint that reports renames, moves, archives, or deletes as events;
per-page version history only covers body edits
([S14](../spec/S14-confluence-sync.md)). The research that shaped sync
tried the obvious shortcut — a CQL `lastmodified` query as an incremental
filter — and found it unreliable for exactly the events that restructure a
space: moves and archives
([R01](../research/R01-confluence-renames.md)). A sync that trusted it
would re-export a renamed page to a new file and leave the old one in
place, silently forking the mirror.

What killed that approach also dictated the replacement. The one field
Confluence keeps stable across rename, move, archive, and unarchive is the
page `id`; every other field is mutable
([R01](../research/R01-confluence-renames.md)). So sync does a full
reconciliation on every run: fetch the whole page tree, diff it against
the local mirror keyed by the `page_id` each file carries in its
frontmatter, and classify every difference
([S14](../spec/S14-confluence-sync.md)). A second rejected design hid in
that choice too: an early option kept a side-car state file mapping page
ids to paths, and it lost to frontmatter because a second source of truth
drifts the moment anyone edits a file outside `mdd`
([R01](../research/R01-confluence-renames.md)).

Two smaller forks from the same note settled the destructive edges.
Archiving could have been modeled as relocation to an `_archived/` subtree
or as deletion; both lost to an in-place frontmatter status flip, because
relocation churns paths on every archive cycle and deletion loses content
the user explicitly wanted kept
([R01](../research/R01-confluence-renames.md)). And a cross-space move
could have been handed off automatically to the other space's mirror; that
was rejected as inter-repo coordination nobody wanted, in favor of
deleting locally and warning
([R01](../research/R01-confluence-renames.md)).

## Structural changes flow one way

The diff model has a consequence that surprises people: it only detects
Confluence-side structure changes. Rename a file locally with `git mv` and
the Confluence page is not renamed; the spec's own assessment of what the
next sync does with that situation is "at best a confusing diff and at
worst a duplicate page"
([S27](../spec/S27-confluence-page-rename-move-archive.md)). Setting
`confluence.status: ARCHIVED` in frontmatter does not archive the page
either — the next sync sees the mismatch and reverts your edit, which is
what the shipped diff code does with any local status flip.

The considered fix — infer intent from the working tree, so a `git mv`
becomes a Confluence rename — was explicitly rejected
([S27](../spec/S27-confluence-page-rename-move-archive.md)). Guessing at
structural intent from file state is how a mirror ends up renaming pages
nobody meant to rename. Instead, S27 added imperative commands
(`rename-page`, `move-page`, `archive-page`, `unarchive-page`) that make
the Confluence API call first and refresh the local file from the
response. Each one runs the same guards as a body push: managed-page
classification, a dirty-tree refusal, and a version-drift check, all
before any API call. There is deliberately no `delete-page`: archiving is
the safe substitute, and the Confluence client issues no HTTP DELETE at
all ([S27](../spec/S27-confluence-page-rename-move-archive.md)).

## When both sides changed, `mdd` does nothing

The hardest question for any bidirectional tool is what to do when the
remote page changed after your last pull *and* you edited the local file.
The prior art here is instructive because it is bad: Quarto's Confluence
publisher, the closest existing system, is last-writer-wins — it fetches
the version number, increments it, and replaces the body wholesale, with
its documentation stating plainly that Confluence-side edits are
overwritten on publish
([R06](../research/R06-confluence-bidirectional-sync-ir.md)).

`mdd` refuses to be that. When sync finds a page where the remote version
advanced past the local frontmatter and the local body also changed, it
skips the page in **both** directions — no push that would erase someone
else's edit, no pull that would erase yours — and records a conflict for
the operator ([S14](../spec/S14-confluence-sync.md)). A narrower race
(someone saves between `mdd`'s fetch and its write) is caught by
Confluence itself and surfaced as a version conflict rather than retried.

Be clear about what this is: a punt, not a merge. The research note that
opened the merge problem calls the skip "fine for an MVP, useless as a
working model," because a space that humans actively edit produces
conflicts faster than an operator resolves them
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). That note
launched a measured comparison of IR foundations — four pipelines built
and scored against the same corpus, with the original Pandoc
recommendation reversed in favor of a pure-Python IR
([R12](../research/R12-confluence-ir-comparison.md)) — and the IR shipped
([S28](../spec/S28-document-ir-foundation.md)). The merge engine built on
top of it has not. What ships today is still skip-and-report, and
resolving a conflict is still manual work.

## Pages `mdd` must never touch

Some pages in a space are published by other automation — a Sphinx
pipeline, an external Markdown sync. Pushing to those is worse than a
normal clobber: the upstream system republishes on its next run, your edit
vanishes, and the two tools oscillate forever
([R05](../research/R05-managed-elsewhere.md)). The managed-elsewhere
mechanism exists to detect those pages and refuse every write to them,
while pull keeps working and the exported file is stamped with a "managed
by X — edit at the source" header
([S26](../spec/S26-managed-elsewhere.md)).

The research proposed a `--force-managed` flag and a per-page frontmatter
override for migration cases
([R05](../research/R05-managed-elsewhere.md)). The spec killed both: a
detected managed page cannot be pushed via `mdd`, full stop, and a wrong
detection is fixed by editing the shared fingerprint config — which leaves
a reviewable diff in git
([S26](../spec/S26-managed-elsewhere.md)). The reasoning is that the only
stable way to coexist with upstream automation is to never write to its
pages, and an override flag is a standing invitation to do exactly that
under deadline pressure.

The detection cascade also inverted between research and spec. R05 put the
Confluence page-restrictions check first, run on every push; S26 runs it
last, after the cheap config-driven checks (managed space, managed
subtree, publisher account id, body marker), and gives it a separate
`READ_ONLY` reason because "you lack permission" means something different
from "another system owns this"
([S26](../spec/S26-managed-elsewhere.md)). The shipped code adds a wrinkle
the spec does not mention: when the restrictions API call fails, the check
fails *open* and assumes you may write, on the grounds that the other
cascade layers are stronger and Confluence will reject an actually
forbidden write server-side. That is a reasonable trade, but it means the
last cascade layer is advisory, not a guarantee.

## The filters at the edges

Two more mechanisms bracket the sync itself. On the pull side,
`.mddignore` filters source content before it is downloaded, with
gitignore semantics deliberately delegated to the `pathspec` library
rather than reimplemented ([S39](../spec/S39-mddignore.md)). Its safety
posture is borrowed from git: adding a pattern never deletes
already-synced files, cleanup is a separate opt-in `--prune-ignored` flag
that logs every deletion and is never sticky, and combining it with
`--read-only` is rejected as contradictory rather than silently resolved
([S39](../spec/S39-mddignore.md)). The spec described the Confluence
wiring as follow-up work; it has since landed, and `sync-space` consumes
the matcher today.

On the push side sits the confidentiality blacklist: a committed config
listing spaces and sites that must never be pushed to a git remote, with
`--force` explicitly not an override
([S07](../spec/S07-data-protection.md)). Here the design record and the
shipped code part ways, and the code is what counts.
[S07](../spec/S07-data-protection.md) says every path that can publish to
a remote consults the blacklist first, and
[S14](../spec/S14-confluence-sync.md) says the mirror push applies it. In
this distribution, no Confluence code path calls the Confluence blacklist
check, and the built-in generic git backend states in its own source that
it applies no host allow-list and no data-protection gate. The SharePoint
half is enforced; the Confluence half is a helper that only `mdd search`
reads. The backend protocol reserves a place for the gate, and a
deployment that supplies its own mirror backend can enforce it there — but
if you run the open-source core against a sensitive space, the spec
describes a protection you do not have
([Safety](../guide/04-safety.md)).

## What is left unguarded

The remaining guards are honest about being crude. A push aborts on an
empty body or a body under 10% of the live page's length; both are length
checks, and neither notices a push that deletes half a page
([Safety](../guide/04-safety.md)). Office attachment publishing is a
separate write path with its own managed-page refusal and one ownership
rule: a user-uploaded attachment already holding the target filename is a
hard error, while an attachment `mdd` published itself is versioned over
on every re-render ([S17](../spec/S17-confluence-office-publishing.md)).
Comments, page restrictions, and page properties are not modeled at all: a
push does not destroy them, but the Markdown file that looks like the
whole page is not the whole page ([Safety](../guide/04-safety.md)).

And all of it — the diff model, the cascade, the guards — is beta software
written almost entirely by AI agents under human review, with no
independent security review ([SECURITY.md](../../SECURITY.md)). The
protections described here exist and are tested, but tested is not
audited. The design compensates the honest way: keep the mirror in git so
every sync is one commit you can revert, lean on Confluence's own version
history for the remote side, and prefer refusing to guessing everywhere
the two conflict.
