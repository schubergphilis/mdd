# 000 — Research notes

This document is the entry point for the MDD research notes.

Research notes are **working documents**, not the durable design
record. They capture what was measured, what was surveyed, and why a
direction was chosen, at the moment that work happened. They are not
kept up to date as the code moves on. The durable record is
[`docs/spec/`](../spec/000-specs.md).

Notes use the `RNN-<slug>.md` form. Numbers are assigned in order,
zero-padded to two digits. Note headings still carry the original
three-digit numbering (`# 007 - …`) and the notes refer to each other
as "note 007" in prose; `R07` and `007` are the same note.

## Index

| # | Title | What it covers |
|---|-------|----------------|
| R01 | [Handling Confluence page moves, renames, and archives](R01-confluence-renames.md) | What Confluence's API exposes about page identity, and a reconciliation strategy that turns remote moves/renames/archives into git moves in the mirror. Basis for [S27](../spec/S27-confluence-page-rename-move-archive.md). |
| R02 | [Attachment conversion and bidirectional Office sync](R02-attachments.md) | Confluence attachment limits and the converter-registry idea; the SharePoint bidirectional Office-sync model. Basis for [S15](../spec/S15-converter-registry.md), [S16](../spec/S16-confluence-attachment-conversion.md), [S17](../spec/S17-confluence-office-publishing.md), [S18](../spec/S18-sharepoint-sync.md). |
| R03 | [AI agent support](R03-ai-support.md) | Survey of the LiteLLM gateway integration, the `mdd search` / `mdd ai` CLI surface, caching, and the skills bundle. Basis for [S19](../spec/S19-search-command.md)–[S23](../spec/S23-skills-bundle.md). |
| R04 | [SVG sibling rasterization](R04-svg-sibling-rasterization.md) | Why a derived `.svg.png` sibling exists, rasterizer comparison, refresh detection, and embedding behaviour. Basis for [S24](../spec/S24-svg-rasterization.md). |
| R05 | [Externally-managed Confluence pages](R05-managed-elsewhere.md) | Detection model for pages owned by external publishing automation, and the refuse-to-push cascade. Basis for [S26](../spec/S26-managed-elsewhere.md). |
| R06 | [Intermediate representation for bi-directional Confluence sync](R06-confluence-bidirectional-sync-ir.md) | Frames the IR design space (status quo + provenance / Pandoc / docling), surveys Quarto's Confluence publisher as prior art, and proposes deciding empirically. Opens the IR thread behind [S28](../spec/S28-document-ir-foundation.md)–[S33](../spec/S33-ir-roundtrip-testing-and-benchmarks.md). |
| R07 | [Test corpus for Confluence round-trip experiments](R07-confluence-test-corpus.md) | What goes in the Confluence test corpus, how it is authored, where it lives, and how tests consume it. Basis for [S32](../spec/S32-ir-test-corpus-expansion.md). |
| R08 | [Experiment harness for Confluence IR comparison](R08-confluence-ir-experiment-harness.md) | The harness that runs each candidate pipeline over the corpus: the `Pipeline` protocol, the M1–M6 metric battery, and the snapshot/live tiers. |
| R09 | [IR spike: status quo pipeline](R09-confluence-ir-spike-status-quo.md) | Baseline measurements for the pre-IR `storage_to_md` / `md_to_storage` converters. |
| R10 | [IR spike: Pandoc + custom Lua writer](R10-confluence-ir-spike-pandoc-lua.md) | Measurements for a Pandoc-JSON pipeline with a custom Lua storage writer. |
| R11 | [IR spike: docling pipeline](R11-confluence-ir-spike-docling.md) | Measurements for a `DoclingDocument`-based in-process pipeline. |
| R12 | [IR foundation comparison and recommendation](R12-confluence-ir-comparison.md) | Cross-pipeline comparison across all spikes, and the recommendation that became [S28](../spec/S28-document-ir-foundation.md). |
| R13 | [IR spike: pure-Python pipeline](R13-confluence-ir-spike-pure-python.md) | Measurements for a first-party typed IR with no external converter — the option the recommendation ultimately landed on. |

## Provenance

These notes were written while `mdd` was developed inside a private
wrapper repository, before the open-source split. They were
contributed here because the specs they underpin live here. Two of
them were split on the way in: R04 kept only its SVG half, and R05
only its generic detection model. Deployment-specific detail —
internal hostnames, in-house publishing systems, and one
integration that is not part of this project — stayed behind. Each
affected note says so in a callout at the top.

Some notes therefore contain references to paths, issue numbers, and
one-off scripts (`scripts/ir_experiment/`) that no longer exist in
this repository. That is expected for a working document; the
measurements reproduced in the notes are the durable part.

## Adding a note

1. Pick the next free number: `uv run python scripts/new-doc-number.py research`.
2. Write `docs/research/RNN-<slug>.md`, opening with a
   `**Status:**` line and a problem brief.
3. Append a row to the index above.
4. Commit with a `docs(research):` prefix.

## Relationship to specs

Specs are self-contained: they MUST NOT link out to research notes,
and any content a spec depends on is copied into the spec — see the
cross-reference convention in
[`docs/spec/000-specs.md`](../spec/000-specs.md). Two specs credit a
note by number in prose (`research note R08`, `research note R13`)
without linking; that is the most a spec should do. Research notes
may freely link to specs and to each other.
