# Concepts

Five ideas carry most of `mdd`: the mirror, sync direction, the document
IR, frontmatter, and `.mddignore`. This page explains what they are. The
how-to pages ([Your first Confluence sync](07-confluence-first-sync.md),
[Your first SharePoint sync](08-sharepoint-first-sync.md)) show you what to
run.

## The mirror

A mirror is a directory of Markdown files that corresponds to one remote
container: one Confluence space, or one SharePoint site. Keep it in git.
Several protections in `mdd` depend on git being there, and git history is
the only way to get a local file back after a sync overwrote it.

For Confluence, the layout follows the page tree. Every page becomes one
`.md` file, named after the sanitized page title. A page that has children
also gets a directory of the same name, holding the children. Confluence
*folders* become directories with no `.md` beside them. Attachments and
embedded images land in `<page-name>-attachments/`.

```
ENGINEERING/
├── Onboarding.md                     a page
├── Onboarding/                       its children
│   ├── Laptop setup.md
│   └── Laptop setup-attachments/
│       └── dock.png
└── Runbooks/                         a Confluence folder: no .md
    └── Restart the gateway.md
```

For SharePoint the layout copies the source directory structure. Each
Office file gets a Markdown sibling in the output tree: `Foo.docx` produces
`Foo.docx.md`, with extracted images in `Foo.docx-attachments/`. A PDF
converts to `Foo.pdf.md`. Plain `.md` files are copied through.
Spreadsheets and standalone image files are skipped.

Filenames come from titles, and titles change. `mdd` does not use the path
as identity — every Confluence file is keyed by the `page_id` in its
frontmatter, which survives rename, move, archive and unarchive. That is
why a rename in Confluence turns into a `git mv` in the mirror rather than
a delete and a create, and why the mirror's history stays readable.

## Sync direction

**Pull** means remote to mirror. **Push** means mirror to remote.
`mdd confluence sync-space` does both in a single run, and so does
`mdd sharepoint sync-site`. This is bidirectional sync, with everything
that implies: a run can change your local files, your remote system, or
both, and it decides which without asking.

A pull overwrites the local file. For any page whose remote version number
advanced, `mdd` fetches the body again, re-renders it, and rewrites the
frontmatter. Local edits to that file are gone unless git has them.

A push overwrites the remote page body with a render of the local file.
There is no merge. Confluence keeps the previous body as a version in page
history, so the old content is recoverable, but the live page is replaced.

When both sides changed, `mdd` refuses rather than guessing. If a local
edit is queued for push and the remote version number has moved past the
version recorded in the local frontmatter, `mdd` skips both the push and
the pull for that page and reports it as a conflict.

SharePoint is deliberately asymmetric. Office to Markdown always runs.
Markdown to Office runs only for pairs whose frontmatter carries
`update_office: true`, because the Markdown-to-Office render goes through
Quarto and loses shapes, styles and inline metadata. The default treats the
Office file as authoritative and ignores Markdown edits, with a warning
telling you how to opt in.

Both sync commands accept `--read-only`, which suppresses every write to
the remote and leaves the pull half running, and `--dry-run`, which prints
the plan and writes nothing anywhere.

## The document IR and "near-lossless"

Confluence stores a page as storage-format XHTML, a namespaced dialect with
elements for macros, layouts and links that have no Markdown equivalent.
`mdd` does not translate that dialect to Markdown and back directly.
It parses it into a typed tree, the document IR, and every converter is a
walker over that shared shape. [S28](../spec/S28-document-ir-foundation.md)
describes the model.

"Near-lossless" is a claim about a specific round-trip: storage to IR to
Markdown to IR to storage. For content you did not edit, that round-trip is
byte-for-byte identical, and CI fails when a corpus page stops
round-tripping ([S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md)).

Two mechanisms hold it up.

The first is that unrecognized content is never dropped. A Confluence macro
`mdd` has no model for rides through as a fenced block tagged
`confluence-xml`, holding the source XHTML verbatim:

````markdown
```confluence-xml
<ac:structured-macro ac:name="bogus-macro" ac:schema-version="1">
  <ac:parameter ac:name="alpha">one</ac:parameter>
</ac:structured-macro>
```
````

You can read around such a block and edit the prose next to it. Editing
inside it means editing storage XHTML by hand.

The second is identity grafting. Confluence attaches identity attributes to
elements (`ac:local-id`, `ac:macro-id`, `ac:schema-version`) that Markdown
has nowhere to put. Before a push, `mdd` fetches the current remote storage
and grafts those attributes back onto the tree parsed from your Markdown,
so an unedited page pushes back as the same bytes rather than as a page
where every macro lost its id.

What does not survive is documented rather than hidden. Backslash escapes
(`\*`, `\_`) are dropped by the Markdown reader per CommonMark and are not
restored on the way back. An empty paragraph carrying an anchor id has no
Markdown syntax and is not invented. Inline `<kbd>` and `<samp>` raw HTML
falls outside the Markdown reader's allowlist.

Separately from the round-trip, some things are not modeled at all.
Comments are neither read nor written. Page restrictions and page
properties are not synced. Labels are read into frontmatter but not pushed
back. [Safety](04-safety.md) covers what that means when you push.

## Frontmatter

The YAML block at the top of a mirrored file is the binding between the
local file and the remote object. It is not decoration, and hand-editing it
changes behavior.

For Confluence, `confluence.page_id` is identity: it tells `mdd` which
remote page this file is. `confluence.version` is the conflict check:
`mdd` compares it against the live version number and refuses to push when
the remote has moved ahead. For SharePoint, the `sharepoint.sync` block
carries the hashes of both sides at the last sync, which is how divergence
is detected at all.

Three states follow from what the block contains:

- **Tracked.** A `confluence.page_id` is present. The file is one end of a
  sync pair.
- **Publish candidate.** No `page_id`, but a `confluence.space_key` is
  present. The next sync creates this as a new Confluence page.
- **Manually managed.** Anything else, including a file with no
  frontmatter at all. Sync never deletes, moves or rewrites it.

That third state is a deliberate safety property, and it means a plain
Markdown file you drop into a mirror is left alone. It also means a
frontmatter *typo* falls into it. Frontmatter is validated with unknown
keys rejected ([S40](../spec/S40-typed-frontmatter.md)), so writing
`spcae_key` makes the whole block unreadable, and the file silently stops
being part of the sync instead of silently syncing the wrong thing.

## `.mddignore`

`.mddignore` filters the source side before anything is downloaded or
converted. It uses gitignore pattern syntax, and it lives at the root of
the mirror directory. It exists because sync is otherwise all-or-nothing:
a SharePoint site with a 7 GB `Archive/` subtree costs you that 7 GB on
every run.

It behaves like `.gitignore` in the way that matters: adding a pattern
blocks new pulls, and does nothing to files already on disk. Cleaning those
up is a separate, explicitly requested operation. `mdd` will not delete
local content because a pattern started matching it.

`.mddignore` is not a confidentiality control. It runs on the pull side, to
avoid fetching content you do not want. The gate that stops content being
published is separate, and [Safety](04-safety.md) describes it.
[S39](../spec/S39-mddignore.md) has the pattern rules.
