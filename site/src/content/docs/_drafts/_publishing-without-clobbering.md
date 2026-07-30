# Publishing to Confluence without clobbering it

Say your team's space is called DOCS. Most pages are yours, but a
Sphinx pipeline republishes one subtree every night, the platform team
edits a few pages by hand, and somebody renamed a page in the Confluence
UI last week. Now you point `mdd confluence sync-space` at it, so the
space and a git repository mirror each other.

Every push in that setup replaces the entire live page body with a
render of your local Markdown, with no merge step in between
([Safety](../guide/04-safety.md)). This article covers the mechanisms
that keep that from destroying anything: what each one protects, what
was rejected on the way, and where the gaps are. For
procedures, see [Safety](../guide/04-safety.md) and
[Your first Confluence sync](../guide/07-confluence-first-sync.md).

## The pages that are not yours

Push a body edit to a page in the Sphinx subtree and the update refuses
before any write:

```
This page is managed by 'sphinx-pipeline'. Edit at the source; do not
update via mdd.
```

The wording is the default refusal in `src/mdd/confluence/update.py`;
the publisher name comes from your shared config, which can also supply
a custom message. Pushing to a page owned by other automation is worse
than a normal clobber: the upstream system republishes on its next run,
your edit vanishes, and the two tools oscillate forever
([R05](../research/R05-managed-elsewhere.md)). Detection is a cascade of
checks — managed space, managed subtree, publisher account id, body
marker, page restrictions — and a hit blocks every write while pull
keeps working ([S26](../spec/S26-managed-elsewhere.md)). The exported
file gets a header naming the publisher, built in
`src/mdd/confluence/managed/headers.py`: "Edit there; this mirror is
read-only."

The research proposed a `--force-managed` flag and a per-page
frontmatter override for migration cases
([R05](../research/R05-managed-elsewhere.md)). The spec killed both: a
detected managed page cannot be pushed via `mdd`, full stop, and a wrong
detection is fixed by editing the shared fingerprint config, which
leaves a reviewable diff in git
([S26](../spec/S26-managed-elsewhere.md)). The reasoning: the only
stable way to coexist with upstream automation is to never write to its
pages, and an override flag is a standing invitation to do exactly that
under deadline pressure.

The cascade also inverted between research and spec. The research put
the page-restrictions check first; the spec runs it last, after the
cheap config-driven checks, and gives it a separate
`READ_ONLY` reason because "you lack permission" means something
different from "another system owns this"
([S26](../spec/S26-managed-elsewhere.md)). The shipped code adds a
wrinkle the spec does not mention: when the restrictions API call fails,
`classify_page` in `src/mdd/confluence/managed/classify.py` fails
*open* and assumes you may write, on the stated grounds that the other
cascade layers are stronger and Confluence will reject an actually
forbidden write server-side. A reasonable trade, but it makes the last
cascade layer advisory, not a guarantee.

## Nothing tells you what changed

The renamed page is a different problem: Confluence Cloud has no change
feed. No endpoint reports renames, moves, archives, or deletes as
events since a timestamp, and per-page version history only covers body
edits
([S14](../spec/S14-confluence-sync.md)). The research that shaped sync
tried the obvious shortcut, a CQL `lastmodified` query as an incremental
filter, and found it unreliable for exactly the events that restructure
a space: moves and archives
([R01](../research/R01-confluence-renames.md)). A sync that trusted it
would re-export a renamed page to a new file and leave the old one,
silently forking the mirror.

What killed that approach also dictated the replacement. The one field
Confluence keeps stable across rename, move, archive, and unarchive is
the page `id`; every other field is mutable
([R01](../research/R01-confluence-renames.md)). So sync does a full
reconciliation on every run: fetch the whole page tree, diff it against
the local mirror keyed by the `page_id` in each file's frontmatter, and
classify every difference
([S14](../spec/S14-confluence-sync.md)). An early option kept a side-car
state file mapping page ids to paths instead; it lost to frontmatter
because a second source of truth drifts the moment anyone edits a file
outside `mdd`.

Two smaller forks from the same note settled the destructive edges
([R01](../research/R01-confluence-renames.md)). Archiving could have
been modeled as relocation to an `_archived/` subtree or as deletion;
both lost to an in-place frontmatter status flip, because relocation
churns paths on every archive cycle and deletion loses content the user
wanted kept. And a cross-space move could have been handed
off to the other space's mirror; that was rejected as inter-repo
coordination nobody wanted, in favor of deleting locally and warning.

## Structural changes flow one way

The diff model only detects Confluence-side structure changes, which
surprises people. Rename a file locally with `git mv`
and the Confluence page is not renamed; the spec's own assessment is
that the next sync "at best produces a confusing diff and at worst a
duplicate page"
([S27](../spec/S27-confluence-page-rename-move-archive.md)). Setting
`confluence.status: ARCHIVED` in frontmatter does not archive the page
either — the next sync sees the mismatch and reverts your edit.

The considered fix, inferring intent from the working tree so a
`git mv` becomes a Confluence rename, was explicitly rejected: guessing
at structural intent from file state is how a mirror ends up renaming
pages nobody meant to rename. Instead, imperative commands
(`rename-page`, `move-page`, `archive-page`, `unarchive-page`) make the
Confluence API call first and refresh the local file from the response,
after the same guards as a body push: managed-page classification, a
dirty-tree refusal, and a version-drift check. There is deliberately no
`delete-page`: archiving is the safe substitute, and the Confluence
client issues no HTTP DELETE at all
([S27](../spec/S27-confluence-page-rename-move-archive.md)).

## When both sides changed

The version-drift check is the guard you will meet most often. Your
frontmatter says the page was at version 5 when you last pulled; a
colleague has since saved twice; your push stops with:

```
Conflict: remote version 7 is newer than local version 5.
Re-export the page to get the latest version, reconcile manually,
then re-run update.
```

That wording lives in `src/mdd/confluence/version.py` and is shared by
the body push and the structural commands. When sync finds a page where
the remote advanced *and* the local body also changed, it skips the page
in both directions — no push that would erase someone else's edit, no
pull that would erase yours — and records a conflict for the operator
([S14](../spec/S14-confluence-sync.md)).

The prior art is instructive because it is bad: Quarto's Confluence
publisher, the closest existing system, is last-writer-wins — it fetches
the version number, increments it, and replaces the body wholesale, and
its documentation states plainly that Confluence-side edits are
overwritten on publish
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). `mdd`
refuses to be that. But the skip is a punt, not a merge. The research
note that opened the merge problem calls it "fine
for an MVP, useless as a working model," because a space that humans
actively edit produces conflicts faster than an operator resolves them
([R06](../research/R06-confluence-bidirectional-sync-ir.md)). That note
launched a measured comparison of document-model foundations: four
pipelines built and scored against the same corpus, with the original
Pandoc recommendation reversed in favor of a pure-Python one
([R12](../research/R12-confluence-ir-comparison.md)). That foundation
shipped ([S28](../spec/S28-document-ir-foundation.md)); the merge engine
built on top of it has not. What ships today is still skip-and-report,
and resolving a conflict is still manual work.

## The crude guards

Two last-resort checks watch the body itself. Push a file whose content
somehow collapsed — a bad merge, a truncated write — and you get:

```
local body (403 chars) is less than 10 % of the remote body
(61240 chars). This looks like accidental content loss. Re-export
and reconcile, or pass --allow-shrink to override.
```

Its companion refuses an empty body outright ("Refusing to wipe the
remote page") unless you pass `--allow-empty`; both messages are in
`src/mdd/confluence/update.py`. The guards are honest about being crude:
both are length checks, and neither notices a push that deletes half a
page ([Safety](../guide/04-safety.md)).

Around the body sit narrower rules. Office attachment publishing is a
separate write path with its own managed-page refusal and one ownership
rule: a user-uploaded attachment already holding the target filename is
a hard error, while an attachment `mdd` published itself is versioned
over on every re-render
([S17](../spec/S17-confluence-office-publishing.md)). Comments, page
restrictions, and page properties are not modeled at all: a push does
not destroy them, but the Markdown file that looks like the whole page
is not the whole page ([Safety](../guide/04-safety.md)). On the pull
side, `.mddignore` filters content before download with gitignore
semantics; adding a pattern never deletes already-synced files, cleanup
is a separate opt-in `--prune-ignored` flag, and combining it with
`--read-only` is rejected as contradictory
([S39](../spec/S39-mddignore.md)).

## The gate the spec describes and the code does not have

One mechanism sits on the far side of the pipeline: a committed
confidentiality blacklist listing spaces and sites whose content must
never be pushed to a git remote, with `--force` explicitly not an
override ([S07](../spec/S07-data-protection.md)). Here the design record
and the shipped code part ways, and the code is what counts. The spec
says every path that can publish to a remote consults the blacklist
first; the sync spec says the mirror push applies it
([S14](../spec/S14-confluence-sync.md)).

> [!WARNING]
> In this distribution, no Confluence code path calls the blacklist
> check, and the built-in generic git backend states in its
> own source, `src/mdd/mirror/git.py`, that it applies "no host
> allow-list and no data-protection gate". The SharePoint half is
> enforced; the Confluence half is a helper that only `mdd search`
> reads.

The backend protocol reserves a place for the gate, and a deployment
that supplies its own mirror backend can enforce it there — but if you
run the open-source core against a sensitive space, the spec describes a
protection you do not have ([Safety](../guide/04-safety.md)).

And all of it — the diff model, the cascade, the guards — is beta
software written almost entirely by AI agents under human review, with
no independent security review ([SECURITY.md](../../SECURITY.md)). The
protections described here exist and are tested, but tested is not
audited. The design compensates the honest way: keep the mirror in git
so every sync is one commit you can revert, lean on Confluence's own
version history for the remote side, and prefer refusing to guessing
everywhere the two conflict.
