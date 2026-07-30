# Documentation

Everything here is Markdown checked into the repository. It renders on GitHub,
and it is also published as a site at <https://schubergphilis.github.io/mdd/>.

The site is the better way to read it — it has search, cross-links that
resolve, and the design record tucked out of the way. This file is the map for
anyone reading the repository directly.

## What is where

| Directory | What it holds | Written for |
|---|---|---|
| [guide/](guide/) | Install, quickstart, concepts, safety, configuration, and the first-sync how-tos | operators |
| [articles/](articles/) | Longer pieces on why the design is the way it is, citing the specs underneath | anyone deciding whether to trust the tool |
| [design-record/](design-record/) | Introduction to the two directories below | contributors |
| [spec/](spec/) | The durable design record, one file per feature — start at [000-specs.md](spec/000-specs.md) | contributors, AI agents |
| [research/](research/) | Surveys, spikes and measurements, recorded when the work happened — start at [000-research.md](research/000-research.md) | contributors, AI agents |

Specs and research notes describe **intent at the time of writing**. They are
not maintained as the code moves, and a research note may recommend an approach
that was later abandoned. The guide describes what `mdd` does now; a command's
own `--help` is more current still.

Guide pages carry a numeric filename prefix (`01-install.md`) that orders them
in the sidebar. The prefix is dropped from the published URL.

## How the site is built

The Astro + Starlight application lives in [`site/`](../site/), not in this
directory. `mdd` is a Markdown-mirror tool and `docs/` is the tree it would
plausibly be pointed at, so build artefacts are kept out of it.

`scripts/sync-docs.py` runs before every build. It copies this directory into
the site's content tree, deriving the Starlight frontmatter these files do not
carry from each file's first heading, demoting the design record, and rewriting
repo-relative links so that links to published pages resolve on the site while
links to source files resolve on GitHub. It fails the build on a link that
resolves to nothing.

The synced copies are gitignored. They are build input, not source — edit the
files here.

```bash
mise run docs-install   # once: install the site dependencies
mise run docs-dev       # live-reloading server on http://localhost:4321/mdd/
mise run docs-check     # prose lint, type check, build, link check
```

The site deploys to GitHub Pages on every merge to `main`.

Two things live outside this directory and are published anyway.
`site/src/content/docs/index.mdx` is the hand-authored landing page, since a
hero and a card grid are presentation rather than documentation. And
`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` and `LICENSE` are read
from the repository root, because GitHub finds those by path and moving them
would break its pull-request and advisory flows.

## Adding to it

- A new guide page: add `docs/guide/NN-<slug>.md` with a single `# ` heading.
  Callouts use GitHub alert syntax (`> [!WARNING]`), which renders here and
  maps to a Starlight aside on the site.
- A new spec or research note: see [spec/000-specs.md](spec/000-specs.md) and
  [research/000-research.md](research/000-research.md); both have a scaffold
  task in `mise tasks`.
- A new article: drafted by the `article-synthesis` skill into
  `site/src/content/docs/_drafts/`, and promoted into `articles/` by hand once
  a person has read it.
