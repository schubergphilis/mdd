# MDD — SharePoint sync test corpus

A neutral, offline mirror of a `MDD` SharePoint site laid out exactly
as OneDrive would sync it. The fixtures were harvested once from a real
tenant and then mechanically de-branded, so nothing here names an
organisation, a tenant, or a person: no tenant or site GUIDs, no
sensitivity labels, no co-authoring history, no brand palette, no
licensed typeface, and every embedded image replaced with a render of
[`assets/mdd-wordmark.svg`](../../../assets/mdd-wordmark.svg).

This is the canonical input for unit and office tests against
`mdd.sharepoint` ([S18](../../../docs/spec/S18-sharepoint-sync.md)).
Integration tests still talk to a live site via
`~/.config/mdd/sharepoint.yaml`; the corpus is not a substitute.

See [spec S38](../../../docs/spec/S38-sharepoint-test-corpus.md)
for layout, refresh policy, and design rationale.

## Layout

```
configs/sharepoint.yaml             — points mdd at "MDD - Documents/" as the sync root
MDD - Documents/                    — site root (matches the OneDrive naming convention)
  Example-Excel.xlsx                — unsupported-format fixture
  Example-Markdown.md               — md authored in the SharePoint in-browser editor
  Example-PowerPoint.pptx           — office-only first-encounter (with sibling)
  Example-PowerPoint.pptx.md        — sibling, update_office: false
  Example-Shortcut.url              — windows-shortcut fixture
  Example-Text.txt                  — plain-text fixture
  Example-Word.docx                 — office-only first-encounter (with sibling)
  Example-Word.docx.md              — sibling, update_office: false
  Example-Folder/
    Example-Word-Folder.docx        — nested-folder fixture
    Example-Word-Folder.docx.md
  Markdown-First/                   — md-first lifecycle, update_office: true
    Example-Templated-PowerPoint.pptx
    Example-Templated-PowerPoint.pptx.md
    Example-Templated-Word.docx
    Example-Templated-Word.docx.md
  Templated/                        — docx/pptx-first lifecycle, update_office: false
    Example-Templated-PowerPoint.pptx
    Example-Templated-PowerPoint.pptx.md
    Example-Templated-Word.docx
    Example-Templated-Word.docx.md
  diff-table/                       — fixture pairs for sync diff-table cells the real site does not naturally cover
    README.md
    docx-only-no-md/                — first-sync: docx, no md sibling
    md-only-no-docx/                — first-sync: md, no docx sibling
    both-no-sync-block/             — first-sync: both present, no sync block
    docx-changed/                   — office_now != sync, md_now == sync
    md-changed-update-true/         — office_now == sync, md_now != sync, update_office: true
    md-changed-update-false/        — office_now == sync, md_now != sync, update_office: false (SKIP)
    divergence/                     — office_now != sync, md_now != sync, update_office: true
    skip-both-changed/              — office_now != sync, md_now != sync, update_office: false (SKIP)
```

## Configuration

`configs/sharepoint.yaml` is committed and points the sync root at
`.` (i.e. this directory). When `mdd sharepoint sync-site MDD ...`
is invoked from inside `tests/corpus/sharepoint/`, mdd loads
`./configs/sharepoint.yaml` **before** `~/.config/mdd/sharepoint.yaml`,
so commands never accidentally touch the live tenant. See spec
[S07](../../../docs/spec/S07-data-protection.md) for the credentials
model.

## Refresh

Refresh is manual and maintainer-only: the corpus is harvested once
from a real tenant and updated only when someone asks. There is no
scripted refresh path here, and the de-branding tool is not part of
this distribution — it is a maintainer tool that carries one
organisation's brand lookup tables.

**Do not contribute Office files harvested from your own tenant.**
Freshly harvested `.docx`/`.pptx`/`.xlsx` files carry tenant and site
GUIDs, sensitivity labels, co-authoring history with e-mail addresses,
template-tooling identifiers, licensed font names, and house-brand
theming — inside the zipped XML parts, where review does not see them.
A pull request touching these binaries will be rejected. Open an issue
describing the case you need covered instead; a maintainer can add a
fixture through the de-branding pass.

After any refresh, the matrix test says which frozen hashes need
re-freezing — see
[`tests/sharepoint/test_corpus_matrix.py`](../../sharepoint/test_corpus_matrix.py),
which pins one [S18](../../../docs/spec/S18-sharepoint-sync.md) diff-table
verdict per fixture pair so a refresh cannot silently drop coverage.

## Related

- [S07](../../../docs/spec/S07-data-protection.md) — data protection
- [S10](../../../docs/spec/S10-sharepoint-command.md) — sharepoint export command
- [S18](../../../docs/spec/S18-sharepoint-sync.md) — sharepoint sync command
- [S32](../../../docs/spec/S32-ir-test-corpus-expansion.md) — `test_corpus:` frontmatter convention
- [S38](../../../docs/spec/S38-sharepoint-test-corpus.md) — this corpus
