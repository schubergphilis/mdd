# S38: SharePoint test corpus

**Purpose:** Vendor a local mirror of the `MDD` SharePoint site as a test corpus alongside the existing Confluence corpus, and reshape `tests/corpus/` to host both.

**Status:** Implemented (2026-07-27)

> Originally implemented 2026-05-20; amended 2026-07-27 (neutral, de-branded corpus).

## Introduction

`tests/corpus/` today holds a vendored mirror of the project test
Confluence space at `markdown.atlassian.net/wiki/spaces/MDD`. It is
the canonical input for the IR round-trip suite ([S33](S33-ir-roundtrip-testing-and-benchmarks.md))
and for hand-authored fixture tests against the `mdd confluence`
verbs ([S09](S09-confluence-command.md), [S14](S14-confluence-sync.md)).

We now have a parallel SharePoint site — `MDD` on the maintainer's
tenant, synced via OneDrive to a local `MDD - Documents/` folder — that
was hand-built to exercise the `mdd sharepoint` reconciliation
matrix from [S18](S18-sharepoint-sync.md). It contains realistic
office files (Word, PowerPoint, Excel), `.docx.md` / `.pptx.md`
siblings with populated `sharepoint.sync` frontmatter, a `.url`
shortcut, a plain `.txt`, an `.md` authored in SharePoint's
in-browser editor, a nested folder, and two folders that exercise
the two opposing first-sync lifecycles (`Markdown-First/` with
`update_office: true`, `Templated/` with `update_office: false`).

This spec:

1. Reshapes `tests/corpus/` into a per-source layout
   (`tests/corpus/confluence/`, `tests/corpus/sharepoint/`) so the
   two corpora can coexist without name collisions.
2. Vendors the SharePoint MDD site contents under
   `tests/corpus/sharepoint/` as the canonical input for SharePoint
   sync tests and as the realistic-input substrate for the
   `office`-marked test suite.

The existing Confluence corpus moves verbatim; no Confluence test
needs to change beyond a path adjustment.

## Requirements

- **Two parallel corpora under one root.** `tests/corpus/` becomes
  the umbrella; sources live at `tests/corpus/<source>/` where
  `<source>` is `confluence` or `sharepoint`.
- **SharePoint corpus mirrors the site's on-disk layout.** Folder
  names, filenames, and the `<Site> - Documents/` site-root suffix
  match what `mdd sharepoint sync-site` expects to find under a
  OneDrive sync root, so tests can point `resolve_sync_root()` at
  `tests/corpus/sharepoint/` and exercise the real walker.
- **Office binaries are vendored.** The `.docx` / `.pptx` / `.xlsx`
  files are committed as-is. Generating them at test time would
  reintroduce the converter-version churn the `office_sha256_at_sync`
  field is meant to detect.
- **The vendored `.docx.md` / `.pptx.md` siblings keep their real
  `sharepoint.sync` frontmatter** (hashes, `last_sync`, converter
  version, `update_office`). The frozen hashes anchor the corpus to
  a known reconciliation state and let tests assert specific verdicts
  from the [S18](S18-sharepoint-sync.md) diff table.
- **Every cell of the [S18](S18-sharepoint-sync.md) diff table has at
  least one fixture pair.** Where the current real-site content
  leaves a cell uncovered, we add a pair under a `diff-table/`
  folder rather than perturbing the realistic fixtures. These
  fixtures are equally "real" SharePoint content — the folder
  name reflects what they cover, not their authoring origin.
- **The corpus is self-contained.** No test depends on a local
  OneDrive mount at runtime. The user's local OneDrive sync is the
  *source* the corpus was harvested from, not a runtime dependency.
- **A `configs/sharepoint.yaml` parallel to the Confluence one
  exists** and points at `tests/corpus/sharepoint/` as the sync
  root, so `mdd sharepoint ...` invocations from inside the corpus
  directory do not require a real OneDrive mount.

## Design Approach

### Layout

```
tests/corpus/
  README.md                          # umbrella: explains the two corpora
  confluence/                        # was: tests/corpus/*
    README.md
    configs/confluence.yaml
    corpus/                          # long-form synthetic pages
    fixtures/                        # short, focused pages
    _snapshots/                      # captured ground truth per page_id
    docs/
    scripts/
  sharepoint/
    README.md
    configs/sharepoint.yaml
    MDD - Documents/                 # site root, name-equivalent to real site
      Example-Excel.xlsx
      Example-Markdown.md
      Example-PowerPoint.pptx
      Example-PowerPoint.pptx.md
      Example-Shortcut.url
      Example-Text.txt
      Example-Word.docx
      Example-Word.docx.md
      Example-Folder/
        Example-Word-Folder.docx
        Example-Word-Folder.docx.md
      Markdown-First/                # md-authored, update_office: true
        Example-Templated-PowerPoint.pptx
        Example-Templated-PowerPoint.pptx.md
        Example-Templated-Word.docx
        Example-Templated-Word.docx.md
      Templated/                     # docx/pptx-authored, update_office: false
        Example-Templated-PowerPoint.pptx
        Example-Templated-PowerPoint.pptx.md
        Example-Templated-Word.docx
        Example-Templated-Word.docx.md
      diff-table/                    # fixtures for [S18] cells the real site does not naturally cover
        docx-only-no-md/
        md-only-no-docx/
        divergence/
        ...
```

The Confluence side moves wholesale: `git mv tests/corpus/{configs,corpus,fixtures,_snapshots,docs,scripts,README.md} tests/corpus/confluence/`. Only callers that hard-code the old path need to update.

Known callers to update at the move:

- `tests/ir/conftest.py` — `CORPUS_ROOT = .../tests/corpus` → `.../tests/corpus/confluence`.
- `tests/corpus/confluence/README.md` — internal relative links (e.g. to `docs/confluence-first-authoring.md`) stay correct because everything moves together.
- `tests/corpus/confluence/scripts/` — verify `push-fixtures.py` and any path-anchored helpers still resolve.
- The existing `confluence.yaml` load-before-`~/.config` guarantee from `tests/corpus/configs/` ([S07](S07-data-protection.md)) is preserved because `mdd confluence` is normally invoked from inside `tests/corpus/confluence/`, not from `tests/corpus/`.

### Site-root naming with a space

`MDD - Documents/` mirrors the OneDrive naming convention that
`_derive_site_name()` in `mdd.sharepoint.export` already strips
(`"<Site> - Documents"` → `<Site>`). Keeping the space matches
the real site at the cost of needing quoted paths in shell
commands; the symmetry with the production path is worth it
since the same string ends up in `_derive_site_name` test
expectations.

### Vendoring binary office files

Each office file is ≤ ~1.5 MB; the full set is under 2 MB. Git
handles this without LFS. The largest are the house-templated
files under `Templated/` (authored from a corporate Office template
with embedded brand assets); the `Markdown-First/` siblings are an
order of magnitude smaller because Quarto renders them from a
lightweight reference doc.

The committed binaries are **de-branded**, not redacted: they keep
their full part structure, style set and layout so they stay
realistic converter input, but every organisation-identifying
element is rewritten. See the
[2026-07-27 amendment](#amendment-2026-07-27-neutral-de-branded-corpus)
below for what that covers and why.

### Diff-table coverage

The real-site content covers the common cells of the
[S18](S18-sharepoint-sync.md) diff table (both sides clean;
`update_office: false`; `update_office: true`) but does **not**
cover every cell — there is no naturally divergent pair, no
"docx-only" or "md-only" first-encounter, etc. We add a
`diff-table/` subtree with fixture pairs for the uncovered
cells. Each fixture carries a `test_corpus:` block in
frontmatter (mirroring the Confluence-corpus convention from
[S32](S32-ir-test-corpus-expansion.md)):

```yaml
test_corpus:
  source: sharepoint
  diff_table_cell: "office_now!=sync && md_now!=sync && update_office=true"
  introduced: 2026-05-20
```

This block is informational — tests parse it to assert that the
cell→verdict mapping in the reconciler is exhaustive.

### Config for the SharePoint corpus

`tests/corpus/sharepoint/configs/sharepoint.yaml` points the sync
root at the parent directory (`..`) so invoking `mdd sharepoint
sync-site MDD` from inside `tests/corpus/sharepoint/` resolves
without a `--sync-root` flag:

```yaml
sharepoint:
  sync_root: .
  # No tenant URL: the corpus is offline-only. Integration tests
  # against the live MDD site use ~/.config/mdd/sharepoint.yaml.
```

### Test usage

Three classes of test consume the SharePoint corpus:

1. **Plain unit tests** (no marker): exercise the converter
   registry, `mdd.sharepoint.rules.decide()`, `mdd.sharepoint.diff`,
   and `mdd.sharepoint.apply` against the real fixture pairs.
   These work without Microsoft Office because the converters
   read `.docx` / `.pptx` as zipped XML.
2. **`@pytest.mark.office` tests**: drive Word / PowerPoint via
   AppleScript using the real fixture files as input. These
   replace the current ad-hoc `_minimal_docx()` helpers in
   `tests/commands/test_pdf_*_office.py` for cases where we want
   layout / style fidelity in the output.
3. **`@pytest.mark.integration` tests** (existing): unchanged.
   They continue to talk to the live MDD SharePoint site via
   the user's `~/.config/mdd/sharepoint.yaml`. The corpus is
   not a substitute.

### Refresh workflow

The corpus is harvested once from the local OneDrive mirror via
`cp -R`, then run through the de-branding pass described below. There is
no otherwise-scripted refresh path: the corpus is expected to drift
slowly, and agents do not re-harvest unless the user asks.

## Implementation Notes

- Use `git mv` for the Confluence-side rename so history follows.
- The `git mv` is one commit; the SharePoint-corpus add is a
  second commit. Reviewers can verify the rename is path-only
  by diffing the first commit against `--find-renames`.
- `tests/ir/conftest.py` is the only known runtime path to
  update; grep for `tests/corpus` in the repo before the move
  to catch any others.
- `mise run spec-check` continues to scan `docs/spec/` only,
  so the move does not affect it.
- The umbrella `tests/corpus/README.md` is short: it points at
  the two per-source READMEs, explains the split, and notes that
  future sources (e.g. Lucid) follow the same `tests/corpus/<source>/`
  convention.
- The `MDD - Documents` directory name has a space, which is
  fine for git but needs quoting in shell scripts. CI runners
  on both GitHub and GitLab handle this correctly today (the
  Confluence corpus already includes a `confluence-first-authoring.md`
  path; no novel quoting concerns).

## Amendment (2026-07-27): neutral, de-branded corpus

The open-source split publishes
`mdd.sharepoint` — and therefore this corpus — outside the company.
The corpus as originally vendored could not ship: the Office binaries
carried a tenant's identity, not just its visual style.

### What the fixtures actually leaked

Auditing the 15 committed binaries turned up five distinct classes of
identifying data, only one of which was visible when opening the file:

1. **Tenant-bound XML parts.** `docProps/custom.xml` held MSIP
   sensitivity labels (`_Name: Internal`), the tenant `SiteId` GUID and
   a SharePoint `ContentTypeId`. `customXml/item*.xml` held the
   document-template vendor's tenant name, template ID and user-profile
   ID, plus a verbatim copy of the corporate colour scheme.
2. **Co-authoring history.** `ppt/changesInfos/changesInfo1.xml`
   recorded every web-editor edit with the editor's display name,
   corporate e-mail address and directory object GUID.
3. **Authorship metadata.** `dc:creator` / `cp:lastModifiedBy` in
   `docProps/core.xml` named a real person.
4. **House brand.** The theme name, colour-scheme name, the brand
   palette (hex values threaded through `styles.xml`, every
   `slideLayout*.xml`, and the VML fallback shapes), a licensed
   corporate typeface referenced by name, and the logo raster/vector
   assets under `word/media/` and `ppt/media/`.
5. **A tenant Office add-in.** `word/webextensions/` bound the document
   to an internally published task pane.

### Requirements added

- **The corpus contains no organisation, tenant, person or product
  brand.** This is a hard gate, not a best effort: a `git grep` over
  the corpus (including inside the zipped Office parts) must come back
  empty for hostnames, e-mail addresses, brand names, brand hexes and
  brand font names.
- **De-branding is mechanical and re-runnable.** One tool owns the
  transformation, so a future re-harvest is one command rather than a
  manual audit. It drops the tenant-bound parts listed above (fixing
  `[Content_Types].xml` and the `.rels` graph as it goes), clears
  authorship, renames the theme and colour scheme, remaps the brand
  palette onto the stock Office palette, substitutes widely available
  fonts, drops `docProps/thumbnail.*` (a pre-scrub raster render of the
  first slide, which no textual rewrite can reach), and replaces every
  embedded image with a neutral `mdd` wordmark letterboxed to the
  original pixel dimensions. The tool itself is **not** part of this
  distribution: it carries one organisation's brand lookup tables, and
  the corpus is vendored data that contributors must not re-harvest.
  See the corpus README.
- **Structural parity is preserved.** The packages keep their part
  layout, style sets (61 styles for the Quarto reference docs, 428 for
  the corporate-template document), slide layouts and content. They
  still open in `python-docx` / `python-pptx`, still convert through
  Docling, and Quarto still renders against the neutral reference docs.
- **Reconciliation parity is pinned by a test.** Rebuilding the
  binaries changes their SHA-256, which changes which
  [S18](S18-sharepoint-sync.md) diff-table cell each pair lands on.
  `tests/sharepoint/test_corpus_matrix.py` asserts the expected
  `PairAction` for all 13 pairs plus the on-disk shape of the two
  single-sided fixtures, and fails if the corpus grows a pair with no
  pinned verdict. Before this amendment *no test consumed the corpus at
  all*, so a silent coverage loss was undetectable.

### Consequence for hashes

`office_sha256_at_sync` and `md_sha256_at_sync` encode intent, not just
history: a fixture built for "office changed since sync" needs its
frozen hash to *differ* from the file on disk, and one built for "in
sync" needs it to match. A refresh must re-freeze only the matching
ones. The matrix test reports both the frozen and the actual digest on
failure so this is mechanical rather than archaeological.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [S07](S07-data-protection.md) — corpus-local config load order
  guarantee; the SharePoint config inherits the same behaviour.
- [S10](S10-sharepoint-command.md) — site walker and
  `_derive_site_name` expectations the layout mirrors.
- [S18](S18-sharepoint-sync.md) — diff-table semantics the
  fixtures exercise; defines the `sharepoint.sync` frontmatter
  block the vendored `.docx.md` files carry.
- [S32](S32-ir-test-corpus-expansion.md) — `test_corpus:`
  frontmatter convention reused by the synthetic diff-table
  fixtures.
- [S33](S33-ir-roundtrip-testing-and-benchmarks.md) — current
  Confluence-side consumer of `tests/corpus/`; its `CORPUS_ROOT`
  pointer moves with the rename.

## Out of scope

- Refactoring `mdd.sharepoint` internals. This spec only adds
  a corpus and updates one test fixture path.
- Adding `.xlsx` conversion support. The Excel file is a
  fixture for "ignored / unsupported" cases only.
- Changes to the live MDD SharePoint site. The site is the
  source we harvest from; the spec is silent on how it is
  maintained.
- Lucid or Confluence-side corpus changes. The Confluence
  move is a path-only rename.
