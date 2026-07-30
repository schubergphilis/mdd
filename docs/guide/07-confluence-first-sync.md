# Your first Confluence sync

This page assumes you bring your own Confluence Cloud tenant. There is no
shared demo space, and there cannot be one: the interesting half of `mdd`
writes, and nobody can hand strangers write access to a Confluence space.

The order below is deliberate. Every step before the last one is read-only.
Do not skip ahead.

> [!CAUTION]
> `mdd confluence sync-space` pushes local changes to Confluence without
> asking for confirmation. Read [Safety](04-safety.md) before you run it
> without `--read-only`.

## 1. Get a space you are allowed to break

Create a new Confluence space, or take one nobody depends on. You want a
space where you can push a bad body, rename a page by accident, and archive
something, without explaining yourself afterwards.

Put a handful of pages in it, with at least one nested page and one image,
so the mirror has some structure to look at. If your organization does not
let you create spaces, a personal space works.

Do not start on a space that other automation publishes into. `mdd` will
refuse to push to those pages, which is correct behavior but a confusing
first experience.

## 2. Configure a token

Create an Atlassian API token for your account, store it in 1Password, and
reference it from a config file. [Configuration and
secrets](05-configuration.md) has the full shape; the short version is:

```yaml
# configs/confluence.yaml
confluence:
  url: https://your-instance.atlassian.net
  username: you@example.com
  api_token: op://Employee/confluence-pat/token
```

Confirm it before you do anything else:

```bash
mdd confluence whoami
```

That prints the account `mdd` authenticated as, and compares it against
any configured external publishers. If it prints a different account,
stop and fix that: every page version you create will be attributed to it.

## 3. Export one page, read-only

Pick a single page and export it. Pass the page URL or its numeric id.

```bash
mdd confluence export-page https://your-instance.atlassian.net/wiki/spaces/SCRATCH/pages/12345/Some+Page --output ./scratch
```

This reads and writes nothing to Confluence. It produces one `.md` file
named after the page title, plus a `<page-name>-attachments/` directory if
the page has images. Add `--no-attachments` for a faster first look.

Now open the file. This is the most useful five minutes in this guide.

You will see a YAML frontmatter block, an export callout, and the body:

```markdown
---
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/164122/Platform+glossary
  page_id: '164122'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  title: Platform glossary
  status: current
  version: 2
  created_at: '2026-05-11T20:55:02.191Z'
  created_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  updated_at: '2026-05-11T20:55:03.086Z'
  labels: []
  exported_at: '2026-05-11T20:55:03.455150+00:00'
  source_format: storage
  attachments: []
---

# Platform glossary

A short glossary of terms used inside Acme's platform team.
```

That block is real: it is the head of
`tests/corpus/confluence/corpus/synth-glossary.md`, a page committed to
this repository as round-trip test data. Every mirrored file looks like it.

Three fields matter. `page_id` is identity and must not be edited.
`version` is the conflict check. `title` is metadata, but the page title
`mdd` actually pushes comes from the first `# H1` in the body, so treat the
H1 as the title.

Have a look at the corpus while you are here. `tests/corpus/confluence/`
in this repository holds fixtures for every shape `mdd` handles, one shape
per file, all of them exported from a live space. If you want to know what
a Confluence layout, a merged table cell or an unrecognized macro looks
like after export, it is in there.

## 4. Pull the whole space, still read-only

Make an empty directory, make it a git repository, and sync into it. Plan
first:

```bash
mkdir -p ~/mirrors/SCRATCH && cd ~/mirrors/SCRATCH && git init
mdd confluence sync-space SCRATCH --output ~/mirrors/SCRATCH --read-only --dry-run
```

`--dry-run` computes the whole plan and prints the summary without touching
files, git, or Confluence. Read it. Every page in the space should classify
as new.

Then run it for real, keeping `--read-only`:

```bash
mdd confluence sync-space SCRATCH --output ~/mirrors/SCRATCH --read-only
```

`--read-only` suppresses every write to Confluence: no page creation, no
body push, no Office publishing. The local mirror updates and `mdd` makes
one git commit for the run, so you can read `git show` to see exactly what
it did.

If the space is large, `--head 5` caps the run at five pages, and
`--no-attachments` skips the downloads.

Look at the layout it produced. Pages are `.md` files; a page with children
also gets a directory of the same name holding them; Confluence folders
become directories with no `.md`. [Concepts](03-concepts.md) has a diagram.

Run the same command again. It should report nothing to sync and make no
commit. Confirm that a second run is a no-op before you trust it with
writes.

## 5. Look at a push before you make one

Now edit one page in the mirror. Change a sentence, not the H1, in a page
you do not care about. Then:

```bash
mdd confluence update-page "Some Page.md" --dry-run
```

That fetches the live page, renders your Markdown to Confluence storage
format, and prints a unified diff of the two. It pushes nothing.

Read the diff carefully the first time. You are looking for two things:
that your change appears, and that nothing *else* does. Spurious diff hunks
in parts of the page you did not touch mean the round-trip is not clean for
that page, and pushing would rewrite content you did not intend to.

When the diff is what you expect, drop `--dry-run`:

```bash
mdd confluence update-page "Some Page.md"
```

It prints the diff again and asks before pushing. Answer `y`. Add
`--message "..."` to set the comment that shows up in the page's version
history; it costs nothing and makes the history readable later.

## 6. Then the rest of the write path

Once a single-page push works, the other write operations follow the same
shape: `--dry-run` first, then a confirmation prompt.

```bash
mdd confluence create-page ./new-page.md --space SCRATCH
mdd confluence rename-page "Some Page.md" "A better title" --dry-run
mdd confluence move-page "Some Page.md" --parent 12345 --dry-run
mdd confluence archive-page "Old Page.md" --dry-run
```

`create-page` is the exception with no prompt. Give it a Markdown file
whose frontmatter has no `page_id`, and it creates the page and writes the
full metadata back into your file.

Full bidirectional sync is last:

```bash
mdd confluence sync-space SCRATCH --output ~/mirrors/SCRATCH --dry-run
mdd confluence sync-space SCRATCH --output ~/mirrors/SCRATCH
```

Without `--read-only`, that run creates pages from local files carrying a
`space_key` and no `page_id`, pushes local edits back, and does it all
without prompting. Read the dry-run plan every time until you trust it.

## Failure modes you will actually hit

**The token will not resolve.** `mdd` tells you whether `op` is missing or
signed out. If you are signed in to more than one 1Password account, pin
the account in config or set `MDD_OP_ACCOUNT`.

**The page URL host does not match config.** This is a hard error by
design, so a copied URL cannot send a command at the wrong tenant. Check
`confluence.url`.

**"Mirror has uncommitted changes."** Sync refuses to run on a dirty tree
and there is no override. Commit or stash. If you get this and believe the
tree is clean, you are in a different directory than you think.

**Sync cannot work out where to write.** Without `--output`, `mdd` only
defaults to the current directory when its `origin` URL names the space.
Otherwise it stops and asks for `--output`.

**A page is reported as a conflict and skipped.** Both sides changed. `mdd`
does not merge: it skips the push and the pull for that page. Export the
page fresh somewhere else, reconcile by hand, then push.

**A page is skipped as managed elsewhere.** Another system publishes it.
There is no override flag; the fix is to edit that page at its source. The
run still exits 0, because this is expected steady state, not a failure.

**The push is refused as empty or too small.** Two guards abort a push
whose body is empty or under 10% of the live page's length. They are
there to override with `--allow-empty` and `--allow-shrink`. If you reach for
either one on a real page, stop and work out what happened to your content
first.

**Two images with the same filename.** Confluence keys attachments by
filename within a page, so two local files sharing a basename is a hard
error. Rename one.

**The page title changed and you did not mean it.** The first `# H1` in the
file is the title `mdd` pushes. Restore the heading and push again;
Confluence keeps the old title in page history.

[S09](../spec/S09-confluence-command.md) and
[S14](../spec/S14-confluence-sync.md) are the design record for these
commands, and [S27](../spec/S27-confluence-page-rename-move-archive.md)
covers rename, move and archive.
