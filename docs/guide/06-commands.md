# Commands overview

This page is a map, not a reference. It groups the command tree by what you are
trying to do and says when to reach for each group. It does not list flags.

`mdd help` is the authority on what exists, and `mdd <command> --help` on what
each one accepts. A generated per-command reference is planned but not
published yet, so where this page and `--help` disagree, believe `--help`.

```bash
mdd help
mdd convert --help
mdd confluence sync-space --help
```

## Convert documents to Markdown

`mdd convert` reads `.docx`, `.pptx` and `.pdf` and writes a Markdown sibling
next to each one, or into a separate tree. Reach for it when you have a folder
of Office files and want text you can diff, grep and hand to an agent.

It is incremental: a file whose Markdown is already newer is skipped. The first
run downloads Docling's models, around 500 MB.

Conversion is lossy in the direction of Markdown. See the round trip in the
[Quickstart](02-quickstart.md) for what that looks like in practice.

## Author new documents

`mdd new`, `mdd new-pptx` and `mdd new-docx` scaffold a Quarto project that
renders to Word, PowerPoint, or both. Reach for these when the deliverable has
to arrive as an Office file but you would rather write Markdown.

`mdd pdf` exports the rendered Office files to PDF, and `mdd pdf-pptx` and
`mdd pdf-docx` do one format each. All three drive Microsoft Office through
AppleScript, so they need macOS with Office installed.

## Mirror a Confluence space

`mdd confluence` is the largest group and the one that can do the most damage.

`mdd confluence sync-space` is the main verb: it reconciles a whole space with
a local git mirror in both directions. `mdd confluence export-page` pulls a
single page and writes nothing back, which makes it the right first command
against an unfamiliar space.

Pushing individual pages is `mdd confluence create-page` and
`mdd confluence update-page`. Structural changes to a page — title, parent,
archived state — are `mdd confluence rename-page`, `mdd confluence move-page`,
`mdd confluence archive-page` and `mdd confluence unarchive-page`; each one
mutates Confluence and then replays the change in the mirror so the two stay in
step.

`mdd confluence whoami` prints the account your credentials resolve to. Run it
first. It answers "whose name will appear on every edit", which is the question
you want answered before rather than after.

Start at [Your first Confluence sync](07-confluence-first-sync.md).

## Mirror a SharePoint site

`mdd sharepoint` never calls the SharePoint API. It works through the OneDrive
folder that the sync client already keeps on your disk, so writes reach
SharePoint by way of OneDrive rather than over the network.

`mdd sharepoint list-sites` shows what OneDrive has synced locally and writes
nothing. `mdd sharepoint sync-site` syncs one of those sites with a Markdown
mirror. `mdd sharepoint sync-folder` does the same for any local folder, which
is the escape hatch when the content you want is not laid out as a site.

Start at [Your first SharePoint sync](08-sharepoint-first-sync.md).

## Search

`mdd search` wraps ripgrep over every mirror root in your configuration, so one
query covers all your Confluence spaces, SharePoint sites and docs repositories
at once. It needs `rg` installed. There is no network call, no API token and no
model behind it.

Use `--json` when a script or an agent is reading the output, and `--include`
to search a directory that is not in your configuration.

## Prose checks

`mdd prose` is a group of deterministic checks over a Markdown corpus. No
network call, no token, no model — the same bytes always produce the same
answer, which is what makes it usable as a merge gate.

`mdd prose check` is the entry point for CI. It runs every check your project
has enabled in one pass over each file, prints one finding per line as
`path:line:column: severity: rule: message`, and exits `1` if anything at or
above `--min-severity` (default `error`) turned up. `--json` switches to
line-delimited JSON for a script or an agent.

There are four checks behind it.

`mdd prose lint` finds mechanical slips a spell checker cannot see: runs of two
or more spaces, a space before terminal punctuation, more than one consecutive
blank line, trailing whitespace, an invisible space where a plain one was
meant, and — off by default, because it is a house style — punctuation placed
outside a closing quote. `--write` fixes the four unambiguous whitespace rules
and reports the rest.

`mdd prose anchors` checks that every internal `file.md#anchor` link resolves:
the target file exists, and a heading in it slugs to the anchor under GitHub's
rule. An unresolved anchor gets a `did you mean` hint. This is what makes it
safe to split, merge or renumber files in a large corpus.

`mdd prose freshness` checks that each file carries a `last-verified:` date in
its frontmatter and that it is recent enough. `--as-of DATE` pins the clock so
a test or a rebuilt CI job gets the same answer. It does nothing until you
configure it, because a corpus mirrored from Confluence has no such field.

`mdd prose reflow` is the one that matters most and the one you have to opt
into. It rewrites prose to **semantic line breaks**: one sentence per line,
with a still-overlong sentence broken at a top-level clause boundary. The point
is the diff — edit four words in a paragraph and you get a one-line diff
instead of a whole reflowed paragraph. Default mode is check-only; `--write`
applies it.

Turning `reflow` on in an existing repository produces one enormous diff:
effectively every prose file changes. Do it as one commit that does nothing
else, and record that commit in `.git-blame-ignore-revs` so `git blame` skips
it. `mdd` does not write that file for you.

Both writers refuse to touch a file whose frontmatter marks it as a Confluence
or SharePoint mirror. Rewriting one invalidates the sync's change detection —
silently, and in a way that does not look like a prose problem when it
surfaces. `--allow-mirror` overrides the refusal if you know what you are
doing. The usual advice is to `.mddignore` your mirrors and point `mdd prose`
at authored content.

Any finding can be silenced in place:

```markdown
<!-- mdd-prose-ignore: punctuation-outside-quote -->
```

That covers the next line only. A comma-separated list names several rules, the
bare form covers every rule, and `<!-- mdd-prose-ignore-file: reflow -->`
covers the whole file from anywhere in it.

## AI assistance

`mdd ai` needs an API token for a LiteLLM gateway. Nothing else in `mdd` calls
a model.

`mdd ai rewrite` rewrites a Markdown file for clarity and tone. `mdd ai index`
walks a directory and proposes an `INDEX.md` of per-page summaries, printing it
rather than writing it until you pass `--apply`. `mdd ai review` looks across a
whole mirror for duplicate pages, contradictory claims and stale content, and
writes a report for a human to act on.

Two things to keep in mind. These commands send document content to whatever
gateway you configured, so the content leaves your machine. And a model can be
wrong: `mdd ai rewrite` writes to `<file>.rewrite.md` by default so you can
diff before you accept anything.

## Agent skills

`mdd skills` manages the Claude Code skills bundled with `mdd`. Installing them
symlinks the bundle into your skills directory so an agent knows when and how
to drive these commands. `mdd skills list` shows what is available and what is
installed; `mdd skills uninstall` removes only the symlinks `mdd` created.

This group touches your skills directory and nothing else.

## What writes to a remote system

Everything above is local except the commands in this table. Each of these can
change content other people depend on.

| Command | Writes to |
|---|---|
| `mdd confluence sync-space` | Confluence, unless you pass `--read-only` or `--dry-run` |
| `mdd confluence create-page` | Confluence |
| `mdd confluence update-page` | Confluence |
| `mdd confluence rename-page` | Confluence |
| `mdd confluence move-page` | Confluence |
| `mdd confluence archive-page` | Confluence |
| `mdd confluence unarchive-page` | Confluence |
| `mdd sharepoint sync-site` | the local OneDrive folder, which OneDrive uploads to SharePoint |
| `mdd sharepoint sync-folder` | the same, for an arbitrary folder |

Two more cases that are not document writes but still leave your machine. The
`--push` flag on the sync commands pushes the mirror's git repository to its
remote. And every `mdd ai` subcommand sends content to your configured gateway.

> [!CAUTION]
> `mdd` is beta software and these commands write to production by default.
> [Safety](04-safety.md) covers what each one can destroy, and which flags hold
> it back.
