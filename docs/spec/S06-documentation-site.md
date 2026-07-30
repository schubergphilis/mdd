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
3. The site's theme matches the organisation site at
   <https://github.com/schubergphilis/schubergphilis.github.io>.
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

**Theme port.** Take `src/styles/custom.css` (the SBP Blue accent and gray
token ramps, the blue header block, Poppins as the brandbook's documented
fallback), the favicon and font `head` entries, and the mise task names
(`docs-install`, `docs-dev`, `docs-build`, `docs-preview`, `docs-check`) with
`dir` changed to `site`. Two deltas from the organisation site: set
`base: '/mdd/'`, and turn `pagefind` and `pagination` back on — both are
disabled there because it is a single splash page. Do not port the `h1#_top`
hiding rule; it is splash-page-specific.

**Agent-facing output.** `llms.txt`, `llms-full.txt` and `llms-small.txt` come
from the `starlight-llms-txt` plugin — a plugin entry and a `projectName`
option, with the design record removed via its exclude patterns. Per-page raw
Markdown twins are the higher-value half for an agent-facing tool and should
be added alongside; direct fetches of `llms.txt` by AI crawlers are rare in
practice, while agents pointed at a specific page do fetch its Markdown.

**Vale.** Start at warning level with `filter_mode: added` so existing prose is
not a blocker, and seed the vocabulary accept-list with the project's domain
terms (`Confluence`, `SharePoint`, `frontmatter`, `roundtrip`, `mddignore`,
`Quarto`, `docling`). Scope it away from generated reference output. Vale also
carries the tone rules prose review otherwise catches by hand: `simply`,
`seamlessly`, `powerful`, `robust`, `easily`.

**`.gitignore` additions.** `site/node_modules/`, `site/dist/`,
`site/.astro/`, and the synced content directories
(`site/src/content/docs/{guide,spec,research}/`).

## Rollout plan

| Phase | Content | Specified |
|---|---|---|
| 0 | `site/`, theme port, deploy workflow, ~10 operator pages in `docs/guide/` | here |
| 1 | `sync-docs.py`, spec and research publishing, Pagefind, `llms.txt` | here |
| 2 | Article-synthesis skill and the first articles | here |
| 3 | `mdd help --json` and a generated CLI reference with a drift gate | own spec |
| 4 | Executable examples in guide pages | own spec |
| 5 | Architecture contracts and a generated module graph | own spec |
| 6 | Curated extension API reference for wrapper authors | own spec |

Phase 2 is deliberately early. Articles are what make the site worth visiting
rather than worth searching. It is not Phase 0 because an essay on IR design
sitting next to no install page would be the wrong site.

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

1. Does `starlight-llms-txt` work against Astro 7? Starlight's release notes
   warn that community plugins may need manual updates for that major, and the
   organisation site is on Astro `^7.0.2`.
2. Which Vale style baseline — the Google or Microsoft package, or custom
   rules only? The packaged guides carry opinions (passive voice,
   contractions) that may fight the existing house voice.
3. Do generated reference pages get committed and drift-gated, or generated at
   build time and never stored? The drift-gate pattern matches
   `complexipy-snapshot.json`, but it puts generated output in git. Decide
   before Phase 3.
4. Does the article-synthesis skill live only in `.claude/skills/`, or also
   ship in the `mdd skills` bundle so wrapper repositories can run it against
   their own spec corpora?
5. Should `docs/guide/` be mirrored into Confluence by `mdd` itself as a
   dogfooding exercise, or does that make the public documentation depend on a
   tenant?

## Out of scope

- CLI reference generation and `mdd help --json` (Phase 3, own spec).
- Executable examples and the harness for running code blocks from
  documentation (Phase 4, own spec).
- Architecture contracts and generated dependency graphs (Phase 5, own spec).
- API reference for the extension surface (Phase 6, own spec).
- Documentation versioning and a version selector.
- Internationalisation.
- Search beyond Pagefind's defaults.
- Migrating `README.md`, `CONTRIBUTING.md` or `AGENTS.md` into the site. They
  stay at the repository root; the site may restate their content but does not
  replace them.
