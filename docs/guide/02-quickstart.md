# Quickstart

This is a tour of the local half of `mdd`: scaffold a document, render it,
convert it back to Markdown, and search the result. Nothing here touches
Confluence or SharePoint, and nothing here needs an account anywhere. Allow
about ten minutes, plus a one-time model download in step 6.

Before you start, [install `mdd`](01-install.md). Three steps need a tool you
may not have: Quarto, Microsoft Office, and ripgrep. Each of those steps says
so at the top.

> [!NOTE]
> `mdd` is quiet by default: it logs at warning level, so a successful command
> often prints nothing at all. Pass `-v` before the subcommand to see what it
> is doing. This page uses `-v` throughout.

## 1. Make a scratch directory

Work somewhere disposable. You will delete it at the end.

```bash
mkdir ~/mdd-quickstart
cd ~/mdd-quickstart
```

## 2. Scaffold a document project

`mdd new` creates a [Quarto](https://quarto.org) project that produces a
PowerPoint deck and a Word document from one Markdown source.

```bash
mdd -v new mdd-tour
```

```
INFO    mdd.utils.scaffolding: Created: mdd-tour/mdd-tour.qmd
INFO    mdd.utils.scaffolding: Output: Both PowerPoint (.pptx) and Word (.docx)
INFO    mdd.utils.scaffolding: Hint: Run 'cd mdd-tour && ./render.sh' to generate the output
```

## 3. Look at what it produced

```bash
cd mdd-tour
ls -1F
```

```
mdd-tour.qmd
render.sh*
simple-document.docx@
simple-presentation.pptx@
```

Four entries, and each one is worth a moment.

`mdd-tour.qmd` is the source: YAML frontmatter naming the two output formats,
then ordinary Markdown.

```yaml
---
title: "mdd-tour"
subtitle: "Your subtitle here"
author: "Your Name"
format:
  pptx:
    reference-doc: simple-presentation.pptx
  docx:
    reference-doc: simple-document.docx
    toc: true
---
```

`render.sh` is a convenience wrapper that calls `quarto render` and then
`mdd pdf`.

The two Office files are **symlinks**, not copies. They point into the bundled
templates inside your `mdd` installation, and they supply the fonts, colors and
slide masters that Quarto renders into. Two things follow: the project is not
self-contained, and moving it elsewhere breaks the links. If you want a
portable project, replace the symlinks with real copies.

`mdd new-pptx` and `mdd new-docx` scaffold a single-format project instead, and
`mdd new-pptx --compact` uses a smaller type scale for dense slides.

## 4. Render it

This step needs Quarto. If you do not have Quarto, skip to step 6 and use any
`.docx`, `.pptx` or `.pdf` file you already have in place of `mdd-tour.docx`.

```bash
quarto render mdd-tour.qmd
```

Quarto prints its full Pandoc configuration for each format. The lines that
matter are at the end of each block:

```
pandoc
  to: pptx
  output-file: mdd-tour.pptx
  reference-doc: simple-presentation.pptx
...
Output created: mdd-tour.pptx
```

You now have `mdd-tour.pptx` and `mdd-tour.docx` alongside the source.

## 5. Export to PDF (optional)

`mdd pdf` drives Word and PowerPoint through AppleScript, so this step works on
macOS with Microsoft Office installed and nowhere else. Skip it otherwise;
nothing later depends on it.

```bash
mdd -v pdf .
```

```
INFO    mdd.commands.pdf: === Exporting PowerPoint files ===
INFO    mdd.utils.pdf_export: Found 1 file(s) to export:
INFO    mdd.utils.pdf_export:   - mdd-tour.pptx
INFO    mdd.utils.pdf_export: Exporting: mdd-tour.pptx -> mdd-tour.pptx.pdf
INFO    mdd.utils.pdf_export: Exported 1 file(s), skipped 0 file(s)
INFO    mdd.commands.pdf: === Exporting Word documents ===
INFO    mdd.utils.pdf_export: Found 1 file(s) to export:
INFO    mdd.utils.pdf_export:   - mdd-tour.docx
INFO    mdd.utils.pdf_export: Exporting: mdd-tour.docx -> mdd-tour.docx.pdf
INFO    mdd.utils.pdf_export: Exported 1 file(s), skipped 0 file(s)
INFO    mdd.commands.pdf: All exports completed successfully
```

Word and PowerPoint open while this runs. The output keeps the source
extension: `mdd-tour.docx.pdf`, not `mdd-tour.pdf`. Every derived file in `mdd`
is named that way, so you can always tell what a file came from. Export is also
incremental — it skips a PDF that is newer than its source unless you change
the source.

## 6. Convert an Office file back to Markdown

This is the direction `mdd` uses when it pulls documents out of a remote
system. `mdd convert` reads `.docx`, `.pptx` and `.pdf` and writes a Markdown
sibling.

> [!IMPORTANT]
> The first run downloads around 500 MB of Docling models into
> `~/.cache/docling/`. This is the slow step. Later runs reuse the cache.

Convert the one file rather than the directory:

```bash
mdd -v convert mdd-tour.docx
```

```
INFO    mdd.commands.convert: [1/1] Converting: mdd-tour.docx
```

That writes `mdd-tour.docx.md`. Pointing `mdd convert` at the directory instead
would also convert the two template symlinks, which is rarely what you want.

Read the result:

```bash
cat mdd-tour.docx.md
```

```markdown
# mdd-tour

# mdd-tour

**Your subtitle here**

**Your Name**


### 1 Introduction

This is a sample document that outputs to both PowerPoint and Word formats.

### 2 Key Points

- Edit this .qmd file with your content
- Run ./render.sh to generate both .pptx and .docx files
- The unified mdd pdf command will export both to PDF

### 3 Code Example

def hello():
    print("Hello, world!")

### 4 Conclusion

- Quarto makes it easy to create multiple output formats
- Single source, multiple outputs
```

Compare that against `mdd-tour.qmd` and you have the honest version of what
"near-lossless" means. The prose, the structure and the list items survive. The
title appears twice, `##` headings came back as `###` with Word's numbering
attached, inline code lost its backticks, and the Python block is no longer a
fenced code block.

This is the round trip through a *rendered* Word file, which is the worst case:
Quarto turned Markdown into Word styling, and Docling read the styling back as
best it can. The Confluence path preserves far more, because `mdd` maps
Confluence storage format to its own document model rather than guessing from
visual styling. [Concepts](03-concepts.md) explains the difference.

The practical rule: treat converted Markdown as a starting point for a human to
review, not as a faithful copy.

## 7. Search it

`mdd search` wraps [ripgrep](https://ripgrep.org), so it needs `rg` on your
`PATH`. It normally searches the mirror roots named in your configuration. You
have none yet, so it tells you so:

```bash
mdd search "PowerPoint"
```

```
No configured mirror roots found. Use --include to add a search path.
```

Add a root for this one run:

```bash
mdd search --include . "PowerPoint"
```

```
./mdd-tour.docx.md
  Title: mdd-tour

  L12:  This is a sample document that outputs to both PowerPoint and Word formats.
```

Results carry the document title as well as the path. The title comes from
`title:` in the frontmatter, or from the first `#` heading when there is no
frontmatter, as here. That is what makes results readable when the mirror is
thousands of pages deep. The default cap is ten matches in total, and `--limit`
changes it:

```bash
mdd search --include . --limit 3 "output"
```

```
./mdd-tour.docx.md
  Title: mdd-tour

  L12:  This is a sample document that outputs to both PowerPoint and Word formats.
  L27:  - Quarto makes it easy to create multiple output formats
  L28:  - Single source, multiple outputs
```

`--json` prints one record per match, which is the form to use from a script or
an agent. Once you configure a mirror, `--space` and `--site` narrow the search
to one Confluence space or one SharePoint site.

## 8. Clean up

```bash
cd ~
rm -rf ~/mdd-quickstart
```

The Docling model cache in `~/.cache/docling/` stays. Delete it too if you do
not plan to run `mdd convert` again.

## Next

You have seen the offline half of `mdd`. The other half mirrors a remote system
into git, and that half can overwrite pages other people wrote.

> [!CAUTION]
> Read [Safety](04-safety.md) before your first sync. `mdd confluence
> sync-space` and `mdd sharepoint sync-site` write to production systems by
> default.

- [Concepts](03-concepts.md) — what a mirror is, and which way content flows.
- [Safety](04-safety.md) — what can destroy data, and how to hold it back.
- [Configuration and secrets](05-configuration.md) — config files and `op://`
  references.
- [Your first Confluence sync](07-confluence-first-sync.md) — bring your own
  tenant, starting read-only.
- [Your first SharePoint sync](08-sharepoint-first-sync.md) — the same, through
  OneDrive.
