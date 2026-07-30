# The design record

The **Design record** section at the bottom of the sidebar holds this project's
specs and research notes. They are published because they are useful, not
because they are documentation. They are not part of this guide, and they are
not written for you unless you are working on `mdd` itself.

## What is in there

**Specs** (`SNN-<slug>.md`) are the durable design record. Each one states the
purpose of a feature, the requirements it has to meet, the approach chosen, and
the options rejected along the way. Non-trivial features start with a spec
before any code is written. [000-specs](../spec/000-specs.md) is the index and
the conventions.

**Research notes** (`RNN-<slug>.md`) are working documents: surveys,
measurements, and spikes recorded at the moment that work happened. They are
not kept up to date as the code moves on, and specs deliberately do not link
back to them. [000-research](../research/000-research.md) is the index.

## What it is not

Every page in the design record describes **intent at the time of writing**. A
spec marked "Implemented" was implemented once; the code has moved since, and
the spec was not always updated to match. A research note may compare three
approaches and recommend the one that was later abandoned.

That is the point rather than a defect. Reversals, dead ends and superseded
recommendations are the most useful content in the corpus, and rewriting them
into a tidy narrative would destroy the reason to keep them.

So: this guide describes what `mdd` does. The design record describes why it
does it that way, and what else was tried. When the two disagree about
behavior, the guide is closer to right, and the command's own `--help` is
closer still.

## Why it is published

Two reasons. `mdd` is written largely by AI agents under human review, and an
agent working on this repository reads the specs before it writes code — so
they have to be findable. And the articles on this site cite the specs and
notes underneath them, which only works if the citations resolve.

The design record is excluded from site search and from the `llms.txt` files,
so it does not crowd out the guide.

## Contributing

[CONTRIBUTING.md](../../CONTRIBUTING.md) covers the development setup, the
quality gate a change has to pass, and the commit conventions.
[AGENTS.md](../../AGENTS.md) is the same ground for AI agents working in the
repository.
