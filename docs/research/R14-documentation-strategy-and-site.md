# 014 - Documentation strategy and a docs site for mdd

**Status:** Research notes. Not an implementation spec.

**Problem brief.** `mdd` has been developed with a single developer
and an audience of AI agents, so its written record is almost
entirely a design record: 38 specs, 13 research notes, a 130-line
README, and `CONTRIBUTING.md`/`AGENTS.md`. There is nothing for
somebody who wants to mirror a Confluence space and needs to know
what will happen to their data. The project is also a documentation
tool, so the absence of its own documentation is a credibility
problem as much as a usability one.

The intent is a site at <https://schubergphilis.github.io/mdd/>,
built with [Starlight](https://starlight.astro.build/) and themed to
match the org site at
<https://github.com/schubergphilis/schubergphilis.github.io>,
deployed from `main` on every merge, publishing hand-written user
documentation alongside the existing specs and research notes.
(The theme half of that brief was later dropped on licensing
grounds — see the superseded note under "Site generator".)

This note frames the audiences, proposes a way to decide what to
generate versus what to write, surveys the tooling against external
sources as of July 2026, and records the counterpoints that came
back. It stops short of a design: the sequencing at the end is a
recommendation, and the open questions at the end are real.

## Audience before Diátaxis

[Diátaxis](https://diataxis.fr/) is the standard framing and the
right vocabulary: four documentation modes — tutorials
(learning-oriented), how-to guides (task-oriented), reference
(information-oriented), and explanation (understanding-oriented) —
positioned on two axes, acquisition versus application and practical
versus theoretical. [`/start-here/`](https://diataxis.fr/start-here/)
and [`/compass/`](https://diataxis.fr/compass/) are the two pages
worth reading before writing anything; `/compass/` in particular is
a decision procedure for "what kind of page is this?" rather than a
taxonomy to memorise.

Two caveats came back from the survey and both apply here.

The framework is a diagnostic tool, not a literal site map. The
[most useful framing in the Hacker News
discussion](https://news.ycombinator.com/item?id=42340740) of
[Sequin's
adoption](https://blog.sequinstream.com/we-fixed-our-documentation-with-the-diataxis-framework/)
is that it is good for asking whether an area has tutorial,
how-to, reference and explanation coverage, without implying those
must live on separate pages. Daniele Procida has said the same in
response to the "four rigid buckets" critique, summarised by Tom
Johnson in [What is Diátaxis and should you be using
it?](https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework).
For a site with maybe ten hand-written pages, four top-level
sections would be structure for its own sake.

Adoption makes things look worse before better. Canonical's
[account of adopting
Diátaxis](https://ubuntu.com/blog/diataxis-a-new-foundation-for-canonical-documentation)
is candid that the first effect is that existing documentation stops
being able to hide its problems. That is a feature here — there is
almost nothing to disrupt.

The more load-bearing split for `mdd` is audience, because there are
four and they want nearly disjoint things:

| Audience | Wants | Has today |
|---|---|---|
| **Operator** — runs `mdd confluence sync-space` | install, first sync, what can clobber production, config and secrets | ~40 lines of README |
| **Integrator** — writes a `MirrorBackend`, wraps `mdd` | extension points, config schema, stability expectations | one README paragraph, a link to `mdd-wrapper` |
| **Contributor** | conventions, gates, specs | good already |
| **AI agent** | machine-readable command tree, skills, conventions | `AGENTS.md`, the skills bundle |

The operator is the entire gap. The integrator is second and has
exactly two real consumers today (`mdd-wrapper`, `sbp-mdd`). Diátaxis
then applies *within* the operator and integrator sections, not
across the site.

A corollary worth stating plainly: **the spec corpus is not user
documentation.** Publishing it is cheap and worth doing, but 52 of
roughly 60 pages being design record makes the site read as an
engineering archive. It belongs in a clearly-labelled section with a
standing banner saying it describes intent at time of writing and
that the command reference is generated from code.

## Freshness tiers

The organising idea that seems most useful for a one-developer
project is to rank every page by *how it stays true*:

1. **Generated** from code — CLI reference, config schema, module
   graph. Always true, zero maintenance, low insight.
2. **Executed** in CI — how-tos whose code blocks actually run.
   True, or the build is red.
3. **Checked** structurally — links resolve, every `mdd …` string in
   prose is a real command, generated reference has not drifted.
4. **Prose** — the *why*. Decays. Needs an owner and a date.

The rule that falls out: never hand-write what can be generated, and
never let prose assert a fact a generator could state. Prose's job is
*why*, *when*, and *don't*.

This matches the external consensus on where LLM-generated
documentation is safe. Fabrizio Ferri-Benedetti's [What's wrong with
AI-generated docs](https://passo.uno/whats-wrong-ai-generated-docs/)
is not an anti-AI piece; it limits LLM generation to "carefully
delimited scenarios like API docs or code snippets, where
documentation is produced from clear, concise sources in almost
programmatic ways" — which is tier 1, done by a generator rather
than a model. It also names the failure this project should care
about most: documentation exists to say what you *cannot* or
*should not* do, and that is the part a model has no grounding for.
`mdd confluence sync-space` can clobber a production space; nothing
in the codebase tells a model how bad that is.

Two 2026 papers back the same split from the other direction. ["An
Endless Stream of AI Slop"](https://arxiv.org/html/2603.27249v1)
codes 1,154 posts across 15 threads into Review Friction, Quality
Degradation, and Forces and Consequences, and documents
overconfident-hallucination "death loops". [Cherryleaf's 2026
survey](https://www.cherryleaf.com/2026/06/ai-in-technical-communication-2026/)
(n=109, mostly technical writers) found 62% use AI regularly or
daily but flagged that weak AI drafts often take longer to fix than
human-written ones. The mitigation both point at is the same: ground
output in a source of truth, and validate mechanically.

## Site generator

**Recommendation: Starlight, as intended.** But the survey turned up
a genuine counterpoint that should be recorded, because the naive
version of it points the other way.

The stock 2026 advice for a Python project is Material for MkDocs —
same virtualenv, no Node toolchain, `mkdocstrings` for API docs, and
it powers FastAPI, Pydantic, Polars and Ruff. That advice is now
substantially undercut:

- Material for MkDocs [entered maintenance
  mode](https://squidfunk.github.io/mkdocs-material/blog/2025/11/05/zensical/)
  in early 2026. 9.7.0 was the last feature release, and it is
  scheduled to reach end of life on 5 November 2026.
- Its successor, **Zensical**, is a from-scratch Rust rewrite, still
  pre-1.0 and in early development, with third-party modules only
  opening up during 2026.
- MkDocs 2.0 is a ground-up rewrite that removes the plugin system
  entirely, putting MkDocs core and its most popular extension in
  direct conflict.

So the "safe, boring Python choice" is currently the one with a
migration ahead of it. Starlight, by contrast, is at 0.41.x on Astro
7, ships Pagefind search, dark mode and i18n in the box, and Astro
had the highest retention of any SSG in State of JS 2025. The real
cost is honest and unchanged: a `package.json`, `bun`, and a Node
build step in a pure-Python repo, which raises the bar for outside
contributors who want to preview a docs change.

That cost is already paid elsewhere — both candidate reference sites
are Starlight with a `bun`-based mise task set. Decision stands; the
Node dependency is the price.

**Superseded: which theme.** This note originally called for matching
the organisation site,
[`schubergphilis.github.io`](https://github.com/schubergphilis/schubergphilis.github.io)
— its SBP Blue token ramps, blue header block and Poppins. That was
dropped before [S06](../spec/S06-documentation-site.md) was written.
`mdd` is Apache-2.0 and the corporate brand is not; a fork cannot
redistribute it. The theme is instead **LSD Warm**, whose palette
lives in `colors/lsd-colors.json` in
[`lsimons/lsimons-dotfiles`](https://github.com/lsimons/lsimons-dotfiles)
under Apache-2.0, with Merriweather and Merriweather Sans under the
SIL OFL. A working Starlight mapping of that palette already exists in
[`lsimons/lsimons.github.io`](https://github.com/lsimons/lsimons.github.io).
S06 carries the token table.

What survives from the original port list regardless of theme: the
mise task names (`docs-install`, `docs-dev`, `docs-build`,
`docs-check`), and `deploy.yml` with its pinned action SHAs and
`concurrency: pages`. Two deltas from either reference site: set
`base: '/mdd/'`, and turn `pagefind` and `pagination` back on — both
are single splash pages and disable them. Their splash-specific CSS
(the `h1#_top` hiding rule and the collapsed first `.content-panel`)
must not be carried over.

## Getting `docs/` into the site

The specs and research notes must stay readable as plain Markdown on
GitHub — this is a tool about Markdown-in-git, and `docs/spec/` is
the durable record. So the site reads them; they do not move into the
site.

Starlight's `docsLoader()` is hardcoded to `src/content/docs/`.
Loading from elsewhere is a [known, requested-but-unimplemented
feature](https://github.com/withastro/roadmap/discussions/434) (see
also [Starlight discussion
#1257](https://github.com/withastro/starlight/discussions/1257)).
The documented workaround is to swap `docsLoader()` for Astro's
`glob()` loader with `base` pointing outside the app, keeping
`schema: docsSchema()`. Two caveats: `glob()` does not apply
Starlight's sluggification, so URLs differ unless a `generateId()` is
supplied, and the `**/[^_]*.md` pattern has to be reproduced by hand
to preserve the underscore-ignore behaviour.

That workaround handles path resolution but not the two problems that
actually matter here: 52 spec and research files have no Starlight
frontmatter (no `title`, no sidebar ordering), and they are full of
repo-relative links (`../spec/S14-...md`, `../../src/mdd/...`) that
must be rewritten differently depending on whether the target is a
published page or a source file on GitHub.

It is also disqualifying on its own terms. Recent Starlight versions
apply their remark and rehype plugins **only to content loaded via
`docsLoader()`**. Content pulled in through a bare `glob()` loader
therefore loses Starlight's markdown processing — including the
aside directive plugin, which is the one Starlight component that
works in plain `.md` and the mechanism the guide pages depend on
(see below). Copying into `src/content/docs/` and leaving
`docsLoader()` in place keeps all of it.

**Recommendation: a `scripts/sync-docs.py` prebuild step** that
copies `docs/**.md` into the site's content directory, derives
frontmatter from the `# 0NN - Title` heading, injects the "design
record" banner, and rewrites links. It is a dumber mechanism than a
custom Astro loader, but it is Python, it is debuggable, it is
testable with the existing pytest setup, and it is the natural place
to also emit the generated pages. Revisit if Starlight ships
first-class external sources.

## CLI reference

There are direct argparse-to-Markdown generators —
[`argdown`](https://pypi.org/project/argdown/),
[`parse2docs`](https://pypi.org/project/parse2docs/), and
[`argparse-to-md`](https://pypi.org/project/argparse-to-md/) — plus
the Sphinx-side [`sphinx-argparse-cli`](https://github.com/tox-dev/sphinx-argparse-cli),
which is the best-maintained of the family (it renders tox's and
pypa-build's docs) but is useless outside Sphinx. The standalone
Markdown generators are small single-maintainer projects, and all of
them work by reaching into argparse internals to walk the subcommand
tree.

**Recommendation: add `mdd help --json`** and generate from that.
`cli.py` is 193 lines and the command tree is registered explicitly
per module in `src/mdd/commands/`, so dumping it is small. Three
payoffs over a third-party scraper: the output is a supported public
surface rather than argparse private attributes; AI agents get a
machine-readable command tree, which matters for a tool whose
`skills` bundle exists to be driven by agents; and it feeds the
generated CLI pages and any llms.txt index from one source.

Then commit the generated Markdown and add a **drift gate** —
regenerate in CI, fail if the tree is dirty. This is the
`complexipy-snapshot.json` pattern already in the repo, and the same
shape as `spec-check`. CLI documentation then cannot rot.

## Code reference

Do not use `pydoc`. The current stack is
[Griffe](https://mkdocstrings.github.io/griffe/) as the extraction
layer — it walks the AST and produces a structured model of the
package including annotations — with a renderer on top.
`mkdocstrings-python` renders HTML for MkDocs, which is the wrong
stack here, but
[`griffe2md`](https://mkdocstrings.github.io/griffe/downstream-projects/)
emits Markdown using the same data and Jinja templates, and
**Griffonner** is a template-first generator over Griffe for
arbitrary output. Either feeds a Starlight page. Griffe is
well-established beyond docs: the OpenAI Agents SDK and PydanticAI
both use it to parse docstrings into tool schemas.

The stronger recommendation is about scope, not tooling. A full API
reference over 194 modules is high noise and low value, because
nobody imports `mdd` except wrapper authors, and they need roughly
five things: `MirrorBackend`, the converter registry, the config
schema, typed frontmatter, and the IR entry points. **Generate a
curated Extension API page over that symbol list and nothing else.**
Completeness here is a cost, not a benefit.

## Architecture documentation

This is the part that genuinely rots, and the one where the initial
instinct — run a code-graph tool and commit the graph — is worth
resisting. A committed AI-generated graph becomes a stale second
source of truth the moment a module moves, and nothing fails when it
is wrong.

**Recommendation:
[import-linter](https://import-linter.readthedocs.io/)** (2.7 at time
of writing, on grimp 3.14+). You write architecture *contracts* —
"`mdd.ir` must not import `mdd.confluence`", "`commands` may import
`converters`, not the reverse" — and CI enforces them. The contracts
file is an architecture document that is structurally incapable of
lying, which is a stronger property than any prose or generated
diagram has. It builds a directed import graph via grimp, reports
violations as full import chains, caches the graph between runs, and
notably does **not** require defining the whole architecture up
front, so it can start with two or three contracts. The known
complaint, from [Roman Imankulov's write-up](https://roman.pt/posts/python-architecture-linter/),
is that the five built-in contract types sometimes force several
contracts where one would be logical; custom contract classes are the
escape hatch.

grimp also exposes the graph, so a Mermaid layer diagram can be
generated into the site from the same data that gates CI.

The heavyweight alternative is the arc42 + C4 + Structurizr/PlantUML
+ Kroki docs-as-code pipeline, which is the European industry
standard and has good [reference
implementations](https://github.com/bitsmuggler/arc42-c4-software-architecture-documentation-example).
It is the right answer for a system with multiple deployables and
multiple teams. `mdd` is one CLI, one developer, and 194 modules;
arc42's twelve sections would be mostly empty headings, which is
exactly the symmetry-padding failure described below. (Also noted in
passing: [RAD-AI](https://arxiv.org/html/2603.28735v1) argues arc42
and C4 cannot capture probabilistic AI components, which is
tangentially relevant to the `mdd ai` surface but not worth acting
on at this size.)

Pair the contracts with exactly one hand-written explanation page —
how a sync flows end to end, and why the IR exists — carrying a
`last-reviewed` date.

## Executable examples

The idea of extracting how-tos from the test suite is good, but the
direction matters. Having a model summarise 146 test files into prose
produces precisely the hollow output described above. The inversion:
hand-lift five to eight integration tests that are already narrative
workflows into how-to pages, then wire those pages back into pytest
so the doc *is* the test. One-time human curation, permanent
automated verification.

Three candidate harnesses:

| Tool | Fit |
|---|---|
| [Sybil](https://sybil.readthedocs.io/) (10.1) | Most capable. Parses examples from source and evaluates them in the normal pytest run via `pytest_collect_file`; supports Markdown/GFM/MyST, pytest fixtures via the `fixtures` argument, skip directives, and **custom parsers**. [pytest's own docs recommend it](https://docs.pytest.org/en/stable/how-to/doctest.html) for anything beyond doctest blocks. |
| [pytest-examples](https://github.com/pydantic/pytest-examples) | Pydantic-team tool. Distinctive feature is linting/formatting examples with ruff and updating expected output in place via `--update-examples`. |
| [mktestdocs](https://github.com/koaning/mktestdocs) | Five lines of setup, runs ` ```python ` blocks and checks they do not raise. No output matching. |

**Recommendation: Sybil**, and the deciding factor is custom
parsers. Most `mdd` examples are *shell*, not Python — `mdd convert
…`, `mdd new …` — and none of the three handle shell blocks out of
the box. Sybil is the only one designed to be extended with a parser
for a block type it does not know.

Start with the offline commands (`convert`, `new`, `search`,
`.mddignore`), which already cover most of the tutorial surface, run
in a tmpdir against a fixture config. Confluence and SharePoint
examples either reuse the snapshot corpus under
`tests/corpus/confluence/_snapshots` or are explicitly labelled
illustrative — never silently untested.

## llms.txt

The evidence here is considerably worse than expected and it changes
the recommendation.

- A monitoring platform analysing 500M+ LLM bot traffic events over
  90 days found **408 direct fetches of `/llms.txt`**. Server-log
  analyses converge on roughly 97% of deployed files receiving no AI
  bot requests at all.
- As of Q1 2026 no major AI vendor has committed to reading it in
  production. Google said no on the record — Gary Illyes in July
  2025, with John Mueller comparing it to the keywords meta tag.
- SE Ranking found 10.13% adoption across 300,000 domains, but among
  the 50 most AI-cited domains, **one** had the file.

See [The State of llms.txt in
2026](https://ai.aeo.press/the-state-of-llms-txt-in-2026) for the
aggregation. Nothing here says don't ship it; it says do not build
anything bespoke for it.

**Recommendation:** use
[`starlight-llms-txt`](https://delucis.github.io/starlight-llms-txt/),
which is a plugin entry and a `projectName` option and emits
`llms.txt`, `llms-full.txt` and `llms-small.txt` at build time.
Two lines of config, done.

Then spend the actual effort on **per-page Markdown twins**, which
agents demonstrably do fetch, via
[`starlight-md-txt`](https://github.com/trueberryless-org/awesome-starlight)
or `@wave-rf/starlight-llm-tools` (which also adds copy-markdown and
open-with-AI buttons). For an agent-facing tool this is the higher
value half. One caveat from the same sources: emitting Markdown
copies of every page is duplicate content at scale, so it interacts
with crawl budget — probably irrelevant at this site's size.

## Prose gates

[Vale](https://vale.sh/) is the established prose linter: Go, no
runtime dependencies, offline, custom rules in YAML, importable
Microsoft and Google style guides. Used by Datadog, GitLab,
Microsoft, Mozilla, and the Linux Foundation.

Two patterns worth copying, both from teams that adopted it onto
existing corpora. Elastic runs it as a PR action reporting on
modified lines only. Another project used `filter_mode: added` so
pre-existing prose debt does not block CI, and cleared roughly 580
alerts just by expanding the vocabulary accept-list with legitimate
domain terms — which for `mdd` means `Confluence`, `SharePoint`,
`frontmatter`, `roundtrip`, `mddignore`, and so on. Both advise
starting at warning level and scoping it away from generated
reference output.

`mise run docs-check` is the natural home for Vale, `astro check`
and the site build, driven by a path-filtered workflow. The
code-coupled checks — the CLI drift gate and the assertion that
every `mdd …` string appearing in prose exists in the `help --json`
tree — belong in `mise run ci` instead. See question 4 for why the
split runs along that line.

## How AI-generated documentation fails

Recorded explicitly, because most of this documentation will be
AI-drafted and these are the failure modes to gate against. The first
seven are observable in output; the last three are process failures.

1. **Restating the signature in English.** "The `--force` flag forces
   the operation." Test: delete the identifier from the sentence — if
   nothing is lost, delete the sentence.
2. **Symmetry padding.** Every page gets the same four sections
   whether or not there is anything to say. Uneven documentation is
   honest documentation.
3. **Confident invention.** Flags, config keys and error strings that
   do not exist. The trust-killer, and the reason the factual layer
   must be generated rather than written.
4. **No opinion, and no "don't".** Models write "you can do X or Y",
   never "use X; Y is legacy" — and will not tell someone not to run
   `sync-space` against a production space.
5. **Timeless present tense.** Prose that implicitly claims to be
   current forever, with nothing to contradict it.
6. **Tone inflation.** "seamlessly", "powerful", "robust", "simply".
   In a documentation context `simply` is usually a lie.
7. **Examples that were never run.** Plausible, wrong, expensive to
   discover.
8. **Volume as a proxy for quality.** A model will cheerfully produce
   60 pages. 60 unmaintained pages are worse than 8 true ones.
9. **Duplication drift.** The same fact in README, index and
   quickstart; two get updated.
10. **Organised by module rather than by task.**

Countermeasures, in the order they are worth building:

- Generate tier 1, execute tier 2, gate tier 3 (see above). This
  removes categories 1, 3 and 7 mechanically.
- Vale with a banned-word list handles 6.
- A hard page budget for the hand-written layer — around ten pages
  for the first cut — handles 8.
- Starlight's git-derived `lastUpdated` on every page, plus a
  build date in the footer, handles 5 without asking anybody to
  promise anything.
- Categories 2, 4, 9 and 10 have no mechanical fix and need human
  editing. The working rule: the model produces drafts to be **cut**,
  not drafts to be approved.

## Synthesised articles from the spec and research corpus

The specs and research notes are written for agents and human
reviewers. They are precise, cross-referenced and self-contained, and
they are not prose anybody would read for pleasure. Publishing them
raw gives the site bulk without giving it a reason to exist.

The alternative is to treat them as **primary sources** and publish
**secondary literature**: article-shaped pages that tell a
higher-level story and cite the specs and notes underneath. A
`.claude/skills/` skill drafts these into `site/`, and a human
tightens them. This changes the answer to whether research notes are
worth publishing — as citation targets their staleness stops
mattering, because a citation is allowed to be from a date.

It also clarifies what tier 4 is for. An essay explaining *why* the
IR is first-party is a historical account of a decision, not a
description of current behaviour, so it does not decay the way a
reference page does. That is a much safer thing to ask a model to
write.

The corpus gives the site two derived surfaces rather than one:
articles for humans, raw Markdown and `llms.txt` for agents. Neither
audience is served the other's format.

### The risk

This is the only artifact in the plan with no mechanical backstop.
The CLI reference has a drift gate, examples have tests, links have
a checker, prose has Vale. A synthesised article has nothing — no
check can detect that it misrepresented [R12](R12-confluence-ir-comparison.md)'s
conclusion. It is defended entirely by human review, and the failure
mode is that tightening prose is pleasant while verifying claims
against 52 documents is not, so review degenerates into copyediting.

Two mechanisms make review tractable:

- **Citation density as a hard requirement.** Every non-obvious
  claim links to the spec or note it came from. The purpose is not
  reader navigation but reviewability: the check becomes "does this
  sentence match the cited paragraph" rather than "does this match
  my memory of the corpus". Link resolution and cited-document
  existence are then mechanically gateable.
- **Provenance frontmatter with a staleness gate.** `derived-from:
  [S28, S33, R09, R12]` plus `derived-at: <sha>`, and a `docs-check`
  rule that flags when any listed source has changed since that sha.
  Prose correctness is not checkable; prose staleness is, and
  staleness is the failure that actually happens. This pulls tier 4
  halfway into tier 3 cheaply. **Deferred** — see question 6. It is
  more defensible than the equivalent mechanism for guide pages,
  because an article can be silently wrong about a spec edited
  months ago and nothing surfaces it, but that argument should be
  made with four articles in hand rather than none.

### What the skill must be told

Preserve reversals. [R12](R12-confluence-ir-comparison.md) made a
recommendation and [R13](R13-confluence-ir-spike-pure-python.md)
overturned it. A model synthesising both will produce a tidy
narrative in which the right answer was arrived at directly. The
true story — the first comparison was wrong, a later spike changed
the conclusion — is the most interesting content in the corpus, and
smoothing is what synthesis does to it by default. Dead ends,
rejected options and the reasons for rejection are the payload, not
the framing. This is also the antidote to failure mode 4 above: a
story containing a wrong turn necessarily has opinions in it.

### Draft handling

Drafts are written to `site/src/content/docs/_drafts/`. The
underscore prefix is already what `docsLoader()` ignores, so drafts
never build. Promotion is a `git mv`. Re-running the skill against a
promoted article must diff and propose, never overwrite — that is
what protects the human editing pass.

### Candidate articles

Organised by story, not by spec. One-article-per-spec would be
failure mode 10 above.

- **Why `mdd` has its own document IR** — from
  [R06](R06-confluence-bidirectional-sync-ir.md),
  [R09](R09-confluence-ir-spike-status-quo.md)–[R13](R13-confluence-ir-spike-pure-python.md)
  and [`S28`](../spec/S28-document-ir-foundation.md). Four measured
  spikes; Pandoc and docling both lost to a first-party typed IR.
- **What "near-lossless" actually means** — from
  [`S31`](../spec/S31-ir-normalization-and-whitespace.md),
  [`S33`](../spec/S33-ir-roundtrip-testing-and-benchmarks.md),
  [R07](R07-confluence-test-corpus.md) and
  [R08](R08-confluence-ir-experiment-harness.md).
- **Publishing into Confluence without clobbering it** — from
  [`S07`](../spec/S07-data-protection.md),
  [`S26`](../spec/S26-managed-elsewhere.md) and
  [`S27`](../spec/S27-confluence-page-rename-move-archive.md).
- **Spec-driven development with AI agents** — from
  [`S01`](../spec/S01-spec-based-development.md),
  [`S34`](../spec/S34-code-quality-gates.md) and
  [`S37`](../spec/S37-complexipy-cognitive-complexity.md). The
  meta-story, and probably the most-read page the site would ever
  have.

## Recommended sequencing

- **Phase 0 — site, deploy, and ~10 operator pages, nothing
  generated.** Home (`index.mdx`, hand-authored in `site/`),
  Install, Quickstart (offline: `convert`, `new`, `search`),
  Concepts (mirror / IR / sync direction), **Safety** (what clobbers
  what, and when not to run a command), Configuration and secrets,
  Commands overview, "Your first Confluence sync" and "Your first
  SharePoint sync" as separate bring-your-own-tenant how-tos, and a
  pointer to the specs. This is the whole point; everything below
  amplifies it.
- **Phase 1 — auto-publish `docs/spec/` and `docs/research/`** via
  `sync-docs.py`, plus Pagefind and the `starlight-llms-txt` plugin.
  Cheap bulk, clearly demoted behind a design-record banner.
- **Phase 2 — the article skill.** Deliberately early, before the
  generated reference work: articles are what make the site worth
  visiting rather than worth searching. A beautiful essay on IR
  design next to no install page would be the wrong site, which is
  why this is not Phase 0 — but it should not wait until the end
  either.
- **Phase 3 — `mdd help --json`**, generated CLI reference pages, and
  the drift gate.
- **Phase 4 — executable examples** with Sybil and a shell-block
  parser, applied to the Quickstart first.
- **Phase 5 — import-linter contracts**, a generated module graph,
  and one hand-written architecture explanation.
- **Phase 6 — curated Extension API** via griffe2md, for wrapper
  authors.

Explicitly not recommended: a full API reference over all 194
modules, an AI code-graph pipeline committed to the repo, `pydoc`,
and a bespoke llms.txt generator.

## Cross-references

- [`README.md`](../../README.md) — source material for Phase 0's
  Install, Commands overview and Configuration pages.
- [`docs/spec/000-specs.md`](../spec/000-specs.md) and
  [`docs/research/000-research.md`](000-research.md) — the two index
  pages that become section landing pages when published.
- [`docs/spec/S02-mdd-cli-tool.md`](../spec/S02-mdd-cli-tool.md) and
  [`S35-argparse-cli-parsing.md`](../spec/S35-argparse-cli-parsing.md)
  — the CLI surface a `help --json` dump has to cover.
- [`docs/spec/S07-data-protection.md`](../spec/S07-data-protection.md)
  and [`S26-managed-elsewhere.md`](../spec/S26-managed-elsewhere.md)
  — source material for the Safety page.
- [`docs/spec/S34-code-quality-gates.md`](../spec/S34-code-quality-gates.md)
  — where a `docs-check` gate and an import-linter gate would be
  specified.
- [`docs/spec/S36-module-structure.md`](../spec/S36-module-structure.md)
  — the layering that import-linter contracts would encode.
- `lsimons/lsimons-dotfiles` — `colors/lsd-colors.json`, the
  Apache-2.0 source of the LSD Warm palette.
- `lsimons/lsimons.github.io` — an existing Starlight mapping of that
  palette, plus the mise task set and `deploy.yml` shape.
- `schubergphilis/schubergphilis.github.io` — the originally proposed
  theme, dropped on licensing grounds; still the reference for
  `deploy.yml`'s pinned action SHAs.

## Open questions

1. ~~**Where does the Astro app live?**~~ **Resolved.** `site/` at
   the repo root, so `docs/` stays a pure Markdown corpus. This
   diverges from both the Starlight convention (the Starlight repo
   puts its own site in `docs/`, sibling to `packages/`) and the org
   repo, at a cost of one line per mise task plus the `deploy.yml`
   artifact path. The deciding argument is specific to this project:
   `mdd` is a Markdown-mirror tool and `docs/` is the tree it would
   plausibly be pointed at, so `node_modules/`, `dist/` and
   `.astro/` do not belong in it. A separate docs repository and a
   `gh-pages` branch were both considered and rejected — none of the
   usual reasons to split a docs repo apply at one developer, docs
   move with code, agents read the whole repository, and GitHub now
   recommends the artifact flow (`upload-pages-artifact` +
   `deploy-pages`) over committing build output to a branch.
2. ~~**Does `docs/` get subdirectories for the new prose?**~~
   **Resolved.** `docs/guide/*.md`, alongside `docs/spec/` and
   `docs/research/`, as plain Markdown carrying a small amount of
   Starlight-specific syntax. This follows the project's own
   pattern: `mdd` already tolerates Confluence-specific syntax
   (`{=confluence}` fenced blocks) inside otherwise-plain Markdown,
   and trusts a lossy mapping between two representations rather
   than restricting the source format.

   Concretely: write GitHub alert syntax (`> [!CAUTION]`), which
   renders natively on GitHub, and add a small remark plugin
   mapping it onto Starlight asides. Starlight
   [declined](https://github.com/withastro/starlight/discussions/1884)
   to support GitHub alerts natively because the variants do not map
   1:1 — GitHub has five (NOTE/TIP/IMPORTANT/WARNING/CAUTION),
   Starlight four (note/tip/caution/danger) — so the plugin has to
   collapse IMPORTANT and WARNING onto `caution` and CAUTION onto
   `danger`. Starlight's own `:::caution` directive syntax stays
   available as an escape hatch; it renders as literal text on
   GitHub.

   Tabs, Steps, Cards and CardGrid are MDX-only and are not
   available in `.md`. Do without them initially; Markdoc and custom
   remark directives are the escape routes if a page later demands
   them. One hand-authored `index.mdx` lives in `site/` for the
   landing page, since a hero and card grid are presentation rather
   than documentation.
3. ~~**Are research notes published at all?**~~ **Resolved.** Yes,
   but demoted, and not as the main event. They are published so
   that synthesised articles have citation targets on the same site
   — a citation pointing off to GitHub is worse than one that
   resolves in place. Demotion is on three axes, all available as
   Starlight frontmatter that `sync-docs.py` injects: `pagefind:
   false` so they never surface in search, exclusion from
   `llms.txt`/`llms-full.txt` via the plugin's exclude patterns, and
   a single collapsed sidebar group at the bottom with a `banner`
   on every page. The published human-facing surface is the article
   layer described above, not the raw notes.
4. ~~**Does `docs-check` run in `mise run ci`, or only in the docs
   workflow?**~~ **Resolved.** Split by what makes a check fail, not
   by what kind of check it is.

   Checks that fail because *code* changed belong in `mise run ci`,
   because a docs-only workflow does not run on a Python PR: the CLI
   drift gate, `mdd …` strings resolving against the command tree,
   and the article provenance gate. All three are pure Python and
   fast.

   Checks that fail because *prose* changed go in a separate
   `mise run docs-check` driven by a workflow path-filtered on
   `docs/**` and `site/**`: Vale, `astro check`, and the site build.
   Nothing can go silently red, because none of these can be broken
   by a code change.

   Two constraints fall out. Node stays out of `mise run ci` — that
   task is the local gate run on every change, and requiring `bun
   install` would tax every Python contributor. And the site build
   must run on docs PRs, since `deploy.yml` only builds on merge to
   main, so without it a broken Astro config surfaces at deploy time
   rather than at review time.

   External link checking runs on a schedule rather than per-PR;
   external links rot on their own timetable and a third-party
   outage should not fail a PR.
5. ~~**What is the versioning story?**~~ **Resolved.** Single
   version at the root, no versioning plugin.

   The retrofit worry was mostly unfounded. Versioning is not native
   to Starlight — it is
   [`starlight-versions`](https://github.com/HiDeoo/starlight-versions),
   a community plugin, self-described as opinionated and in early
   development — but its model keeps the current version at the root
   and gives archived versions a slug prefix. So `/guide/install/`
   stays put and adding versioning later snapshots the then-current
   content to `/1.0/guide/install/`. There is no URL stability
   decision to make now, which was the only expensive part.

   Against adopting it today: Starlight's release notes warn that
   community plugins may need manual updates for Astro v7, and more
   decisively, `mdd` installs from git main, so there is no released
   version to document. A version selector offering choices nobody
   can install is worse than none.

   Instead the site shows the **date** it was built, injected at
   build time. Not the commit sha — a sha would imply the pages were
   verified against that commit, which they were not. A date makes
   the weaker, true claim, and matches the claim strength of
   everything else on the site.

   Revisit when the install instructions point at a tag rather than
   main.
6. ~~**Who owns the `last-reviewed` dates?**~~ **Resolved.** Nobody,
   because the field is dropped.

   A manual `last-reviewed` is a promise to re-read. At one
   developer that promise will not be kept, and a stale
   `last-reviewed` on a page nobody has looked at since is an
   affirmative false claim of freshness — failure mode 5 above in a
   different costume, and worse than saying nothing.

   Use Starlight's `lastUpdated` instead (boolean, default `false`),
   which derives the date from the file's git history and is
   overridable per page. One operational gotcha: it needs real git
   history, and `actions/checkout` defaults to depth 1, so
   `deploy.yml` must set `fetch-depth: 0` or every page displays the
   deploy date.

   A richer mechanism was considered and rejected as premature: a
   `covers: [src/mdd/convert/, S03]` frontmatter list with a CI
   warning when a covered path changed after the page's last git
   modification. At roughly ten pages this is machinery for a scale
   that does not exist, and the two code-coupled checks from
   question 4 — the CLI drift gate and `mdd …` string resolution —
   already catch most of what it would have caught, because most of
   those pages are about commands. The same cut applies to the
   `derived-from` / `derived-at` provenance gate proposed for
   synthesised articles: defer it and decide when there are actually
   articles to protect.

   Revisit when the page count outgrows what can be re-read in one
   sitting, or when somebody other than the current single developer
   starts writing pages.
7. ~~**Does the operator documentation need a working example
   Confluence space?**~~ **Resolved.** No, and the reason is
   structural rather than operational. A quickstart's job is to have
   the reader run a command that does something; for Confluence that
   command is `sync-space`, which writes. Strangers cannot be given
   write access to the corpus instance, so a shared demo space
   cannot serve a sync quickstart regardless of how the free tier is
   configured. The instance is also already load-bearing for the
   test corpus ([R07](R07-confluence-test-corpus.md),
   [`S32`](../spec/S32-ir-test-corpus-expansion.md),
   `mise run refresh-corpus`); pointing public documentation at it
   makes it load-bearing twice.

   The quickstart is therefore offline — `mdd convert`, `mdd new`,
   `mdd search` — which is the same set identified above as the
   CI-testable examples. Both constraints reduce to "no external
   service", so the page a reader can follow without a tenant and
   the page that executes in CI are the same page.

   Confluence and SharePoint get separate how-tos that open by
   stating the reader needs a space they administer, framed
   safety-first: scratch space, read-only export first, sync only
   after. Where documentation needs to show real content, use the
   committed snapshots under `tests/corpus/confluence/_snapshots/`.

## Next document

[`S06`](../spec/S06-documentation-site.md) promotes phases 0 through 2
of the sequencing above into a spec: the repository layout, the theme
port, `sync-docs.py`, the guide's Markdown dialect, the deploy
workflow, the gate split, and the article-synthesis skill. Phases 3
through 6 are separable and each get their own spec, or ride along
with the feature they document.
