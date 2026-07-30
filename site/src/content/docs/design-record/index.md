---
title: The design record
description: The specs and research notes below are published because they are useful,
  not because they are documentation.
editUrl: https://github.com/schubergphilis/mdd/edit/main/docs/design-record/index.md
---

The specs and research notes below are published because they are useful, not
because they are documentation. They are not written for you unless you are
working on `mdd` itself.

## What is in here

**Specs** (`SNN-<slug>.md`) are the durable design record. Each one states the
purpose of a feature, the requirements it has to meet, the approach chosen, and
the options rejected along the way. Non-trivial features start with a spec
before any code is written. [000-specs](/mdd/spec/000-specs/) is the index and
the conventions.

**Research notes** (`RNN-<slug>.md`) are working documents: surveys,
measurements, and spikes recorded at the moment that work happened. They are
not kept up to date as the code moves on, and specs deliberately do not link
back to them. [000-research](/mdd/research/000-research/) is the index.

## What it is not

Every page here describes **intent at the time of writing**. A spec marked
"Implemented" was implemented once; the code has moved since, and the spec was
not always updated to match. A research note may compare three approaches and
recommend the one that was later abandoned.

That is the point rather than a defect. Reversals, dead ends and superseded
recommendations are the most useful content in the corpus, and rewriting them
into a tidy narrative would destroy the reason to keep them.

So: the guide describes what `mdd` does. The design record describes why it
does it that way, and what else was tried. When the two disagree about
behavior, the guide is closer to right, and the command's own `--help` is
closer still.
