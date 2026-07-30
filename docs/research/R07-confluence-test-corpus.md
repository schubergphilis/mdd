# 007 - Test corpus for Confluence round-trip experiments

**Status:** Research notes. Not an implementation spec.

**Problem brief.** [Research note 006](R06-confluence-bidirectional-sync-ir.md)
proposes deciding between three IR foundations (status quo + provenance,
Pandoc with Lua writer, docling) empirically rather than by argument.
That requires a test corpus: representative Confluence content we can
round-trip through each candidate pipeline and measure against ground
truth.

The corpus carries `mdd`'s own licence (`LICENSE.md` in the corpus
repo). Where a fixture's content needs to travel upstream — e.g.
attached to a bug report against pandoc or docling — the specific
snippet is excerpted into the upstream channel directly.
Confidential content stays out of the corpus regardless, because the
corpus is hand-authored from scratch (no copying of pages from any
real space).

Infrastructure has been provisioned:

- A free-tier Confluence Cloud instance at <https://markdown.atlassian.net/>
  with one space `MDD` at
  <https://markdown.atlassian.net/wiki/spaces/MDD/overview>. Single
  user.
- A companion `mdd/test-confluence` git repository for the local
  mirror, sitting alongside the other content repos.

This note specifies what goes in the corpus, how it's authored,
where it lives, and how tests consume it.

## Goals

1. **Exhaustive enough on shape coverage** that round-tripping the
   corpus through each candidate pipeline exercises every code path
   the production system will hit. Missing a macro family in the
   corpus means missing a regression in the merge engine.
2. **Small enough to read end-to-end.** Reviewers should be able to
   open the corpus and understand what each fixture is for. No
   hundred-page generated mass.
3. **Reproducible from git.** Anyone with read access to the
   `mdd/test-confluence` repo can build the same corpus the same
   way. Tests are deterministic.
4. **Self-contained.** All content is hand-authored from scratch
   under the same licence as mdd itself. No copying of upstream
   content (CC-licensed or otherwise), no inclusion of confidential
   pages. When a snippet needs to travel upstream for bug
   reporting, it's excerpted at the point of use.

## Non-goals

- Performance benchmarking at scale. The corpus is for fidelity
  testing, not perf. A 200-page space sync is a future concern.
- Confluence Server / Data Center compatibility. We target
  Confluence Cloud's storage XHTML only.
- Coverage of every macro Confluence ships. We target the
  intersection of "macros mdd users will encounter" and "macros that
  exercise distinct code paths." See §"Macro coverage" below.

## Shape and macro coverage

The corpus must cover the following Confluence storage shapes. Each
gets at least one **focused fixture page** (short, one shape per
page) plus appearances inside the longer corpus pages where natural.

### Core HTML elements

- Headings h1–h6 (separate page exercising each level)
- Paragraphs: single, multiple, with inline formatting
- Inline: `strong`, `em`/`i`, `code`, `a` (with and without title)
- Blockquote
- Code blocks via `<pre>` (markdown-source path)
- Lists: bullet, ordered, nested mixed (ol inside ul and vice versa)
- Tables: plain, with header row, with merged cells (`colspan` /
  `rowspan`), with `<th>` in body rows
- `hr` and `br`

### Confluence-namespaced elements

- **Callout macros** (one fixture per): `tip`, `info`, `note`,
  `warning`, `panel`. Both empty bodies and rich-text bodies with
  nested formatting.
- **Code macro** (`<ac:structured-macro ac:name="code">`):
  with `<ac:plain-text-body><![CDATA[…]]></ac:plain-text-body>` and
  `<ac:parameter ac:name="language">…</ac:parameter>`. Multiple
  language values (bash, python, yaml, none).
- **ac:link variants**:
  - `<ri:page ri:content-title="…"/>` — the case that just broke
    in #70/#71. Same-space and cross-space (latter via
    `<ri:space ri:space-key="…"/>` child).
  - `<ri:url ri:value="https://…"/>` — external link, also a
    fallback shape for some macros.
  - `<ri:attachment ri:filename="…"/>` — links to attached files
    on the same page.
  - Inside paragraphs, list items, table cells, callout bodies.
  - With and without `<ac:link-body>`.
- **ac:image** with `<ri:attachment>`, `<ri:url>`, and with sizing /
  alignment attributes (`ac:width`, `ac:height`, `ac:align`,
  `ac:alt`).
- **Layout containers**: `<ac:layout>`, `<ac:layout-section
  ac:type="two_equal" | "three_equal" | "single">`,
  `<ac:layout-cell>`. The current converter flattens these
  transparently; corpus confirms content order survives.
- **Inline ac elements**: `<ac:emoticon ac:name="…"/>`,
  `<ac:placeholder>…</ac:placeholder>`.
- **Niche / passthrough macros** to exercise the RawBlock /
  passthrough path: `children` (auto-list of child pages), `expand`
  (collapsible section), `status`, `info-card`, `jira` (without a
  real Jira link — just confirms the macro structure round-trips),
  table of contents. Don't have to be semantically meaningful; the
  test is "verbatim macro survives the pipeline."

### Combinations known to be tricky

- `ac:link` inside paragraph with text trailing the link.
- `ac:link` inside list item with text trailing the link.
- `ac:link` inside a callout's rich-text body.
- Nested structures: code macro inside list item, callout inside
  blockquote, table cell containing a list.
- Tables with mixed inline formatting in cells (strong, link,
  inline code).
- Multi-paragraph callout bodies.
- Adjacent macros at the document root (no separating paragraph).

## Source-material policy

**All content is hand-authored from scratch** under the corpus
repo's licence. No upstream content (CC, public-domain, or
otherwise) is copied in; no confidential content is included. This
both simplifies the licence posture
(everything is mdd's own) and forces the corpus to be deliberate
about coverage (we write exactly what we want exercised, no more).

### Focused fixtures

Each fixture is ≤200 words, exists to exercise one specific shape,
and has a self-documenting filename. Reviewers should be able to
look at the filename and know what's under test. Stored under
`fixtures/<category>/` in the corpus repo. Filename convention is
`<sub-shape>.md` (e.g. `fixtures/links/inline-with-trailing-text.md`,
`fixtures/callouts/tip-rich-body.md`).

### Synthetic long-form pages

To provide realistic prose shape and naturally-occurring combinations
of elements, build a small set of **synthetic "fake company" pages**
that imitate the kind of content a real Confluence space would
contain: engineering handbook entries, project pages, meeting notes,
glossary entries. These pages exercise:

- Multi-paragraph prose with naturally-occurring inline links,
  callouts, and code blocks.
- Deep hierarchical structure (parent → child → grandchild pages).
- Niche macros (status, expand, info-card, jira-style references)
  in plausible contexts.
- Long-form content (~1000 words per page) so whitespace and
  paragraph-boundary handling get exercised at scale.

Two or three of these is sufficient. They live under `corpus/synth-*.md`
in the corpus repo. No upstream references, no real customer or
employee names; fully invented.

## Authoring policy

Per decision recorded in note 006: **both directions, roughly half
the corpus each way.**

### Confluence-first pages

Composed directly in the Confluence editor at
markdown.atlassian.net/MDD. Captures authentic, idiomatic storage
XHTML — including the editor's quirks (e.g. how the UI emits
`<p>` wrappers around inline content, how it assigns
`ac:local-id` / `ac:macro-id`, how it represents tables with
merged cells). Then `mdd confluence export` pulls them down to the
mirror. The exported markdown is committed.

Use case: tests the **storage → markdown** half of the pipeline
against content the converter didn't itself emit.

### Markdown-first pages

Authored as markdown source files in the
`mdd/test-confluence/MDD/…` tree, pushed via
`mdd confluence create-page` and `mdd confluence update-page`.
The Confluence-side storage XHTML is whatever mdd emits.

Use case: tests the **markdown → storage** half plus the
create/update flow end-to-end. Reproducible from git: anyone can
re-create the corpus on a fresh Confluence space by re-running the
push commands.

### Mapping authoring to fixtures

Each fixture page records its authoring origin in frontmatter:

```yaml
test_corpus:
  authoring: confluence-first | markdown-first
  shapes:
    - ac:link/ri:page
    - paragraph-trailing-text
  license: MIT | CC-BY-SA-4.0
  source: https://en.wikipedia.org/wiki/Markdown   # only for CC content
```

This lets tests filter by shape ("run all fixtures exercising
ac:link") and lets review tooling spot license issues mechanically.

## Repository layout

The `mdd/test-confluence` repo follows the same shape as
`mdd/confluence/<space>` content repos.

Note that `mdd/test-confluence` is a **namespace**, not a single
repo — each Confluence space mirrored maps to its own repo under it.
Today there is one space (`MDD`), mapped to repo `mdd/test-confluence/MDD`:

```
mdd/test-confluence/MDD/          # mirrors markdown.atlassian.net/wiki/spaces/MDD
├── LICENSE.md                    # licence covering the corpus content
├── README.md                     # what's here, how to refresh
├── .gitignore
├── configs/
│   └── confluence.yaml           # points mdd at markdown.atlassian.net
├── fixtures/                     # hand-authored focused pages
│   ├── callouts/
│   │   ├── tip-empty.md
│   │   ├── tip-rich-body.md
│   │   ├── info-with-nested-link.md
│   │   └── …
│   ├── links/
│   │   ├── ri-page-same-space.md
│   │   ├── ri-page-cross-space.md
│   │   ├── ri-url-external.md
│   │   ├── ri-attachment.md
│   │   ├── inline-with-trailing-text.md   # the #70/#71 case
│   │   └── …
│   ├── paragraph/
│   ├── tables/
│   ├── code/
│   ├── lists/
│   ├── images/
│   ├── layout/
│   └── niche-macros/             # children/expand/status/jira/info-card
├── corpus/                       # synthetic long-form pages
│   ├── synth-engineering-handbook.md
│   ├── synth-meeting-notes-2026-05-11.md
│   └── synth-glossary.md
├── _snapshots/                   # captured ground-truth per page_id
│   └── <page_id>/
│       ├── storage.xhtml         # body-format=storage
│       ├── export_view.html      # body-format=export_view
│       └── metadata.json         # page version, title, timestamps
└── scripts/                      # one-off scripts (refresh-corpus, validators)
```

Mirroring the standard content-repo shape keeps tooling and muscle
memory aligned — the same mental model that applies to
`mdd/confluence/<space>` content repos applies here.

## Fixture / snapshot strategy

Per decision recorded in note 006: **hybrid — snapshots for unit
tests, live-fetch for integration tier.**

### Snapshot tier (default unit tests)

For each page in the corpus, `_snapshots/<page_id>/` carries:

- `storage.xhtml` — the canonical Confluence storage body
- `export_view.html` — Confluence's rendered HTML
- `metadata.json` — page version, title, parent_id, space_id,
  timestamps, attachments manifest

These are committed to git. Unit tests load them directly. No
network. Deterministic.

The mdd tests in `tests/confluence/` get a new fixture loader
(`tests/confluence/test_corpus.py` or similar) that points at the
sibling `mdd/test-confluence/MDD/_snapshots/` directory — vendored
via git submodule or a `corpus_path` configurable in test config.
(Open question: submodule vs vendored copy vs editable path —
deferred to the harness note 008.)

### Live tier (`@pytest.mark.integration`)

A separate integration-test suite re-fetches the same page IDs
from markdown.atlassian.net and diffs against the snapshots. Drift
means either Confluence's API changed shape (rare but happens) or
our snapshots are stale.

Already supported by mdd's test infrastructure — the
`mise run test-integration` task and `@pytest.mark.integration`
marker exist. We just register new tests under that marker.

### Refreshing snapshots

`mise run refresh-corpus` (new task, defined in `mise.toml`):

1. Iterates over every page_id listed in
   `mdd/test-confluence/MDD/**/*.md` frontmatter.
2. Fetches storage and export_view bodies via the
   `mdd/test-confluence` confluence client.
3. Writes the three snapshot files per page.
4. Reports a git diff summary — what changed since last refresh.

The refresh is **manual, not automatic.** Drift detection runs on
demand. Auto-refreshing would hide real Confluence API changes that
we want to notice.

## Initial corpus build plan

A concrete sequence to bootstrap the corpus from zero. Each step
ends in a commit to `mdd/test-confluence`.

1. **Bootstrap the repo.** Initialize `mdd/test-confluence/MDD` with
   `LICENSE.md`, `README.md`, `.gitignore`, `configs/confluence.yaml`,
   and an empty `_snapshots/` directory. Licence boilerplate
   identical to mdd's own.
2. **Author the hand-authored fixtures.** One commit per shape
   category (callouts, links, tables, etc.). Each commit adds the
   markdown source under `MDD/fixtures/<category>/`.
3. **Push markdown-first fixtures to Confluence.** Use
   `mdd confluence create-page` (or `mdd confluence sync`) to
   populate the MDD space with the markdown-first half. Capture
   resulting `page_id`s into frontmatter.
4. **Author the Confluence-first fixtures.** Compose the other half
   directly in the Confluence editor. For each, use
   `mdd confluence export` to pull the markdown into the mirror.
5. **Author the synthetic long-form pages.** Two or three
   hand-authored "fake company" pages under `corpus/synth-*.md`
   that exercise prose-shape and combination patterns the focused
   fixtures don't naturally produce. Decide per-page which
   authoring side (Confluence-first vs markdown-first) to use.
6. **Capture initial snapshots.** Run `mise run refresh-corpus` for
   the first time. Commit the resulting `_snapshots/` tree.
7. **Wire mdd's tests to load corpus snapshots.** A small
   `tests/confluence/test_corpus_smoke.py` that round-trips every
   corpus page through the current `storage_to_md` and asserts the
   output isn't empty. This is the smoke test that the corpus is
   loadable; spike-specific tests come later.

Estimated effort: 1–2 days, dominated by step 2 (writing
fixtures) and step 5 (CC content adaptation).

## Open questions before bootstrapping

1. **Submodule vs vendored vs path config?** How does the mdd test
   tree find the corpus snapshots? Submodule is reproducible but
   adds setup friction; vendored duplicates content; path-config is
   the most flexible. Deferred to note 008 (experiment harness).
2. **Snapshot diff tolerance.** When the integration tier sees
   snapshot drift, what's the failure mode? Hard-fail and refuse
   to merge? Soft-warn and require manual ack? Affects how
   sensitive the suite is to Confluence-side flakiness.
3. **Should the corpus repo include `mdd configs/`?** The
   `mdd/test-confluence` repo needs a `configs/confluence.yaml`
   pointing at `markdown.atlassian.net` so that
   `mdd confluence export` and friends work without per-machine
   setup. The token reference is fine to commit (1Password op://
   reference, not the secret). Probably yes; document the pattern.
4. **Authoring sequence — fixtures or long-form first?** Fixtures
   provide systematic coverage; long-form provides realistic
   shape distribution. Suggest fixtures first (faster to write,
   exercises more shapes per word).

## Next research note

`R08-confluence-ir-experiment-harness.md` — the experiment runner
that consumes this corpus and produces comparison reports for the
three candidate IR pipelines. Specifies metric definitions, output
format, and how the three spikes (notes 009–011) plug in.
