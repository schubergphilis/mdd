# S06: Documentation Site

**Purpose:** Publish a Starlight documentation site at <https://schubergphilis.github.io/mdd/> on every merge to `main`, built from checked-in Markdown under `docs/`, whose primary content is operator documentation and whose secondary content is the existing spec and research corpus, demoted.

**Status:** Draft

## Introduction

`mdd` has 38 specs, 14 research notes, a README, `CONTRIBUTING.md` and
`AGENTS.md`. All of it is design record or contributor guidance. There is
nothing for somebody who wants to mirror a Confluence space and needs to know
what will happen to their data.

`mdd` is a documentation tool, so the absence of its own documentation is a
credibility problem as well as a usability one.

Four audiences read this project's documentation, and they want nearly
disjoint things:

| Audience | Wants | Has today |
|---|---|---|
| Operator | install, first run, what can clobber production, config and secrets | ~40 lines of README |
| Integrator | extension points, config schema, stability expectations | one README paragraph |
| Contributor | conventions, gates, spec discipline | well served already |
| AI agent | machine-readable command tree, skills, conventions | `AGENTS.md`, the skills bundle |

The operator is the entire gap; the integrator is second. This spec covers the
site that closes it, and the content pipeline that keeps it supplied without
hand-maintenance.

Originates from research note R14.

## Requirements

1. The site is published at <https://schubergphilis.github.io/mdd/> on every
   merge to `main`, with no manual step.
2. All prose content is checked-in Markdown under `docs/`, readable on GitHub
   without a build step. The site renders that Markdown; it is not where the
   Markdown lives.
3. Every asset the site ships — palette, fonts, styles — is under a licence
   compatible with `mdd`'s own, and is redistributable by anyone who forks the
   repository.
4. An operator can install `mdd`, run a first command that produces visible
   output, and learn which operations can destroy data — without access to a
   Confluence or SharePoint tenant.
5. Specs and research notes are published without per-file hand maintenance,
   and are demoted so they do not dominate the site.
6. No hand-written page asserts a fact that a generator could state.
7. Every `mdd …` command string appearing in prose corresponds to a real
   command, enforced in CI.
8. `mise run ci` does not require a Node toolchain.
9. A site build failure is caught when the change is proposed, not when it is
   deployed.

## Design Approach

### Audience first, Diátaxis within

The site is organised operator-first. Diátaxis (tutorial, how-to, reference,
explanation) applies *within* the operator and integrator sections as a
coverage check, not as top-level navigation — at roughly ten hand-written
pages, four top-level sections would be structure for its own sake.

The spec corpus is not user documentation. Publishing it is cheap and worth
doing, but if 52 of 60 pages are design record the site reads as an
engineering archive. It is therefore demoted (see below).

### Freshness tiers

Every page is classified by how it stays true, and the classification
determines who maintains it:

1. **Generated** from code — always true, zero maintenance, low insight.
2. **Executed** in CI — true, or the build is red.
3. **Checked** structurally — links resolve, `mdd …` strings are real
   commands, generated output has not drifted.
4. **Prose** — the *why*. Decays; needs a human.

The governing rule, and requirement 6 restated: never hand-write what can be
generated, and never let prose assert a fact a generator could state. Prose's
job is *why*, *when*, and *don't*.

### Repository layout

The Astro application lives in `site/` at the repository root. `docs/` stays a
pure Markdown corpus.

```
mdd/
├── docs/                     checked-in Markdown, no build artefacts
│   ├── guide/                operator documentation (new)
│   ├── reference/            generated, committed (Phase 3+)
│   ├── research/
│   └── spec/
├── scripts/
│   └── sync-docs.py
├── site/                     Astro + Starlight application
│   ├── astro.config.mjs
│   ├── package.json
│   ├── bun.lock
│   └── src/
│       ├── content/docs/
│       │   ├── index.mdx     hand-authored landing page
│       │   ├── guide/        synced (gitignored)
│       │   ├── reference/    synced (gitignored)
│       │   ├── spec/         synced (gitignored)
│       │   └── research/     synced (gitignored)
│       └── styles/custom.css
└── src/mdd/
```

This diverges from the Starlight convention, which puts a project's own site
in `docs/`, and from the organisation repository, which does the same. The
reason is specific to this project: `mdd` is a Markdown-mirror tool and
`docs/` is the tree it would plausibly be pointed at, so `node_modules/`,
`dist/` and `.astro/` do not belong in it, and every `docs/**.md` glob would
otherwise need an exclusion. The divergence costs one line per mise task and
one path in the deploy workflow.

A separate documentation repository and a `gh-pages` branch were both
considered and rejected. None of the usual reasons to split a docs repository
apply — one developer, docs that move with code, and AI agents that read the
whole repository — and GitHub's recommended Pages flow is an uploaded artifact
rather than committed build output.

### Content pipeline

`scripts/sync-docs.py` runs before the Astro build. It copies `docs/**.md`
into `site/src/content/docs/`, deriving Starlight frontmatter from each file's
heading, injecting the design-record banner and demotion frontmatter, and
rewriting repo-relative links so links to published pages resolve on the site
while links to source files resolve on GitHub.

Astro's `glob()` content loader was considered as an alternative, pointing
directly at `../docs`. It is rejected on a technical ground rather than a
convenience one: recent Starlight versions apply their remark and rehype
plugins **only** to content loaded through `docsLoader()`. Content pulled in
through a bare `glob()` silently loses Starlight's Markdown processing,
including the aside directive plugin the guide pages depend on. Copying into
`src/content/docs/` and leaving `docsLoader()` in place keeps all of it, and
also handles the two problems the loader does not: 52 existing files have no
Starlight frontmatter, and they are full of repo-relative links.

Synced output is gitignored. It is build input, not source.

### Generated reference pages are committed

Generated documentation — the CLI reference in Phase 3, and anything like it
later — is written to `docs/reference/`, committed, and guarded by a drift
gate in `mise run ci` that regenerates and fails on a diff. It is then synced
into the site by the same script as everything else in `docs/`, with no special
case.

The deciding reason is that **the diff is review signal**. A pull request that
adds a flag shows the reference change beside the code change, so a reviewer
catches a rename, a dropped option or an accidental breaking change by reading
the diff, without running anything. Generating at build time discards that: the
CLI surface changes silently and nobody sees the rendered result until a reader
does.

Two supporting reasons. It keeps the Astro build free of the Python toolchain,
which is what makes requirement 8 hold — a site build that shells out to
`uv run mdd help --json` would need a Python environment in the deploy
workflow. And `docs/reference/*.md` renders on GitHub, so it serves someone
reading the repository who never visits the site.

The cost is git noise and merge conflicts between concurrent branches. Write
one file per command group rather than one monolith, so a conflict stays inside
the command that was actually touched. Hand-edits need no separate control; the
drift gate catches them by construction.

This follows the `complexipy-snapshot.json` pattern already in the repository:
generated artefact in git, regeneration is a normal part of the change, CI
fails if you forget.

### Markdown dialect for guide pages

Guide pages are plain `.md` in `docs/guide/`, carrying a small amount of
site-specific syntax. This follows the project's existing pattern: `mdd`
already tolerates Confluence-specific syntax (`{=confluence}` fenced blocks)
inside otherwise-plain Markdown rather than restricting the source format.

The primary escape hatch is GitHub alert syntax, which renders natively on
GitHub, plus a remark plugin mapping it onto Starlight asides. Starlight does
not support GitHub alerts natively because the variants do not correspond
one-to-one, so the mapping is explicitly lossy:

| GitHub | Starlight aside |
|---|---|
| `> [!NOTE]` | `note` |
| `> [!TIP]` | `tip` |
| `> [!IMPORTANT]` | `caution` |
| `> [!WARNING]` | `caution` |
| `> [!CAUTION]` | `danger` |

Starlight's `:::caution` directive syntax remains available for cases the
mapping cannot express; it renders as literal text on GitHub, which is the
cost of using it.

Tabs, Steps, Cards and CardGrid are MDX-only and are not available in `.md`.
Guide pages do without them. One hand-authored `index.mdx` lives in `site/`
for the landing page, since a hero and card grid are presentation rather than
documentation.

### Demoting the design record

Specs and research notes are published, but on three demotion axes, all
applied by `sync-docs.py` as injected frontmatter:

- `pagefind: false`, so they never surface in site search.
- Excluded from `llms.txt` and `llms-full.txt`.
- A single collapsed sidebar group at the bottom, with a `banner` on every
  page stating the document describes intent at time of writing.

Research notes are published rather than left on GitHub specifically so that
synthesised articles have citation targets resolving on the same site.

### Synthesised articles

The specs and research notes are written for agents and human reviewers. They
are precise and cross-referenced, and they are not prose anyone reads for
pleasure. Publishing them raw gives the site bulk without giving it a reason
to exist.

They are therefore treated as primary sources, and the site publishes
secondary literature: article-shaped pages telling a higher-level story and
citing the specs and notes underneath. A skill in `.claude/skills/` drafts
these; a human tightens them.

This is the only content on the site with no mechanical backstop. The CLI
reference has a drift gate, examples have tests, links have a checker, prose
has Vale — a synthesised article has none of that, and no check can detect
that it misrepresented a source. Three constraints follow, and the skill must
enforce them:

- **Citation density.** Every non-obvious claim links to the spec or note it
  came from. The purpose is reviewability: the check becomes "does this
  sentence match the cited paragraph" rather than "does this match my memory
  of the corpus".
- **Preserve reversals.** Dead ends, rejected options and superseded
  recommendations are the payload. A model synthesising a corpus will by
  default produce a tidy narrative in which the right answer was reached
  directly; that erases the most interesting content and yields prose with no
  opinions in it.
- **Never overwrite.** Drafts go to `site/src/content/docs/_drafts/`. The
  underscore prefix is already what `docsLoader()` ignores, so drafts do not
  build. Promotion is a `git mv`. Re-running the skill against a promoted
  article diffs and proposes; it does not overwrite.

### Deployment

The deploy workflow is ported from the organisation repository: a build job,
`upload-pages-artifact`, then a deploy job targeting the `github-pages`
environment with `pages: write` and `id-token: write`, under a `pages`
concurrency group that does not cancel in flight.

One addition: `actions/checkout` must set `fetch-depth: 0`. Starlight's
`lastUpdated` derives each page's date from git history, and a shallow clone
would make every page display the deploy date instead — wrong in a way that
looks plausible.

### Gates

Checks are split by what makes them fail, not by what kind of check they are.

| Check | Fails because | Runs in |
|---|---|---|
| Generated reference drift | code changed | `mise run ci` |
| `mdd …` strings resolve against the command tree | code changed | `mise run ci` |
| Vale prose lint | prose changed | `mise run docs-check` |
| `astro check` and site build | prose or site config changed | `mise run docs-check` |
| External link rot | neither; links rot on their own | scheduled workflow |

Code-coupled checks must be in `mise run ci` because a docs-only workflow does
not run on a Python pull request — and that is precisely the change that
invalidates a doc. Prose checks are path-filtered on `docs/**` and `site/**`;
nothing goes silently red there, because none of them can be broken by a code
change.

`mise run ci` stays Node-free. It is the local gate run on every change, and
requiring `bun install` would tax every contributor for changes unrelated to
documentation. All the code-coupled checks are pure Python.

The site build runs on documentation pull requests (requirement 9). Without
it, a broken Astro configuration surfaces at deploy time.

### Versioning and freshness display

One version, at the site root, with no versioning plugin. `mdd` installs from
git `main`, so there is no released version to document, and a version
selector offering choices nobody can install would be worse than none.
Versioning plugins keep the current version at the root and prefix archived
versions, so nothing about this decision has to be unwound later.

The site displays the **date** it was built, not the commit sha. A sha would
imply the pages were verified against that commit, which they were not.

Pages display Starlight's git-derived `lastUpdated`. A manual `last-reviewed`
field was considered and rejected: it is a promise to re-read, and a stale one
is an affirmative false claim of freshness, which is worse than silence.

### Operator content without a tenant

The quickstart is offline — `mdd convert`, `mdd new`, `mdd search` — which
satisfies requirement 4 and is also the set that can execute in CI later.

A shared example Confluence space was considered and rejected on structural
grounds: a quickstart's job is to have the reader run a command that does
something, and for Confluence that command writes. Strangers cannot be given
write access to the corpus instance, so a shared demo space cannot serve a
sync quickstart at all. That instance is also already load-bearing for the
test corpus; pointing public documentation at it would make it load-bearing
twice.

Confluence and SharePoint therefore get separate bring-your-own-tenant
how-tos, opening safety-first: scratch space, read-only export first, sync
only after. Where documentation needs to show real content, it uses the
committed snapshots under `tests/corpus/confluence/`.

## Implementation Notes

**Theme.** The site uses **LSD Warm**, a warm amber-on-brown palette with
matching light and dark modes. It is not a corporate theme, and that is the
point: `mdd` is Apache-2.0, and a fork should be able to take the whole
repository, including its documentation site, without inheriting a trademark
or a brand licence it has no rights to. A corporate brandbook cannot give that
guarantee.

The palette's source of truth is `colors/lsd-colors.json` in
[`lsimons/lsimons-dotfiles`](https://github.com/lsimons/lsimons-dotfiles),
which is Apache-2.0 — the same licence as this project. Copy the token values
into `site/src/styles/custom.css` and credit the source in a comment. Do not
add a build-time dependency on the dotfiles repository; the palette is a few
dozen hex values that change rarely, and vendoring them keeps the site
buildable from this repository alone.

Starlight derives every surface, text and border colour from three ramps, so
mapping those restyles the whole site. Dark mode is `:root`, light mode is
`:root[data-theme='light']`:

| Starlight token | LSD Warm dark | LSD Warm light |
|---|---|---|
| `--sl-color-accent` | `#c17a23` | `#c17a23` |
| `--sl-color-accent-low` | `#4a2f08` | `#f6e4c4` |
| `--sl-color-accent-high` | `#eabb79` | `#8f5610` |
| `--sl-color-white` (headings) | `#ffebd2` | `#241100` |
| `--sl-color-gray-2` (body) | `#dfcab2` | `#4a3418` |
| `--sl-color-gray-3` (muted) | `#8a7761` | `#594329` |
| `--sl-color-gray-5` (borders) | `#3a2b16` | `#dbcbb9` |
| `--sl-color-gray-6` (nav, sidebar) | `#1f1000` | `#f0dfc9` |
| `--sl-color-black` (page) | `#1a0c00` | `#faf1f3` |

Light-mode `accent-high` is deliberately darker than the palette's raw accent;
the unmodified value does not reach contrast on the light background.

**Fonts.** Merriweather for long-form prose (`.sl-markdown-content`),
Merriweather Sans for UI chrome (`--sl-font`), and a system-first monospace
stack for code. Both faces are SIL Open Font License 1.1, so they can be
redistributed with the site.

Self-host them through `@fontsource/merriweather` and
`@fontsource/merriweather-sans` rather than linking Google Fonts. Three
reasons: it removes a third-party runtime dependency from a page that
otherwise has none; it avoids sending every reader's IP address to Google,
which is a live legal question in the EU; and it makes the "everything ships
under a licence we can redistribute" requirement literally true rather than
true-by-reference.

**Site configuration.** `base: '/mdd/'`, `pagefind` and `pagination` enabled,
`customCss: ['./src/styles/custom.css']`, and mise tasks `docs-install`,
`docs-dev`, `docs-build`, `docs-preview`, `docs-check` with `dir = "site"`.
The reference implementation is a single splash page and carries rules that do
not belong here — the `h1#_top` hiding rule, the collapsed first
`.content-panel`, and the always-visible `.right-group` nav. A documentation
site with a sidebar needs none of them.

**Agent-facing output.** `llms.txt`, `llms-full.txt` and `llms-small.txt` come
from the `starlight-llms-txt` plugin — a plugin entry and a `projectName`
option, with the design record removed via its exclude patterns. Per-page raw
Markdown twins are the higher-value half for an agent-facing tool and should
be added alongside; direct fetches of `llms.txt` by AI crawlers are rare in
practice, while agents pointed at a specific page do fetch its Markdown.

**Vale.** Start minimal and tighten later, once there is enough live content to
judge a rule by the findings it produces rather than by how it reads in the
abstract. The initial configuration is:

- `BasedOnStyles = Vale` — the built-in spelling and repetition checks.
  Spelling uses Vale's default American English dictionary.
- Two named rules from the MIT-licensed `write-good` package, enabled
  individually rather than by adding the whole style: `write-good.Passive` and
  `write-good.Cliches`. Naming a rule enables it without pulling in the
  package's other seven.
- A vocabulary accept-list seeded with the project's domain terms
  (`Confluence`, `SharePoint`, `frontmatter`, `roundtrip`, `mddignore`,
  `Quarto`, `docling`).
- `filter_mode: added`, at warning level.

Both rules are chosen for the same reason: much of `mdd`'s audience reads
English as a second language. Passive constructions and idiom are what that
reader stumbles on, and neither is a matter of taste that a reviewer needs to
adjudicate. Deliberately **not** adopted are the Google and Microsoft style
packages. They encode a house voice for an organisation standardising across
many writers; this repository has one writer and an established voice, so
either package would mean suppressing most of it or rewriting prose that is
fine.

Vale runs over hand-written prose only — `docs/guide/` and the hand-authored
pages under `site/src/content/docs/` — and not over `docs/spec/`,
`docs/research/`, or generated reference output. The design record is written
for a different reader in a different register.

`write-good` is fetched by `vale sync` from a pinned release URL
(`v0.4.1`); the synced `styles/write-good/` directory is gitignored. That
makes the prose gate depend on the network, which is one more reason it sits
in `mise run docs-check` rather than `mise run ci`.

Follow-up, deferred until after Phase 2 ships and the guide has real content:
revisit the rule set against the findings it actually produced. Likely
additions are `write-good.TooWordy` and `write-good.Weasel` (same
non-native-reader rationale), sentence-length and readability rules, and
American-English adaptations of the parts of the GOV.UK content guidance that
survive the change of register. The tone rules that prose review currently
catches by hand — `simply`, `seamlessly`, `powerful`, `robust`, `easily` —
belong in that pass too, as a custom style rather than a packaged one.

**`.gitignore` additions.** `site/node_modules/`, `site/dist/`,
`site/.astro/`, and the synced content directories
(`site/src/content/docs/{guide,spec,research}/`).

## Rollout plan

| Phase | Content | Specified |
|---|---|---|
| 0 | `site/`, LSD Warm theme, deploy workflow, ~10 operator pages in `docs/guide/` | here |
| 1 | `sync-docs.py`, spec and research publishing, Pagefind, `llms.txt` | here |
| 2 | Article-synthesis skill and the first articles | here |
| 3 | `mdd help --json` and a generated CLI reference with a drift gate | own spec |
| 4 | Executable examples in guide pages | own spec |
| 5 | Architecture contracts and a generated module graph | own spec |
| 6 | Curated extension API reference for wrapper authors | own spec |

Phase 2 is deliberately early. Articles are what make the site worth visiting
rather than worth searching. It is not Phase 0 because an essay on IR design
sitting next to no install page would be the wrong site.

Every gate in this spec starts at its minimum useful setting and is tightened
after Phase 2, not before. A rule is easier to argue about once there is
content for it to fire on. This applies most visibly to Vale, where the
follow-up is written out in the implementation notes, but the same holds for
the link checker's allow-list and for how strictly `astro check` is run.

Phase 0's pages: landing page, Install, Quickstart (offline), Concepts (mirror,
IR, sync direction), Safety, Configuration and secrets, Commands overview,
first Confluence sync, first SharePoint sync, and a pointer to the design
record.

Candidate first articles, drawn from the existing corpus and organised by
story rather than by spec: why `mdd` has its own document IR; what
"near-lossless" actually means; publishing into Confluence without clobbering
it; and spec-driven development with AI agents.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions.
- [S02](S02-mdd-cli-tool.md) and [S35](S35-argparse-cli-parsing.md) — the CLI
  surface a later `help --json` dump has to cover, and the source of truth for
  the `mdd …` string check.
- [S07](S07-data-protection.md) and [S26](S26-managed-elsewhere.md) — source
  material for the Safety page and the bring-your-own-tenant how-tos.
- [S23](S23-skills-bundle.md) — the skills bundle the article-synthesis skill
  sits alongside.
- [S34](S34-code-quality-gates.md) — where the `docs-check` gate and the
  code-coupled documentation checks are enforced.
- [S32](S32-ir-test-corpus-expansion.md) — the corpus supplying real
  before/after content to conversion documentation.

## Open questions

1. ~~Does `starlight-llms-txt` work against Astro 7?~~ **Resolved.** Yes.
   `starlight-llms-txt` `0.11.0` declares `astro: ^7.0.0` and
   `@astrojs/starlight: >=0.41.0`. Pin `^0.11.0`.
2. ~~Which Vale style baseline — the Google or Microsoft package, or custom
   rules only?~~ **Resolved.** Neither package. Vale's built-in style plus
   `write-good.Passive` and `write-good.Cliches`, with a follow-up pass after
   Phase 2. See the Vale implementation note.
3. ~~Do generated reference pages get committed and drift-gated, or generated
   at build time and never stored?~~ **Resolved.** Committed to
   `docs/reference/`, drift-gated in `mise run ci`. See "Generated reference
   pages are committed".
4. ~~Does the article-synthesis skill live only in `.claude/skills/`, or also
   ship in the `mdd skills` bundle?~~ **Resolved.** `.claude/skills/` only.
   Every bundled skill drives `mdd` the command; this one drives this
   repository's corpus and writes into `site/`, which a wrapper does not have.
   [S23](S23-skills-bundle.md)'s `register_skill_root` already lets a wrapper
   ship its own version, so the core does not need to generalise one for zero
   known consumers.
5. ~~Should `docs/guide/` be mirrored into Confluence by `mdd` itself as a
   dogfooding exercise?~~ **Resolved.** Not in this spec. Requirement 4 says a
   reader needs no tenant; the same applies to the build. A wrapper repository
   that already has a tenant can push `docs/guide/` into an internal space as a
   one-way job, exercising the same code path at no cost to the core.

No open questions remain.

## Out of scope

- CLI reference generation and `mdd help --json` (Phase 3, own spec).
- Executable examples and the harness for running code blocks from
  documentation (Phase 4, own spec).
- Architecture contracts and generated dependency graphs (Phase 5, own spec).
- API reference for the extension surface (Phase 6, own spec).
- Documentation versioning and a version selector.
- Internationalisation.
- Search beyond Pagefind's defaults.
- Vale as an `mdd` feature. Running a prose linter over mirrored content — as a
  check before a push, or as a deterministic complement to what `mdd ai`
  currently does with a model — is a plausible and much larger piece of work,
  with an audience well beyond this repository's documentation. Here, Vale is
  only a local gate on this project's own prose. If the feature is pursued it
  gets its own research note and spec.
- Bidirectional sync between a Starlight site and Confluence as an `mdd`
  feature. The one-way push described under open question 5 is a wrapper-local
  job. Treating a Starlight content tree as a first-class mirror target, with
  sync in both directions, is a product capability of its own and would need
  its own research note and spec.
- Migrating `README.md`, `CONTRIBUTING.md` or `AGENTS.md` into the site. They
  stay at the repository root; the site may restate their content but does not
  replace them.
