# Confluence-first authoring guide

This guide walks through composing the test-corpus fixtures that
**cannot** be authored in markdown because markdown has no syntax
for the underlying Confluence shape. You compose each page directly
in the Confluence editor at
<https://markdown.atlassian.net/wiki/spaces/MDD>, then pull it down
into the corpus repo via `mdd confluence export page`.

The markdown-first batch was completed by `scripts/push-fixtures.py`
and lives under `fixtures/` already. This guide covers the
remaining **13 confluence-first fixtures** across 5 categories.

## Prerequisites

- Browser logged into <https://markdown.atlassian.net> (the
  project test instance — single user).
- Terminal at the corpus repo root:
  ```bash
  cd ~/git/mdd/test-confluence/MDD
  ```
- 1Password unlocked (`op` calls will trigger biometric).
- A scratch directory for exports:
  ```bash
  mkdir -p /tmp/cf-export
  ```

## The pattern (read this first)

Every confluence-first fixture follows the same four steps:

1. **Compose in the Confluence UI.**
   - In the MDD space, click "Create" (top nav) → "Blank page".
   - Set the page title exactly as specified in the recipe below.
   - Insert the macro / layout / table per the recipe.
   - Click "Publish".
   - Note the page ID from the URL —
     `https://markdown.atlassian.net/wiki/spaces/MDD/pages/<ID>/<slug>`.

2. **Export to a scratch directory.**
   ```bash
   mdd confluence export page <ID> --output /tmp/cf-export/
   ```
   This writes `/tmp/cf-export/<page-title>.md` (note: directly
   under `--output`, not under a `MDD/` subdirectory — the export
   command flattens the space level when a single page is exported).

3. **Move into the corpus and rename to the conventional path.**
   ```bash
   mv "/tmp/cf-export/<exact title>.md" "fixtures/<category>/<name>.md"
   ```
   Filename convention: `<sub-shape>.md`, kebab-case, no spaces.
   The Confluence page title can stay human-readable.

4. **Add the `test_corpus:` frontmatter block** at the top of the
   moved file. The export writes a `confluence:` block but not the
   corpus-specific metadata; you add it by hand. Per-fixture
   templates are inline below.

After all fixtures in a category land in `fixtures/`, commit and
push:

```bash
git add fixtures/<category>/
git commit -m "fixtures: <category> — confluence-first authored via UI"
git push
```

Why mix `confluence:` (machine-written) and `test_corpus:`
(hand-added)? The `confluence:` block is mdd's standard export
metadata — it'll be overwritten on every `mdd confluence export`.
The `test_corpus:` block is documentation we want preserved across
exports. Putting them as two top-level keys keeps them clearly
separated.

---

## Category 1 — Callouts (5 fixtures)

Confluence has five callout macros: tip, info, note, warning, panel.
Each gets one fixture exercising its rich-text body.

### 1.1 Tip callout (worked example — read fully)

**Confluence page title**: `Tip callout (rich body)`
**Target file**: `fixtures/callouts/tip-rich-body.md`

In the editor:

1. Type `/tip` and press Enter to insert a tip macro. A green
   callout appears, cursor inside.
2. Inside the callout, type three short paragraphs:
   - First paragraph: "Tip macros highlight helpful suggestions.
     They render as a green callout in Confluence."
   - Second paragraph: "The body can contain **bold text**,
     *emphasis*, and `inline code` like any paragraph."
   - Third paragraph: "Round-trip should preserve the macro
     wrapper and all inline formatting within the body."

3. Click outside the macro, then "Publish".

Export, move, and add frontmatter:

```bash
mdd confluence export page <ID> --output /tmp/cf-export/
mv "/tmp/cf-export/Tip callout (rich body).md" \
   fixtures/callouts/tip-rich-body.md
```

Open `fixtures/callouts/tip-rich-body.md` and prepend (above the
existing `confluence:` block) a `test_corpus:` block. The final
frontmatter should look like:

```yaml
---
test_corpus:
  authoring: confluence-first
  shapes:
    - callout-tip
    - inline-strong
    - inline-em
    - inline-code
confluence:
  url: https://markdown.atlassian.net/wiki/spaces/MDD/pages/<ID>/...
  page_id: '<ID>'
  ...
---
```

### 1.2 Info callout

**Confluence page title**: `Info callout (rich body)`
**Target file**: `fixtures/callouts/info-rich-body.md`

Type `/info` → Enter. Compose two short paragraphs of plain prose
inside. Add a third paragraph that contains a `[link to example](https://example.com)`
to exercise inline links inside callout bodies.

`test_corpus.shapes`: `[callout-info, inline-link]`

### 1.3 Note callout

**Confluence page title**: `Note callout (rich body)`
**Target file**: `fixtures/callouts/note-rich-body.md`

Type `/note` → Enter. Compose a single longer paragraph plus a
bullet list with three items inside the callout body. This exercises
**nested block content** in a callout (the existing converter
flattens this; we want a regression test for it).

`test_corpus.shapes`: `[callout-note, callout-nested-blocks, list-bullet]`

### 1.4 Warning callout

**Confluence page title**: `Warning callout (rich body)`
**Target file**: `fixtures/callouts/warning-rich-body.md`

Type `/warning` → Enter. Compose two paragraphs. Inside one of
them, include `inline code` and an `[external link](https://pandoc.org)`.

`test_corpus.shapes`: `[callout-warning, inline-code, inline-link]`

### 1.5 Panel callout

**Confluence page title**: `Panel callout (rich body)`
**Target file**: `fixtures/callouts/panel-rich-body.md`

Type `/panel` → Enter (or `/info panel` depending on your
Confluence build; the macro family is the same). Compose a short
paragraph and a numbered list. Panel macros sometimes have a
configurable colour parameter — if you can set one without
fighting the UI, do; otherwise leave default.

`test_corpus.shapes`: `[callout-panel, list-ordered]`

---

## Category 2 — Page links (2 fixtures)

### 2.1 Same-space page link (`ri:page`)

**Confluence page title**: `Same-space page link`
**Target file**: `fixtures/links/ri-page-same-space.md`

The target page already exists in the corpus — use
`Plain paragraph` (or any other markdown-first fixture; pick one
with a memorable title).

In the editor:

1. Type a short sentence like "See ".
2. Inside that sentence, type `[[` (double-bracket) — Confluence
   pops up a page autocomplete.
3. Begin typing "Plain paragraph"; pick the matching page.
4. Continue the sentence: "[Plain paragraph] for the simplest
   round-trip case."
5. Add a second paragraph with another inline page link mid-
   sentence followed by trailing text — explicitly the #70/#71
   pattern that bit us before.

Publish.

```bash
mdd confluence export page <ID> --output /tmp/cf-export/
mv "/tmp/cf-export/Same-space page link.md" \
   fixtures/links/ri-page-same-space.md
```

`test_corpus.shapes`: `[link-ri-page-same-space, link-inline-trailing-text]`

### 2.2 Attachment link (`ri:attachment`)

**Confluence page title**: `Attachment link`
**Target file**: `fixtures/links/ri-attachment.md`

**Gotcha** (recorded after first attempt): clicking the paperclip
toolbar icon and uploading a file inserts a `view-file` macro
card, **not** an `ac:link` with `ri:attachment`. They look similar
in the editor but the storage XML is completely different — the
card is `<ac:structured-macro ac:name="view-file">`.

To get a true `ac:link` with `ri:attachment`:

1. Upload the file first via the paperclip → it appears as a
   card.
2. Delete the card from the body.
3. In the page metadata sidebar (right-hand panel), the file
   should appear as an attachment.
4. Type some prose text, select a span of it, and use Insert →
   Link (or the link icon in the floating toolbar).
5. In the link dialog, switch to the "Attachments" tab and pick
   the uploaded file.
6. Continue the sentence after the link to exercise trailing
   text.
7. Publish.

If the "Attachments" tab in the link dialog isn't present in the
new editor, fall back to the legacy "Insert link" dialog (you may
need to enable it in personal settings) or accept the `view-file`
form and recategorise as a niche macro (see
`niche-macros/view-file-macro.md` for an example).

```bash
mdd confluence export page <ID> --output /tmp/cf-export/
mv "/tmp/cf-export/Attachment link.md" \
   fixtures/links/ri-attachment.md
```

**Attachment binary download known-bad** (2026-05-11): on the free
tier, `mdd confluence export` currently 404s when fetching
attachment binaries (`GET /download/attachments/.../<name>?...`).
The page itself exports fine; only the binary copy is missing.
Worth filing as a bug against mdd separately. For now the
fixture's value is the storage XML round-trip, not the binary.

`test_corpus.shapes`: `[link-ri-attachment, attachment-binary]`

---

## Category 3 — Layout sections (2 fixtures)

### 3.1 Two-equal columns

**Confluence page title**: `Layout two-equal columns`
**Target file**: `fixtures/layout/two-equal.md`

In the editor:

1. Click "+" in the toolbar → "Layouts" → "Two columns equal".
   (Or `/layout` → pick two-equal.)
2. Left column: type a paragraph of plain prose.
3. Right column: type a different paragraph plus a bullet list.
4. Publish.

The current converter flattens layouts; the fixture is the
regression test for content order surviving the flatten.

`test_corpus.shapes`: `[layout-two-equal, list-bullet]`

### 3.2 Three-equal columns

**Confluence page title**: `Layout three-equal columns`
**Target file**: `fixtures/layout/three-equal.md`

Same pattern, three columns each with one short paragraph. Pick
distinct sentinel text per column so the round-trip diff catches
column reordering.

`test_corpus.shapes`: `[layout-three-equal]`

---

## Category 4 — Tables with merged cells (1 fixture)

**Confluence page title**: `Table with merged cells`
**Target file**: `fixtures/tables/merged-cells.md`

In the editor:

1. Insert a 4×4 table (toolbar → table or `/table`).
2. First row: header row with cells "Quarter", "Q1", "Q2", "Q3".
3. Use the table cell toolbar to **merge** cells:
   - Merge "Q1" and "Q2" header cells into one cell labelled
     "First half".
   - In a body row, merge two cells in the same row.
   - In another body row, merge two cells across rows (rowspan).
4. Fill in the remaining cells with sentinel values.
5. Publish.

Confluence storage represents merged cells via `colspan` and
`rowspan` attributes on `<td>` / `<th>`; the current converter
either flattens or drops these — fixture is the regression test.

```bash
mdd confluence export page <ID> --output /tmp/cf-export/
mv "/tmp/cf-export/Table with merged cells.md" \
   fixtures/tables/merged-cells.md
```

`test_corpus.shapes`: `[table, table-merged-cells]`

---

## Category 5 — Niche macros (3 fixtures)

These exercise the `RawBlock` / passthrough path in any future IR.
The macros aren't semantically modelled by mdd today — round-trip
must preserve them verbatim.

### 5.1 Expand macro

**Confluence page title**: `Expand macro`
**Target file**: `fixtures/niche-macros/expand.md`

`/expand` → set the heading to "Click to reveal" and the body to
two paragraphs of placeholder text.

`test_corpus.shapes`: `[macro-expand]`

### 5.2 Status macro

**Confluence page title**: `Status macro`
**Target file**: `fixtures/niche-macros/status.md`

Compose a paragraph: "The current status is ". Then `/status` —
choose a colour (green/red/yellow) and a label like "On track".
Add another `/status` in the same paragraph with a different
colour/label. The macros render inline so this exercises both the
inline-macro shape and trailing-text-after-inline.

`test_corpus.shapes`: `[macro-status, inline-macro]`

### 5.3 Children macro

**Confluence page title**: `Children macro`
**Target file**: `fixtures/niche-macros/children.md`

`/children` — this inserts a macro that, at render time, lists the
current page's child pages. Since this page has no children, the
rendered output is empty, but the storage XML carries the macro
itself. That's what we want to round-trip.

Add a paragraph above and below the macro so the surrounding
content provides context for the test.

`test_corpus.shapes`: `[macro-children]`

---

## Final commit

After all 13 fixtures land in `fixtures/`:

```bash
git status                    # confirm 13+ new files (.md + maybe _attachments/)
git add fixtures/
git commit -m "fixtures: confluence-first authored via UI

Adds the shapes that markdown can't natively express:
- callouts/{tip,info,note,warning,panel}-rich-body.md
- links/{ri-page-same-space,ri-attachment}.md
- layout/{two-equal,three-equal}.md
- tables/merged-cells.md
- niche-macros/{expand,status,children}.md

All composed in the Confluence editor at markdown.atlassian.net
and pulled via 'mdd confluence export page'."
git push
```

## Things to NOT worry about

- **Jira and Smartcard macros.** These require a Jira instance
  link and live URL fetching respectively. Both rely on external
  state that the corpus shouldn't depend on. Skip.
- **Cross-space `ri:page` links.** We have one space. Adding a
  second space (e.g. `MDD2`) just to test cross-space links is
  out of scope for the bootstrap; revisit if the spike work
  needs it.
- **The `ac:link` shape without `ac:link-body`.** Hard to compose
  in the UI; covered indirectly by the smart-card form which
  Confluence emits with various link-body presences.
- **`exported_at` differing between local and live.** Every export
  refreshes this field — don't try to keep it stable.

## When something goes wrong

- **Export writes to wrong filename.** Check the page title in
  Confluence matches what you typed. Rename in the UI if needed,
  re-export.
- **`mdd confluence export` says "config not found".** You're not
  in the corpus repo root. `cd ~/git/mdd/test-confluence/MDD`.
- **`op read` times out.** Trigger 1Password biometric (look for
  a fingerprint prompt or click the 1Password menu bar icon).
- **Macro doesn't appear in the slash menu.** Some macros require
  the Confluence admin to enable them. As single-user admin you
  can enable them under Settings → Apps → Manage apps.
